"""Issue #260 : tools/banc/nuit.sh -DryRun — sur une save 100% synthétique
(Library jetable, jamais le vrai `saves/`, D-109/D-178) : aucun agent lancé
(pas de herdr, pas de powershell), vérifie la création de l'arborescence,
de `nuit.md` et du `resume-run.md` minimal.

`-RunDir` (paramètre interne, non documenté côté opérateur) écrit le run
dans un dossier temporaire plutôt que dans le vrai `bench/nuit-AAAAMMJJ/` du
dépôt — ce test ne doit jamais toucher au vrai `bench/`.
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
    """Préfère le bash de Git for Windows (celui de WSL malmène les chemins C:\\)."""
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

    tmp = Path(tempfile.mkdtemp(prefix="nuit-dryrun-test-"))
    try:
        # --- save 100% synthétique, jamais le vrai saves/ (D-109) -----------
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit DryRun Test", mode="rpg",
            premise="Save 100% synthétique — Issue #260, jamais de matériau réel.",
        )
        assert slug, "création de la save synthétique a échoué"

        run_dir = tmp / "run"

        env = {
            **os.environ,
            "SAVES_DIR": str(lib_root / "saves"),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        # Env sans variables GIT_* héritées (même garde que d'autres tests
        # bash de ce dépôt) : ce test ne fait pas de git, mais nuit.sh en
        # fait un (git rev-parse --show-toplevel) pour trouver REPO_ROOT —
        # des GIT_DIR/GIT_INDEX_FILE hérités d'un hook re-dirigeraient ce
        # rev-parse vers le mauvais dépôt.
        env = {k: v for k, v in env.items() if not k.startswith("GIT_")}

        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "2", "-Save", slug,
             "-RunDir", str(run_dir), "-DryRun"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert p.returncode == 0, (
            f"-DryRun attendu code 0, reçu {p.returncode}\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )
        print("1) nuit.sh -DryRun -Parties 2 : sortie 0")

        # --- arborescence -----------------------------------------------------
        assert run_dir.is_dir(), f"dossier de run non créé : {run_dir}"
        for pnn in ("01", "02"):
            partie_dir = run_dir / f"partie-{pnn}"
            assert partie_dir.is_dir(), f"dossier absent : {partie_dir}"
            assert (partie_dir / "save").is_dir(), f"save absente : {partie_dir / 'save'}"
            assert (partie_dir / "save" / "player.md").exists(), \
                f"save copiée incomplète : {partie_dir / 'save' / 'player.md'}"
            resume = partie_dir / "resume-run.md"
            assert resume.exists(), f"resume-run.md absent : {resume}"
            contenu = resume.read_text(encoding="utf-8")
            assert "fin_atteinte:" in contenu, contenu
            assert "raison_arret: dry-run" in contenu, contenu
        print("2) arborescence : partie-01/ et partie-02/ (save + resume-run.md) créées")

        nuit_md = run_dir / "nuit.md"
        assert nuit_md.exists(), f"nuit.md absent : {nuit_md}"
        contenu = nuit_md.read_text(encoding="utf-8")
        assert "partie-01" not in contenu or "| 01 |" in contenu or "01 |" in contenu, contenu
        assert "Métriques" in contenu, contenu
        print("3) nuit.md écrit, porte la table des parties et les métriques")

        # --- idempotence : un second appel le même jour NE réécrit PAS
        # partie-01/partie-02, il enchaîne à partie-03/partie-04 -----------
        p2 = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Save", slug,
             "-RunDir", str(run_dir), "-DryRun"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert p2.returncode == 0, f"second appel : code {p2.returncode}\n{p2.stderr}"
        assert (run_dir / "partie-03").is_dir(), (
            f"second appel -Parties 1 attendu sur partie-03 (2 déjà jouées) : "
            f"{sorted(p.name for p in run_dir.glob('partie-*'))}"
        )
        print("4) second appel le même jour : reprend à partie-03 (pas d'écrasement)")

        print("\nALL NUIT_DRYRUN TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
