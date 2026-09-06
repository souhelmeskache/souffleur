"""Issue #330 (D-264) : tools/banc/nuit.sh -DryRun -Reset N[,N...] — preuve de
forme demandée par la lane (§ Preuve à fournir, point 2) : la SÉQUENCE d'un
reset (fermeture de la session MJ en vol, lancement neuf à froid — jamais
--resume —, go du tour suivant par la boucle normale) s'affiche pour chaque
valeur de -Reset, sans lancer aucun agent réel (même discipline que
tests/nuit_dryrun_test.py — save 100% synthétique, D-109).

Couvre aussi les refus d'argument : -Reset en parallèle (-Paires > 1) et
-Reset >= -Tours.
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


def _env_synthetique(lib_root: Path) -> dict:
    env = {
        **os.environ,
        "SAVES_DIR": str(lib_root / "saves"),
        "NUIT_CONSERVER_SAVES_DIR": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    return {k: v for k, v in env.items() if not k.startswith("GIT_")}


def _save_synthetique(tmp: Path, nom: str) -> tuple[Path, str]:
    lib_root = tmp / f"lib-{nom}"
    lib = Library(lib_root)
    slug = lib.saves.create(
        f"Nuit Reset DryRun Test {nom}", mode="rpg",
        premise="Save 100% synthétique — Issue #330, jamais de matériau réel.",
    )
    assert slug, "création de la save synthétique a échoué"
    (lib.saves.dir(slug) / "module.json").write_text(
        '{"partition": "/dev/null/partition-factice", '
        '"titre": "Module factice de test"}', encoding="utf-8")
    (lib.saves.dir(slug) / "locations.md").write_text(
        (lib.saves.dir(slug) / "locations.md").read_text(encoding="utf-8")
        + "\n## Lieu factice  {#lieu-factice}\nimportance: 3\n\n"
          "Un lieu 100% synthétique.\n",
        encoding="utf-8")
    return lib_root, slug


def main() -> int:
    assert NUIT_SH.exists(), f"script absent : {NUIT_SH}"

    tmp = Path(tempfile.mkdtemp(prefix="nuit-reset-dryrun-test-"))
    try:
        # --- 1. -DryRun -Reset 3,7 -Tours 10 : la séquence s'affiche -------
        lib_root, slug = _save_synthetique(tmp, "sequence")
        run_dir = tmp / "run"
        env = _env_synthetique(lib_root)
        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Tours", "10", "-Save", slug,
             "-RunDir", str(run_dir), "-Reset", "3,7", "-DryRun"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert p.returncode == 0, (
            f"-DryRun -Reset attendu code 0, reçu {p.returncode}\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )
        for n in (3, 7):
            assert f"[DryRun] RESET tour {n:02d} : fermeture pane MJ" in p.stdout, p.stdout
            assert "pas --resume" in p.stdout, p.stdout
            assert f"[DryRun] RESET tour {n:02d} : lancement neuf" in p.stdout, p.stdout
            assert "gabarit tools/prompts/banc-mj.md" in p.stdout, p.stdout
            assert f"[DryRun] RESET tour {n:02d} : go du tour {n + 1}" in p.stdout, p.stdout
        print("1) -DryRun -Reset 3,7 : séquence (kill, lancement neuf, go) affichée pour chaque valeur")

        # --- 2. -Reset refusé en parallèle (-Paires > 1) -------------------
        p2 = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Paires", "2", "-Tours", "10",
             "-Save", slug, "-RunDir", str(tmp / "run2"), "-Reset", "3", "-DryRun"],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert p2.returncode != 0, p2.stdout + p2.stderr
        assert "REFUS" in p2.stderr and "-Reset" in p2.stderr and "-Paires 1" in p2.stderr, p2.stderr
        print("2) -Reset + -Paires 2 : REFUS nommé (séquentiel uniquement)")

        # --- 3. -Reset >= -Tours refusé ------------------------------------
        p3 = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Tours", "5",
             "-Save", slug, "-RunDir", str(tmp / "run3"), "-Reset", "5", "-DryRun"],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert p3.returncode != 0, p3.stdout + p3.stderr
        assert "REFUS" in p3.stderr and "-Reset 5 >= -Tours 5" in p3.stderr, p3.stderr
        print("3) -Reset >= -Tours : REFUS nommé (il faut un tour N+1 à jouer)")

        print("\nALL NUIT_RESET_DRYRUN TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
