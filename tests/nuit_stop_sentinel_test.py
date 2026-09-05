"""Issue #271 : tools/banc/nuit.sh — sentinelle d'arrêt `STOP` (Ctrl+C n'est
pas garanti sous Windows, constat nuit N0 02/09 : le trap INT/TERM n'a jamais
tourné depuis un shell Windows). Créer `bench/nuit-AAAAMMJJ/STOP` doit
arrêter la nuit PROPREMENT (nuit.md réécrit, sortie 130) avant la partie
suivante -- testé ici entre deux parties, sur un `-RunDir`/`-DryRun`
synthétique (jamais le vrai `bench/`, D-109/D-178).

Deux appels successifs sur le même `-RunDir` (idempotence, déjà couverte par
tests/nuit_dryrun_test.py) : le premier joue partie-01 normalement : le
second, avec le fichier STOP déjà posé, doit s'arrêter AVANT partie-02 --
reproduit fidèlement "un STOP posé entre deux parties" sans dépendre d'un
minutage de process réel.
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


def main() -> int:
    assert NUIT_SH.exists(), f"script absent : {NUIT_SH}"

    tmp = Path(tempfile.mkdtemp(prefix="nuit-stop-sentinel-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Stop Sentinel Test", mode="rpg",
            premise="Save 100% synthétique — Issue #271, jamais de matériau réel.",
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

        run_dir = tmp / "run"

        env = {
            **os.environ,
            "SAVES_DIR": str(lib_root / "saves"),
            "NUIT_CONSERVER_SAVES_DIR": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        env = {k: v for k, v in env.items() if not k.startswith("GIT_")}

        p1 = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Save", slug,
             "-RunDir", str(run_dir), "-DryRun"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert p1.returncode == 0, (
            f"premier appel (sans STOP) : code de sortie attendu 0, reçu {p1.returncode}\n"
            f"stdout={p1.stdout}\nstderr={p1.stderr}"
        )
        assert (run_dir / "partie-01").is_dir(), "partie-01 non créée par le premier appel"
        print("1) premier appel -Parties 1 -DryRun : partie-01 jouée, sortie 0")

        (run_dir / "STOP").write_text("posé par nuit_stop_sentinel_test.py\n", encoding="utf-8")

        p2 = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "3", "-Save", slug,
             "-RunDir", str(run_dir), "-DryRun"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert p2.returncode == 130, (
            f"second appel (STOP posé) : code de sortie attendu 130, reçu {p2.returncode}\n"
            f"stdout={p2.stdout}\nstderr={p2.stderr}"
        )
        print("2) second appel avec STOP déjà posé : sortie 130 avant toute partie suivante")

        assert not (run_dir / "partie-02").exists(), (
            "partie-02 n'aurait jamais dû être lancée -- STOP était posé avant le second appel"
        )
        assert not (run_dir / "partie-03").exists()
        print("3) aucune partie-02/partie-03 -- l'arrêt a bien eu lieu AVANT la partie suivante")

        nuit_md = run_dir / "nuit.md"
        assert nuit_md.exists(), f"nuit.md absent après arrêt STOP : {nuit_md}"
        contenu = nuit_md.read_text(encoding="utf-8")
        assert "arrêt demandé" in contenu and "STOP" in contenu, (
            f"nuit.md attendu avec une raison d'arrêt mentionnant STOP : {contenu}"
        )
        print("4) nuit.md réécrit avec la raison d'arrêt (fichier STOP/PAUSE)")

        print("\nALL NUIT_STOP_SENTINEL TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
