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

        # --- 2. -FinA déjà passée de plusieurs heures, sur un run FRAIS ->
        # PAS de refus (#276, revue REFUS 03/09 x2) : -FinA se résout à la
        # PROCHAINE occurrence de HH:MM (demain) au lancement d'une nuit
        # fraîche -- c'est exactement le cas d'usage nominal de #276
        # (nuit.cmd lancé en soirée, -FinA 06:00 par défaut déjà "passée"
        # pour aujourd'hui). Écart large et FIXE (2h, jamais une comparaison
        # à l'horloge courante au moment précis de l'exécution) : robuste,
        # jamais une course avec le `date` interne du script.
        heure_passee_loin = (datetime.now() - timedelta(hours=2)).strftime("%H:%M")
        run_dir_passee = tmp / "run-passee"
        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Save", slug,
             "-RunDir", str(run_dir_passee), "-DryRun", "-FinA", heure_passee_loin],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert p.returncode == 0, (
            f"-FinA {heure_passee_loin} (passée de 2h, run frais) NE DOIT PAS être "
            f"refusée -- se résout à demain : reçu {p.returncode}\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )
        assert (run_dir_passee / "partie-01").is_dir(), "la partie doit être jouée normalement"
        rapport_passee = (run_dir_passee / "rapport-nuit.md").read_text(encoding="utf-8")
        assert "budget -Parties atteint" in rapport_passee, (
            f"arrêt attendu sur budget -Parties, pas sur heure de fin : {rapport_passee}"
        )
        print(f"2) -FinA {heure_passee_loin} (passée de 2h, run frais) : PAS de refus -- "
              "résolue à demain, nuit jouée normalement")

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
        # -FinA déjà atteinte au second appel -> exit 130, rapport-nuit.md
        # écrit, PAS de partie-02, JAMAIS un rollover au lendemain (2e revue
        # REFUS 03/09 : « une heure déjà atteinte pendant la nuit arrête la
        # nuit ; au lancement seulement, une heure passée bascule au
        # lendemain » — une continuation n'est jamais « au lancement »).
        # Écart FIXE (5 min, pas une comparaison à l'horloge courante au
        # moment précis de l'exécution) : robuste, jamais une course.
        run_dir_cont = tmp / "run-continuation"
        p1 = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Save", slug,
             "-RunDir", str(run_dir_cont), "-DryRun"],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert p1.returncode == 0, f"premier appel : {p1.returncode}\n{p1.stderr}"
        assert (run_dir_cont / "partie-01").is_dir()

        heure_passee2 = (datetime.now() - timedelta(minutes=5)).strftime("%H:%M")
        p2 = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "3", "-Save", slug,
             "-RunDir", str(run_dir_cont), "-DryRun", "-FinA", heure_passee2],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert p2.returncode == 130, (
            f"continuation, -FinA déjà atteinte (5 min) : attendu 130, reçu {p2.returncode}\n"
            f"stdout={p2.stdout}\nstderr={p2.stderr}"
        )
        assert not (run_dir_cont / "partie-02").exists(), "aucune partie-02 -- arrêt avant"
        contenu = (run_dir_cont / "nuit.md").read_text(encoding="utf-8")
        assert "heure de fin atteinte" in contenu and heure_passee2 in contenu, contenu
        rapport_cont = (run_dir_cont / "rapport-nuit.md").read_text(encoding="utf-8")
        assert "heure de fin atteinte" in rapport_cont, rapport_cont
        print("4) run déjà entamé + -FinA déjà atteinte au relancement : arrêt AVANT "
              "partie-02 (exit 130), jamais un rollover au lendemain")

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
