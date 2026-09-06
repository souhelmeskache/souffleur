"""Issue #309 : `nuit.sh` sépare le dossier de la vraie nuit
(`bench/nuit-AAAAMMJJ/`, uniquement quand `-FinA` est posée) du dossier de
fumée/journée (`bench/fumee-AAAAMMJJ/`, run borné par `-Parties` seul, sans
`-FinA`) — constat 05/09 : six runs de fumée joués en journée dans
`bench/nuit-20260905/` avaient fait `nuit.cmd` du soir croire à une
continuation de nuit interrompue, arrêtant la nuit au premier contrôle sans
jouer un tour (règle « heure déjà atteinte en continuation », #276).

Ce test vérifie la résolution du DÉFAUT de `$RUN_DIR` (sans `-RunDir`), donc
ne peut pas passer par le raccourci `-RunDir` des autres tests `nuit_*`
(D-109/D-178 : jamais toucher au vrai `bench/` du dépôt courant) — `REPO_ROOT`
se déduit dans `nuit.sh` de l'emplacement du SCRIPT lui-même (pas de
`git rev-parse`), donc une copie de fichiers jetable (jamais `git clone` : un
clone ne verrait que le dernier commit, pas les modifications en cours de
cette branche) fournit un `$REPO_ROOT` isolé dont `bench/` peut être écrit et
jeté sans risque de collision avec une vraie nuit en cours sur ce poste.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from coderain.memory import Library  # noqa: E402


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
    tmp = Path(tempfile.mkdtemp(prefix="nuit-dossier-jour-nuit-test-"))
    try:
        # --- copie jetable du dépôt (arbre de travail réel, pas `git clone` --
        # un clone ne verrait que HEAD, jamais les modifications en cours de
        # cette branche) : $REPO_ROOT isolé, bench/ jetable ------------------
        clone_dir = tmp / "repo"
        shutil.copytree(
            REPO_ROOT, clone_dir,
            ignore=shutil.ignore_patterns(".git", "bench", "__pycache__", "*.pyc"),
        )
        nuit_sh = clone_dir / "tools" / "banc" / "nuit.sh"
        assert nuit_sh.exists(), f"script absent dans le clone : {nuit_sh}"

        # --- save 100% synthétique, jamais le vrai saves/ (D-109) -----------
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Dossier Test", mode="rpg",
            premise="Save 100% synthétique — Issue #309, jamais de matériau réel.",
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

        env = {
            **os.environ,
            "SAVES_DIR": str(lib_root / "saves"),
            "NUIT_CONSERVER_SAVES_DIR": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        env = {k: v for k, v in env.items() if not k.startswith("GIT_")}

        date_jour = datetime.now().strftime("%Y%m%d")
        bench_dir = clone_dir / "bench"

        # --- 1. sans -FinA (run borné -Parties seul, cas des runs de fumée
        # manuels du constat #309) -> bench/fumee-AAAAMMJJ/, JAMAIS
        # bench/nuit-AAAAMMJJ/ -------------------------------------------------
        p = subprocess.run(
            [BASH, str(nuit_sh), "-Parties", "1", "-Save", slug, "-DryRun"],
            capture_output=True, text=True, timeout=120, env=env, cwd=str(clone_dir),
        )
        assert p.returncode == 0, f"sans -FinA : attendu 0, reçu {p.returncode}\n{p.stderr}"
        assert (bench_dir / f"fumee-{date_jour}" / "partie-01").is_dir(), (
            f"attendu bench/fumee-{date_jour}/partie-01 : "
            f"{sorted(x.name for x in bench_dir.glob('*'))}"
        )
        assert not (bench_dir / f"nuit-{date_jour}").exists(), (
            "aucun run de fumée (sans -FinA) ne doit toucher bench/nuit-AAAAMMJJ/"
        )
        print("1) sans -FinA (run de fumée/journée) : bench/fumee-AAAAMMJJ/, "
              "jamais bench/nuit-AAAAMMJJ/")

        # --- 2. avec -FinA (vraie nuit) -> bench/nuit-AAAAMMJJ/ ---------------
        heure_future = "23:59"
        p = subprocess.run(
            [BASH, str(nuit_sh), "-Parties", "1", "-Save", slug, "-DryRun",
             "-FinA", heure_future],
            capture_output=True, text=True, timeout=120, env=env, cwd=str(clone_dir),
        )
        assert p.returncode == 0, f"avec -FinA : attendu 0, reçu {p.returncode}\n{p.stderr}"
        assert (bench_dir / f"nuit-{date_jour}" / "partie-01").is_dir(), (
            f"attendu bench/nuit-{date_jour}/partie-01 : "
            f"{sorted(x.name for x in bench_dir.glob('*'))}"
        )
        print("2) avec -FinA (vraie nuit) : bench/nuit-AAAAMMJJ/")

        # --- 3. les deux dossiers restent étanches -- le run de fumée du (1)
        # n'a pas fait démarrer une "continuation" dans bench/nuit-AAAAMMJJ/ --
        assert (bench_dir / f"nuit-{date_jour}" / "partie-02").exists() is False, (
            "le run de fumée (1) ne doit jamais avoir avancé le compteur de "
            "partie du dossier de nuit (2) -- dossiers étanches"
        )
        print("3) dossier de fumée et dossier de nuit restent étanches "
              "(compteurs de partie indépendants)")

        print("\nALL NUIT_DOSSIER_JOUR_NUIT TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
