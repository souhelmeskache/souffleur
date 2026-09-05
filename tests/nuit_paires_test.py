"""Issue #282 : tools/banc/nuit.sh -Paires N — N parties en PARALLÈLE (N
paires Director/joueur), sans collision, sur -DryRun (aucun agent réel, la
distribution des rangs entre paires (`prochain_rang`, `slot_boucle`) est
exercée pour de vrai — DryRun n'affecte que jouer_partie, pas l'ordonnanceur).

Sur `-RunDir`/save synthétique uniquement (jamais le vrai `bench/`,
D-109/D-178) — même discipline que tests/nuit_dryrun_test.py.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from coderain.memory import Library  # noqa: E402

NUIT_SH = REPO_ROOT / "tools" / "banc" / "nuit.sh"


def find_bash():
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


BASH = find_bash()
assert BASH, "bash introuvable (Git for Windows le fournit)"


def base_env(lib_root: Path) -> dict:
    env = {
        **os.environ,
        "SAVES_DIR": str(lib_root / "saves"),
        "NUIT_CONSERVER_SAVES_DIR": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    return {k: v for k, v in env.items() if not k.startswith("GIT_")}


def lire_paire(resume: Path) -> str:
    for ligne in resume.read_text(encoding="utf-8").splitlines():
        if ligne.startswith("paire:"):
            return ligne.split(":", 1)[1].strip()
    raise AssertionError(f"pas de ligne 'paire:' dans {resume}")


def main() -> int:
    assert NUIT_SH.exists(), f"script absent : {NUIT_SH}"

    tmp = Path(tempfile.mkdtemp(prefix="nuit-paires-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Paires Test", mode="rpg",
            premise="Save 100% synthétique — Issue #282, jamais de matériau réel.",
        )
        assert slug, "création de la save synthétique a échoué"
        # #281 : nuit.sh REFUSE désormais une save sans module installé
        # (garde monde vide, à côté de la garde tour 0) — module.json +
        # locations.md non vide, 100% synthétique (D-109).
        (lib.saves.dir(slug) / "module.json").write_text(
            '{"partition": "/dev/null/partition-factice", '
            '"titre": "Module factice de test"}', encoding="utf-8")
        (lib.saves.dir(slug) / "locations.md").write_text(
            (lib.saves.dir(slug) / "locations.md").read_text(encoding="utf-8")
            + "\n## Lieu factice  {#lieu-factice}\nimportance: 3\n\n"
              "Un lieu 100% synthétique.\n",
            encoding="utf-8")
        env = base_env(lib_root)

        # --- 1. -Paires 2 -Parties 2 : une paire par partie, pas de requeue -
        run_dir_22 = tmp / "run-2-2"
        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "2", "-Paires", "2", "-Save", slug,
             "-RunDir", str(run_dir_22), "-DryRun"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert p.returncode == 0, (
            f"-Paires 2 -Parties 2 -DryRun attendu code 0, reçu {p.returncode}\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )
        print("1) nuit.sh -Paires 2 -Parties 2 -DryRun : sortie 0")

        paires_22 = set()
        for pnn in ("01", "02"):
            partie_dir = run_dir_22 / f"partie-{pnn}"
            assert partie_dir.is_dir(), f"dossier absent : {partie_dir}"
            resume = partie_dir / "resume-run.md"
            assert resume.exists(), f"resume-run.md absent : {resume}"
            paires_22.add(lire_paire(resume))
        assert paires_22 == {"01", "02"}, (
            f"2 paires pour 2 parties -- une paire par partie attendu, reçu {paires_22}"
        )
        print("2) partie-01/partie-02 jouées par deux paires DISTINCTES (paire 01 et 02)")

        nuit_md_22 = (run_dir_22 / "nuit.md").read_text(encoding="utf-8")
        assert "Paires simultanées : 2" in nuit_md_22, nuit_md_22
        print("3) nuit.md porte 'Paires simultanées : 2'")

        # --- 2. -Paires 2 -Parties 3 : requeue -- une paire rejoue une 2e
        # partie dès qu'elle se libère (budget > nombre de paires) ----------
        run_dir_23 = tmp / "run-2-3"
        p2 = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "3", "-Paires", "2", "-Save", slug,
             "-RunDir", str(run_dir_23), "-DryRun"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert p2.returncode == 0, (
            f"-Paires 2 -Parties 3 -DryRun attendu code 0, reçu {p2.returncode}\n"
            f"stdout={p2.stdout}\nstderr={p2.stderr}"
        )
        print("4) nuit.sh -Paires 2 -Parties 3 -DryRun : sortie 0")

        paires_par_partie = {}
        for pnn in ("01", "02", "03"):
            partie_dir = run_dir_23 / f"partie-{pnn}"
            assert partie_dir.is_dir(), f"dossier absent : {partie_dir}"
            paires_par_partie[pnn] = lire_paire(partie_dir / "resume-run.md")
        valeurs = set(paires_par_partie.values())
        assert valeurs == {"01", "02"}, (
            f"3 parties sur 2 paires -- exactement 2 paires distinctes attendues, "
            f"reçu {paires_par_partie}"
        )
        assert len(paires_par_partie) == 3 and len(set(paires_par_partie.values())) == 2, (
            "au moins une paire doit avoir rejoué une 2e partie (requeue) : "
            f"{paires_par_partie}"
        )
        print(f"5) requeue vérifiée -- 3 parties réparties sur 2 paires : {paires_par_partie}")

        nuit_md_23 = (run_dir_23 / "nuit.md").read_text(encoding="utf-8")
        assert "Paires simultanées : 2" in nuit_md_23, nuit_md_23
        rapport_23 = (run_dir_23 / "rapport-nuit.md").read_text(encoding="utf-8")
        assert "Paires simultanées : 2" in rapport_23, rapport_23
        print("6) nuit.md et rapport-nuit.md portent tous deux 'Paires simultanées : 2'")

        # --- 3. -Paires invalide -> REFUS avant tout lancement --------------
        p3 = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Paires", "0", "-Save", slug,
             "-RunDir", str(tmp / "run-invalide"), "-DryRun"],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert p3.returncode == 1, f"-Paires 0 : attendu refus 1, reçu {p3.returncode}"
        assert "-Paires" in p3.stderr, p3.stderr
        print("7) -Paires 0 (invalide) : REFUS 1 avant tout lancement")

        print("\nALL NUIT_PAIRES TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
