"""Issue #305, revue REFUS (point bloquant) : `relancer_processus_sorti`
attend l'interactive_ready avant d'envoyer le go de reprise (`herdr agent
prompt ... --wait --until working --timeout 15000`, même idiome que le
premier lancement dans `lancer-banc-fumee.ps1`) et PROPAGE l'échec de cet
envoi dans son code de retour — un `herdr agent start --resume` réussi ne
suffit plus à dire « OK » si le go n'a jamais été reçu (agent jamais revenu
`working` sous 15s, ex. `claude --resume` encore en train de recharger la
session).

Faux `herdr` : `agent get` rend toujours `agent_not_found` (le processus ne
revient jamais, peu importe la cause) ; `agent start` réussit toujours (rc 0,
journalisé) ; `agent prompt` réussit pour le go INITIAL (sans `--wait`, celui
envoyé par `jouer_partie` avant tout appel à `attendre_fichier`) mais ÉCHOUE
(rc 1) pour tout appel portant `--wait` — c'est précisément celui de
`relancer_processus_sorti`, le seul du script à porter ce drapeau.

Ce scénario doit craquer IMMÉDIATEMENT (première détection déjà finale, pas
d'attente d'une seconde sortie) avec un journal disant ÉCHEC, jamais OK —
distinct de tests/nuit_processus_sorti_craquement_test.py (qui échoue lui à
la RELANCE de processus, pas à l'envoi du go après une relance réussie).
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

ID_SESSION_TEST = "aabbccdd-test-session-0305-c"


def find_bash():
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


BASH = find_bash()
assert BASH, "bash introuvable (Git for Windows le fournit)"

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
  for a in "$@"; do
    if [ "$a" = "--wait" ]; then
      # Le go de RELANCE (relancer_processus_sorti) : l'agent n'est jamais
      # revenu "working" sous 15s -- simule un `claude --resume` toujours
      # en train de recharger sa session au moment de l'envoi.
      exit 1
    fi
  done
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

    tmp = Path(tempfile.mkdtemp(prefix="nuit-processus-sorti-go-echec-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Processus Sorti Go Echec Test", mode="rpg",
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

        # -TimeoutTour large (5 min) : si le go de relance n'était pas
        # attendu/vérifié, ce scénario dériverait vers un timeout normal
        # (~2.5 min de mi-timeout) au lieu de craquer dès la première
        # détection -- la preuve que ce test isole bien le chemin
        # "go jamais reçu" est un craquement quasi immédiat.
        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Tours", "1", "-Save", slug,
             "-RunDir", str(run_dir), "-TimeoutTour", "5",
             "-LancementCmd", LANCEMENT_CMD_FAKE],
            capture_output=True, encoding="utf-8", timeout=170, env=env,
        )
        assert p.returncode == 0, (
            f"une seule partie craquée reste sortie 0 (n'arrête pas la nuit) — "
            f"reçu {p.returncode}\nstdout={p.stdout}\nstderr={p.stderr}"
        )

        assert f"reprise --resume {ID_SESSION_TEST} : ÉCHEC" in p.stdout, p.stdout
        assert "OK" not in p.stdout.split("reprise --resume")[1].split("\n")[0], (
            f"le go n'a jamais été reçu -- jamais un OK trompeur : {p.stdout}"
        )
        assert "PROCESSUS SORTI À NOUVEAU" not in p.stdout, (
            f"craquement dès la 1re détection (échec d'ENVOI du go), "
            f"pas besoin d'une 2e sortie : {p.stdout}"
        )
        print("1) `agent start` réussi mais go jamais reçu (--wait échoue) -> ÉCHEC annoncé, "
              "craquement dès la 1re détection")

        start_log = (state_dir / "start.log").read_text(encoding="utf-8")
        assert len([l for l in start_log.splitlines() if l]) == 1, start_log
        print("2) `herdr agent start --resume` bien tenté une fois (la relance de PROCESSUS "
              "a réussi, seul l'envoi du go a échoué)")

        prompts_log = (state_dir / "prompts.log").read_text(encoding="utf-8")
        lignes_prompt = [l for l in prompts_log.splitlines() if l]
        assert len(lignes_prompt) == 2, lignes_prompt  # go initial + tentative de reprise
        print("3) go initial + tentative de reprise (échouée) tous deux journalisés")

        partie_dir = run_dir / "partie-01"
        craquement = partie_dir / "craquement-processus-sorti-01.md"
        assert craquement.exists(), f"craquement processus-sorti absent : {craquement}"
        contenu = craquement.read_text(encoding="utf-8")
        assert "relance tentée : oui" in contenu, contenu
        assert f"id_session : {ID_SESSION_TEST}" in contenu, contenu
        print("4) craquement-processus-sorti-01.md : relance tentée=oui, id de session correcte")

        print("\nALL NUIT_PROCESSUS_SORTI_GO_ECHEC TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
