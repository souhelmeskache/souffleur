"""Issue #305, second scénario — le processus reste SORTI même après la
relance (`herdr agent start ... --resume` réussit mais l'agent ne revient
jamais, ex. id de session périmée) : une seule relance tentée, la SECONDE
sortie détectée craque directement (`craquement-processus-sorti-NN.md`)
SANS attendre le `-TimeoutTour` complet — c'est le point de preuve central
de l'Issue (constat #299 mis à jour 05/09 : le banc a attendu 6 min un
agent déjà mort, trois fois).

Vérifie aussi la sonde d'écran (complément de spec du 05/09 17:00,
`nuit.sh::demarrer_sonde_ecran`) : lecture des deux panes toutes les 10s
PENDANT TOUTE LA PARTIE, journalisée dans `partie-NN/ecran-<role>.log`,
citée par le craquement `processus-sorti`.

Faux `herdr` : `agent get` rend TOUJOURS `agent_not_found` (le processus ne
revient jamais, même après `agent start --resume`) ; `pane read` rend un
texte canned portant la commande de reprise ; `agent start`/`agent prompt`
journalisent leurs appels.
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

ID_SESSION_TEST = "0f1e2d3c-test-session-0305-b"


def find_bash():
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


BASH = find_bash()
assert BASH, "bash introuvable (Git for Windows le fournit)"

# `agent get` ne revient JAMAIS "found" (id de session périmée simulée) —
# distinct du scénario de relance réussie (nuit_processus_sorti_test.py).
FAKE_HERDR_SH = """#!/bin/bash
STATE_DIR="__STATE_DIR__"
ID_SESSION="__ID_SESSION__"
if [ "$1" = "agent" ] && [ "$2" = "list" ]; then
  echo '{"result":{"agents":[]}}'
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "get" ]; then
  echo '{"error":{"code":"agent_not_found","message":"agent target '"$3"' not found"}}'
  exit 1
fi
if [ "$1" = "agent" ] && [ "$2" = "start" ]; then
  printf '%s\\n' "$*" >> "$STATE_DIR/start.log"
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "prompt" ]; then
  printf '%s\\t%s\\n' "$3" "$4" >> "$STATE_DIR/prompts.log"
  exit 0
fi
if [ "$1" = "pane" ] && [ "$2" = "read" ]; then
  printf 'Claude Code session ended.\\nResume this session with: claude --resume %s\\n' "$ID_SESSION"
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "read" ]; then
  printf 'ligne transcription canned\\n'
  exit 0
fi
exit 0
"""

LANCEMENT_CMD_FAKE = (
    'echo "Pane MJ: fake-mj-pane"; '
    'echo "Pane joueur-banc: fake-joueur-pane"; '
    'exit 0'
)


def main() -> int:
    assert NUIT_SH.exists(), f"script absent : {NUIT_SH}"

    tmp = Path(tempfile.mkdtemp(prefix="nuit-processus-sorti-craquement-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Processus Sorti Craquement Test", mode="rpg",
            premise="Save 100% synthétique — Issue #305, jamais de matériau réel.",
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

        run_dir = tmp / "run"
        state_dir = tmp / "state"
        state_dir.mkdir()

        fake_bin = tmp / "fake-bin"
        fake_bin.mkdir()
        fake_herdr = fake_bin / "herdr"
        fake_herdr.write_text(
            FAKE_HERDR_SH.replace("__STATE_DIR__", str(state_dir).replace("\\", "/"))
                         .replace("__ID_SESSION__", ID_SESSION_TEST),
            encoding="utf-8", newline="\n",
        )
        fake_herdr.chmod(0o755)

        env = {
            **os.environ,
            "SAVES_DIR": str(lib_root / "saves"),
            "NUIT_CONSERVER_SAVES_DIR": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        }
        env = {k: v for k, v in env.items() if not k.startswith("GIT_")}

        # -TimeoutTour large (10 min) : si le correctif #305 régressait vers
        # une attente du timeout complet, ce test dépasserait largement son
        # propre budget (timeout=180s ci-dessous) plutôt que de rester vert
        # par accident — la preuve centrale de l'Issue est que la SECONDE
        # sortie craque en ~1 poll (~20s), jamais en ~10 min.
        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Tours", "1", "-Save", slug,
             "-RunDir", str(run_dir), "-TimeoutTour", "10",
             "-LancementCmd", LANCEMENT_CMD_FAKE],
            capture_output=True, encoding="utf-8", timeout=170, env=env,
        )
        assert p.returncode == 0, (
            f"une seule partie craquée reste sortie 0 (n'arrête pas la nuit) — "
            f"reçu {p.returncode}\nstdout={p.stdout}\nstderr={p.stderr}"
        )

        assert p.stdout.count("PROCESSUS SORTI") >= 2, (
            f"détection puis re-détection attendues, jamais une attente muette : {p.stdout}"
        )
        assert "PROCESSUS SORTI À NOUVEAU" in p.stdout, p.stdout
        print("1) sortie détectée deux fois, craquement bien avant le -TimeoutTour de 10 min "
              "(preuve #305, § 5 de l'Issue)")

        start_log = (state_dir / "start.log").read_text(encoding="utf-8")
        lignes_start = [l for l in start_log.splitlines() if l]
        assert len(lignes_start) == 1, (
            f"une seule tentative de relance de processus par tour, même si elle échoue "
            f"à ramener l'agent : {lignes_start}"
        )
        print("2) une seule relance de processus tentée par tour, pas de boucle de tentatives")

        partie_dir = run_dir / "partie-01"
        craquement = partie_dir / "craquement-processus-sorti-01.md"
        assert craquement.exists(), f"craquement processus-sorti absent : {craquement}"
        contenu = craquement.read_text(encoding="utf-8")
        assert "agent : mj (banc-mj)" in contenu, contenu
        assert f"id_session : {ID_SESSION_TEST}" in contenu, contenu
        assert "relance tentée : oui" in contenu, contenu
        assert "sonde d'écran" in contenu, contenu
        assert "ecran-mj.log" in contenu, contenu
        print("3) craquement-processus-sorti-01.md : agent, id de session, relance tentée, "
              "et la sonde d'écran citée")

        journal_mj = partie_dir / "ecran-mj.log"
        assert journal_mj.exists(), f"journal de sonde absent : {journal_mj}"
        contenu_journal = journal_mj.read_text(encoding="utf-8")
        assert "Resume this session with: claude --resume" in contenu_journal, contenu_journal
        assert contenu_journal.strip() in contenu, (
            "le contenu du journal de sonde doit apparaître verbatim dans le craquement"
        )
        print("4) partie-01/ecran-mj.log écrit par la sonde, horodaté, cité verbatim "
              "dans le craquement")

        resume = (partie_dir / "resume-run.md").read_text(encoding="utf-8")
        assert "raison_arret: craquement-processus-sorti" in resume, resume
        print("5) resume-run.md : raison_arret craquement-processus-sorti")

        print("\nALL NUIT_PROCESSUS_SORTI_CRAQUEMENT TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
