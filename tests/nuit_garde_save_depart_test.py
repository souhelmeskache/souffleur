"""Issue #275 (I-465) : `tools/banc/nuit.sh` refuse de jouer une save qui
n'est PAS au tour 0 — une nuit ne doit jamais pouvoir jouer une partie en
cours. 100% synthétique (D-109), Library jetable, jamais le vrai `saves/`.
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

from coderain.memory import Library, MemoryStore  # noqa: E402

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
    tmp = Path(tempfile.mkdtemp(prefix="nuit-garde-save-depart-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Garde Save Depart Test", mode="rpg",
            premise="Save 100% synthétique — Issue #275, jamais de matériau réel.",
        )
        store = MemoryStore(lib.saves.dir(slug))
        assert len(store.turns()) == 0, "précondition : save fraîche au tour 0"

        # --- rend cette save NON fraîche : un tour joué ---------------------
        (lib.saves.dir(slug) / "transcript.md").write_text(
            (lib.saves.dir(slug) / "transcript.md").read_text(encoding="utf-8")
            + "\n<!--@player-->\n> On avance.\n"
              "<!--@narrator-->\nLa porte grince.\n",
            encoding="utf-8")
        assert len(MemoryStore(lib.saves.dir(slug)).turns()) > 0

        env = {
            **os.environ,
            "SAVES_DIR": str(lib_root / "saves"),
            "NUIT_CONSERVER_SAVES_DIR": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        env = {k: v for k, v in env.items() if not k.startswith("GIT_")}

        run_dir = tmp / "run"
        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Save", slug,
             "-RunDir", str(run_dir), "-DryRun"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert p.returncode == 1, (
            f"attendu code 1 (REFUS), reçu {p.returncode}\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )
        assert "REFUS" in p.stderr and "tour" in p.stderr, p.stderr
        assert not (run_dir / "partie-01").exists(), \
            "aucune partie ne doit être jouée sur REFUS"
        print("1) nuit.sh refuse une save non fraîche (tour > 0) : REFUS explicite, sortie 1")

        # --- une save au tour 0 (fraîche) est acceptée par cette même garde -
        slug_frais = lib.saves.create(
            "Nuit Garde Save Depart Test Fraiche", mode="rpg",
            premise="Save fraîche — même Issue.",
        )
        run_dir2 = tmp / "run2"
        p2 = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Save", slug_frais,
             "-RunDir", str(run_dir2), "-DryRun"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert p2.returncode == 0, (
            f"save fraîche attendue acceptée, reçu {p2.returncode}\n"
            f"stdout={p2.stdout}\nstderr={p2.stderr}"
        )
        print("2) nuit.sh accepte une save au tour 0 : sortie 0")

        print("\nALL NUIT_GARDE_SAVE_DEPART TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
