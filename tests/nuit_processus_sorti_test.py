"""Issue #305 : `tools/banc/nuit.sh::attendre_fichier` détecte un agent dont
le PROCESSUS claude est SORTI (pane vivant, « Resume this session with:
claude --resume <id> », l'agent disparaît de `herdr agent list`) et le
relance DANS LE MÊME PANE — plutôt que d'attendre le timeout complet sur un
mort (constat #299 mis à jour 05/09 : runs de 15:00/15:09/16:35, 6 min
perdues à chaque fois, cause « muet » supposée alors qu'il s'agissait d'un
processus sorti).

Deux diagnostics distincts : « muet » (#299, encore détecté par `herdr agent
list`, relance mi-timeout via `agent prompt`) et « sorti » (#305, plus détecté
du tout — `herdr agent get` rend `agent_not_found` — relance par `herdr agent
start ... --resume <id>`, à CHAQUE relevé, pas seulement à mi-timeout).

Faux `herdr` (même convention que #271/#299, tests/nuit_nettoyage_agent_test.py
et tests/nuit_relance_timeout_test.py) :
- `agent list` : toujours vide (aucun agent réel).
- `agent get banc-mj` : rend `agent_not_found` (rc 1) tant qu'aucun
  `agent start ... --resume ...` n'a encore été journalisé — puis rc 0
  (agent "revenu"), simulant une relance réussie (item 4 de l'Issue :
  « agent get → not found puis found après start »).
- `pane read` : rend un texte canned portant la ligne de reprise Claude Code
  (« Resume this session with: claude --resume <id-de-test> »).
- `agent start` : journalise ses arguments (agent, pane, kind, et tous les
  arguments après `--`) dans un fichier, rend 0.
- `agent prompt` : journalise chaque appel (go initial + go renvoyé après
  relance) dans un fichier, rend 0.

`tour-01.md` n'est JAMAIS écrit par le fake (aucun agent réel) : le tour 1
(ouverture, MJ seul) craque finalement en `timeout` une fois le process
"revenu" — ce test vérifie la détection + la relance + le renvoi du go, pas
la fin heureuse d'un tour (hors périmètre, aucun agent réel ne peut écrire
tour-01.md ici).
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

ID_SESSION_TEST = "5f3c2e1a-test-session-0305"


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
  if [ -s "$STATE_DIR/start.log" ]; then
    echo '{"result":{"agent":{"name":"'"$3"'"}}}'
    exit 0
  fi
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

    tmp = Path(tempfile.mkdtemp(prefix="nuit-processus-sorti-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Processus Sorti Test", mode="rpg",
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

        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Tours", "1", "-Save", slug,
             "-RunDir", str(run_dir), "-TimeoutTour", "1",
             "-LancementCmd", LANCEMENT_CMD_FAKE],
            capture_output=True, encoding="utf-8", timeout=180, env=env,
        )
        assert p.returncode == 0, (
            f"une seule partie craquée reste sortie 0 (n'arrête pas la nuit) — "
            f"reçu {p.returncode}\nstdout={p.stdout}\nstderr={p.stderr}"
        )

        assert f"PROCESSUS SORTI (mj, tour 01) — reprise --resume {ID_SESSION_TEST} : OK" in p.stdout, p.stdout
        print("1) détection immédiate (pas d'attente du timeout) + relance annoncées sur stdout")

        start_log = (state_dir / "start.log").read_text(encoding="utf-8")
        lignes_start = [l for l in start_log.splitlines() if l]
        assert len(lignes_start) == 1, (
            f"une seule tentative de relance de processus par tour : {lignes_start}"
        )
        ligne = lignes_start[0]
        assert ligne.startswith("agent start banc-mj"), ligne
        assert "--pane fake-mj-pane" in ligne, ligne
        assert f"--resume {ID_SESSION_TEST}" in ligne, ligne
        assert "--model sonnet" in ligne, ligne  # -Director défaut nuit.sh
        assert "--effort medium" in ligne, ligne  # effort du Director (mj)
        assert "--permission-mode acceptEdits" in ligne, ligne
        print("2) `herdr agent start` relancé dans le MÊME pane, --resume + "
              "mêmes modèle/effort/permission-mode que le lancement")

        prompts_log = (state_dir / "prompts.log").read_text(encoding="utf-8")
        lignes_prompt = [l for l in prompts_log.splitlines() if l]
        # go initial (tour 1, ouverture) + go renvoyé après relance réussie
        # (#305) : les deux premiers appels sont identiques (le go du tour
        # en cours, pas un texte de "relance"). Avec -TimeoutTour 1 (60s,
        # POLL_SECS fixe 20s), la relance mi-timeout INDÉPENDANTE (#299)
        # tombe déterministement à mi-parcours (n=1) puisque l'agent revenu
        # n'écrit toujours rien (aucun agent réel derrière le faux herdr) —
        # un 3ᵉ appel, distinct, est donc attendu ; les deux mécanismes
        # coexistent sans se marcher dessus.
        assert len(lignes_prompt) == 3, lignes_prompt
        assert lignes_prompt[0].startswith("banc-mj\t") and "go — tour 01 : ouverture" in lignes_prompt[0], lignes_prompt
        assert lignes_prompt[1].startswith("banc-mj\t") and "go — tour 01 : ouverture" in lignes_prompt[1], lignes_prompt
        assert lignes_prompt[2].startswith("banc-mj\trelance"), lignes_prompt
        print("3) go du tour renvoyé verbatim à banc-mj après la relance réussie "
              "(#305) ; relance mi-timeout (#299) indépendante ensuite, sans conflit")

        partie_dir = run_dir / "partie-01"
        # Le process est "revenu" (agent get rend found dès que start.log
        # existe) : le tour craque ensuite normalement en timeout (aucun
        # agent réel n'écrit tour-01.md), PAS en processus-sorti — la
        # relance a réussi, un craquement-processus-sorti n'aurait aucun
        # sens ici.
        craquement_timeout = partie_dir / "craquement-timeout-01.md"
        craquement_processus = partie_dir / "craquement-processus-sorti-01.md"
        assert craquement_timeout.exists(), f"craquement timeout attendu : {craquement_timeout}"
        assert not craquement_processus.exists(), (
            "aucun craquement-processus-sorti attendu — la relance a réussi"
        )
        print("4) relance réussie : la partie craque en timeout ensuite (aucun agent réel), "
              "jamais en processus-sorti")

        print("\nALL NUIT_PROCESSUS_SORTI TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
