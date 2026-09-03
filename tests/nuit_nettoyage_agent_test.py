"""Issue #271 : tools/banc/nuit.sh — fin de partie VÉRIFIÉE (nuit N0 02/09,
cas 1 : un agent `banc-joueur` a survécu à `fermer_panes`, et a fait échouer
TOUTE partie suivante par collision de nom sur `agent start`).

Utilise un faux `herdr` (script bash, comme `-LancementCmd`/`-RunDir` pour
les autres tests de ce dossier) qui simule `agent list` rendant un agent
`banc-joueur` survivant tant que le script n'a pas envoyé `/exit` (`agent
send-keys`), puis vide ensuite -- exerce le chemin complet :
`pane close` (fait "rien") -> `herdr agent list` survivant pendant toute la
boucle bornée (30s) -> `/exit` envoyé via `send-keys` -> agent list vide au
prochain contrôle -> la partie se termine normalement (aucun craquement,
sortie 0), la nuit continue.

`-LancementCmd` (interne, #263) simule ici un lancement réussi qui écrit
directement `tour-01.md` (prose déjà valide) -- évite de dépendre du faux
`herdr` pour le protocole "go"/attente de fichier, hors périmètre de ce
test.
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

# Faux herdr : `agent list` rend un survivant "banc-joueur" tant que
# $STATE_DIR/exit-sent n'existe pas (posé par `agent send-keys`, qui écrase
# TOUJOURS ce fichier -- peu importe la cible/les touches passées).
FAKE_HERDR_SH = """#!/bin/bash
STATE_DIR="__STATE_DIR__"
if [ "$1" = "agent" ] && [ "$2" = "list" ]; then
  if [ -f "$STATE_DIR/exit-sent" ]; then
    echo '{"result":{"agents":[]}}'
  else
    echo '{"result":{"agents":[{"name":"banc-joueur","pane_id":"pane-fake-joueur"}]}}'
  fi
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "send-keys" ]; then
  touch "$STATE_DIR/exit-sent"
  exit 0
fi
exit 0
"""


def main() -> int:
    assert NUIT_SH.exists(), f"script absent : {NUIT_SH}"

    tmp = Path(tempfile.mkdtemp(prefix="nuit-nettoyage-agent-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Nettoyage Agent Test", mode="rpg",
            premise="Save 100% synthétique — Issue #271, jamais de matériau réel.",
        )
        assert slug, "création de la save synthétique a échoué"

        run_dir = tmp / "run"
        state_dir = tmp / "state"
        state_dir.mkdir()

        fake_bin = tmp / "fake-bin"
        fake_bin.mkdir()
        fake_herdr = fake_bin / "herdr"
        fake_herdr.write_text(
            FAKE_HERDR_SH.replace("__STATE_DIR__", str(state_dir).replace("\\", "/")),
            encoding="utf-8", newline="\n",
        )
        fake_herdr.chmod(0o755)

        lancement_cmd = (
            f'printf \'# tour 01\\n\\n## Prose du Narrateur (verbatim)\\n\\n'
            f'Prose de test synthetique.\\n\' > "$partie_dir/tour-01.md"; '
            f'echo "Pane MJ: pane-fake-mj"; '
            f'echo "Pane joueur-banc: pane-fake-joueur"; exit 0'
        )

        env = {
            **os.environ,
            "SAVES_DIR": str(lib_root / "saves"),
            "NUIT_CONSERVER_SAVES_DIR": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        }
        env = {k: v for k, v in env.items() if not k.startswith("GIT_")}

        assert not (state_dir / "exit-sent").exists(), "flag exit-sent déjà présent avant le test"

        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Tours", "1", "-Save", slug,
             "-RunDir", str(run_dir), "-LancementCmd", lancement_cmd],
            capture_output=True, text=True, timeout=180, env=env,
        )
        assert p.returncode == 0, (
            f"attendu code de sortie 0 (partie terminée normalement malgré un agent "
            f"survivant récupéré via /exit), reçu {p.returncode}\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )
        print("1) nuit.sh : agent survivant après pane close, récupéré par /exit — sortie 0")

        assert (state_dir / "exit-sent").exists(), (
            "le chemin /exit (herdr agent send-keys) n'a jamais été exercé — "
            "fermer_et_verifier_agents n'a pas envoyé /exit à l'agent survivant"
        )
        print("2) /exit envoyé via send-keys à l'agent survivant (jamais `agent prompt`)")

        assert "AVERTISSEMENT" in p.stderr and "survivant" in p.stderr, (
            f"avertissement de survivance attendu sur stderr : {p.stderr}"
        )

        resume = run_dir / "partie-01" / "resume-run.md"
        assert resume.exists(), f"resume-run.md absent : {resume}"
        contenu = resume.read_text(encoding="utf-8")
        assert "raison_arret: tours_max" in contenu, contenu
        assert "craquements: (aucun)" in contenu, (
            f"la récupération via /exit ne doit produire AUCUN craquement : {contenu}"
        )
        print("3) resume-run.md : partie terminée normalement (tours_max), aucun craquement")

        assert not (run_dir / "partie-01" / "craquement-nettoyage-01.md").exists(), (
            "aucun craquement-nettoyage attendu quand /exit suffit à récupérer"
        )

        print("\nALL NUIT_NETTOYAGE_AGENT TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
