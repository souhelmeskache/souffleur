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
        # #281 : nuit.sh REFUSE désormais une save sans module installé
        # (garde monde vide, à côté de la garde tour 0 exercée ici) —
        # module.json + locations.md non vide, 100% synthétique (D-109).
        (lib.saves.dir(slug_frais) / "module.json").write_text(
            '{"partition": "/dev/null/partition-factice", '
            '"titre": "Module factice de test"}', encoding="utf-8")
        (lib.saves.dir(slug_frais) / "locations.md").write_text(
            (lib.saves.dir(slug_frais) / "locations.md").read_text(encoding="utf-8")
            + "\n## Lieu factice  {#lieu-factice}\nimportance: 3\n\n"
              "Un lieu 100% synthétique.\n",
            encoding="utf-8")
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

        # --- une save au tour 0 mais SANS module (monde vide, #281) est
        # refusée par cette même garde, à côté de celle du tour ------------
        slug_sans_module = lib.saves.create(
            "Nuit Garde Save Depart Test Sans Module", mode="rpg",
            premise="Save fraîche sans module — Issue #281.",
        )
        assert not (lib.saves.dir(slug_sans_module) / "module.json").exists()
        run_dir3 = tmp / "run3"
        p3 = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Save", slug_sans_module,
             "-RunDir", str(run_dir3), "-DryRun"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert p3.returncode == 1, (
            f"attendu code 1 (REFUS, monde vide), reçu {p3.returncode}\n"
            f"stdout={p3.stdout}\nstderr={p3.stderr}"
        )
        assert "REFUS" in p3.stderr and "module" in p3.stderr, p3.stderr
        assert not (run_dir3 / "partie-01").exists(), \
            "aucune partie ne doit être jouée sur REFUS"
        print("3) nuit.sh refuse une save au tour 0 SANS module (monde vide, #281) : REFUS explicite, sortie 1")

        print("\nALL NUIT_GARDE_SAVE_DEPART TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
