"""Issue #276 : tools/banc/nuit.sh -- option `-FinA HH:MM` (arrêt à heure
fixe) et `rapport-nuit.md` (écrit à la fin de la nuit quelle que soit la
raison d'arrêt). Sur `-RunDir`/save synthétique uniquement (jamais le vrai
`bench/`, D-109/D-178) -- même discipline que
tests/nuit_stop_sentinel_test.py et tests/nuit_dryrun_test.py.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
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


def main() -> int:
    assert NUIT_SH.exists(), f"script absent : {NUIT_SH}"

    tmp = Path(tempfile.mkdtemp(prefix="nuit-fin-a-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit FinA Test", mode="rpg",
            premise="Save 100% synthétique — Issue #276, jamais de matériau réel.",
        )
        assert slug, "création de la save synthétique a échoué"
        env = base_env(lib_root)

        # --- 1. format invalide -> REFUS avant tout lancement -------------
        run_dir_fmt = tmp / "run-fmt"
        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Save", slug,
             "-RunDir", str(run_dir_fmt), "-DryRun", "-FinA", "6h00"],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert p.returncode == 1, f"format -FinA invalide : attendu 1, reçu {p.returncode}\n{p.stderr}"
        assert not run_dir_fmt.exists(), "aucun dossier ne doit être créé sur un -FinA invalide"
        print("1) -FinA '6h00' (format invalide) : refus 1, aucun dossier créé")

        # --- 2. heure déjà passée AU LANCEMENT (run frais) -> REFUS 1 ------
        heure_passee = (datetime.now() - timedelta(minutes=5)).strftime("%H:%M")
        run_dir_passee = tmp / "run-passee"
        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Save", slug,
             "-RunDir", str(run_dir_passee), "-DryRun", "-FinA", heure_passee],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert p.returncode == 1, (
            f"-FinA {heure_passee} déjà passée : attendu 1, reçu {p.returncode}\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )
        assert not (run_dir_passee / "partie-01").exists(), "aucune partie ne doit être jouée"
        print(f"2) -FinA {heure_passee} déjà passée (run frais) : refus 1, pas de nuit vide")

        # --- 3. heure future : -DryRun tourne normalement, rapport-nuit.md
        # écrit sur l'arrêt normal (budget -Parties atteint) -------------------
        heure_future = (datetime.now() + timedelta(hours=2)).strftime("%H:%M")
        run_dir_ok = tmp / "run-ok"
        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Save", slug,
             "-RunDir", str(run_dir_ok), "-DryRun", "-FinA", heure_future],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert p.returncode == 0, f"attendu 0, reçu {p.returncode}\n{p.stderr}"
        rapport = run_dir_ok / "rapport-nuit.md"
        assert rapport.exists(), f"rapport-nuit.md absent : {rapport}"
        contenu = rapport.read_text(encoding="utf-8")
        assert "Raison d'arrêt" in contenu, contenu
        assert "budget -Parties atteint" in contenu, contenu
        assert "Limite de session touchée : non" in contenu, contenu
        nuit_md = (run_dir_ok / "nuit.md").read_text(encoding="utf-8")
        assert "rapport-nuit.md" in nuit_md, nuit_md
        assert "dépôt Issue #201 : non posté (-DryRun)" in nuit_md, nuit_md
        print("3) -FinA future, arrêt normal : rapport-nuit.md écrit, statut dépôt cité dans nuit.md")

        # --- 4. arrêt ENTRE DEUX PARTIES : run déjà entamé (continuation),
        # -FinA déjà passée au second appel -> exit 130, rapport-nuit.md écrit,
        # PAS de partie-02 ---------------------------------------------------
        run_dir_cont = tmp / "run-continuation"
        p1 = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Save", slug,
             "-RunDir", str(run_dir_cont), "-DryRun"],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert p1.returncode == 0, f"premier appel : {p1.returncode}\n{p1.stderr}"
        assert (run_dir_cont / "partie-01").is_dir()

        heure_passee2 = (datetime.now() - timedelta(minutes=1)).strftime("%H:%M")
        p2 = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "3", "-Save", slug,
             "-RunDir", str(run_dir_cont), "-DryRun", "-FinA", heure_passee2],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert p2.returncode == 130, (
            f"continuation, -FinA déjà passée : attendu 130, reçu {p2.returncode}\n"
            f"stdout={p2.stdout}\nstderr={p2.stderr}"
        )
        assert not (run_dir_cont / "partie-02").exists(), "aucune partie-02 -- arrêt avant"
        contenu = (run_dir_cont / "nuit.md").read_text(encoding="utf-8")
        assert "heure de fin atteinte" in contenu and heure_passee2 in contenu, contenu
        rapport_cont = (run_dir_cont / "rapport-nuit.md").read_text(encoding="utf-8")
        assert "heure de fin atteinte" in rapport_cont, rapport_cont
        print("4) run déjà entamé + -FinA déjà passée au relancement : arrêt AVANT partie-02 "
              "(exit 130), pas un refus -- rapport-nuit.md et nuit.md le citent")

        # --- 5. arrêt AU TOUR SUIVANT (partie en cours) : -LancementCmd
        # "true" (lancement réussi, aucun agent réel), -FinA atteinte pendant
        # l'attente du premier tour -> exit 130, même chemin que STOP -------
        run_dir_tour = tmp / "run-tour"
        heure_proche = (datetime.now() + timedelta(minutes=1)).strftime("%H:%M")
        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Save", slug,
             "-RunDir", str(run_dir_tour), "-TimeoutTour", "2",
             "-FinA", heure_proche, "-LancementCmd", "true"],
            capture_output=True, text=True, timeout=150, env=env,
        )
        assert p.returncode == 130, (
            f"arrêt au tour suivant (heure de fin) : attendu 130, reçu {p.returncode}\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )
        assert "HEURE DE FIN ATTEINTE" in p.stdout, p.stdout
        nuit_md_tour = (run_dir_tour / "nuit.md").read_text(encoding="utf-8")
        assert "heure de fin atteinte" in nuit_md_tour, nuit_md_tour
        assert (run_dir_tour / "rapport-nuit.md").exists()
        print("5) partie en cours (attente d'un tour) : -FinA atteinte -> arrêt propre "
              "au tour suivant (exit 130), rapport-nuit.md écrit")

        print("\nALL NUIT_FIN_A TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
