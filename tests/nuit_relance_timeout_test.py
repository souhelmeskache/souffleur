"""Issue #299 : `tools/banc/nuit.sh::attendre_fichier` relance UNE FOIS
l'agent attendu à mi-timeout (3 min sur un `-TimeoutTour` par défaut, ici
raccourci à 1 min pour le test) plutôt que d'attendre en silence jusqu'au
craquement — constat N1 (Director Haiku, partie 03) et
`bench/nuit-20260905/partie-04` (joueur Haiku) : l'agent se tait après un
appel d'outil, sans erreur, jusqu'au craquement `timeout` (6 min perdus).

Le craquement `timeout` doit désormais nommer l'agent (rôle joueur/mj), le
fichier attendu, si une relance a été envoyée, et joindre les 30 dernières
lignes de `herdr agent read <agent>`.

Faux `herdr` (même convention que #271, tests/nuit_nettoyage_agent_test.py) :
`agent list` toujours vide (aucun agent réel à fermer), `agent prompt`
journalise chaque appel (go initial + relance) dans un fichier, `agent read`
rend une transcription canned, `pane read`/`pane close` inertes. `tour-01.md`
n'est JAMAIS écrit (le fake `-LancementCmd` se contente d'imprimer les deux
lignes de pane) — le tour 1 (ouverture, jamais d'attente joueur) attend donc
`tour-01.md` du MJ jusqu'au timeout : exerce le rôle "mj" sans dépendre du
protocole de relance joueur (tour >= 2), plus rapide (un seul timeout).
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

FAKE_HERDR_SH = """#!/bin/bash
STATE_DIR="__STATE_DIR__"
if [ "$1" = "agent" ] && [ "$2" = "list" ]; then
  echo '{"result":{"agents":[]}}'
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "prompt" ]; then
  printf '%s\\t%s\\n' "$3" "$4" >> "$STATE_DIR/prompts.log"
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "read" ]; then
  printf 'ligne 1 transcription canned\\nligne 2 transcription canned\\n'
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

    tmp = Path(tempfile.mkdtemp(prefix="nuit-relance-timeout-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Relance Timeout Test", mode="rpg",
            premise="Save 100% synthétique — Issue #299, jamais de matériau réel.",
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
            FAKE_HERDR_SH.replace("__STATE_DIR__", str(state_dir).replace("\\", "/")),
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
            capture_output=True, text=True, timeout=180, env=env,
        )
        assert p.returncode == 0, (
            f"une seule partie craquée (timeout) reste sortie 0 (n'arrête pas la nuit) — "
            f"reçu {p.returncode}\nstdout={p.stdout}\nstderr={p.stderr}"
        )
        assert "RELANCE (mi-timeout" in p.stdout, p.stdout
        print("1) relance mi-timeout annoncée sur stdout")

        prompts_log = (state_dir / "prompts.log").read_text(encoding="utf-8")
        lignes_prompt = [l for l in prompts_log.splitlines() if l]
        # go initial (tour 1, ouverture) + relance : exactement 2 appels
        # `agent prompt` reçus par banc-mj (agent réel jamais lancé, faux
        # herdr seul destinataire).
        relances = [l for l in lignes_prompt if l.split("\t", 1)[1].startswith("relance")]
        assert len(relances) == 1, f"une seule relance attendue : {lignes_prompt}"
        assert relances[0].startswith("banc-mj\t"), (
            f"la relance doit cibler l'agent MJ (tour 1, ouverture) : {relances[0]}"
        )
        print("2) exactement une relance envoyée, à banc-mj (rôle mj)")

        partie_dir = run_dir / "partie-01"
        craquement = partie_dir / "craquement-timeout-01.md"
        assert craquement.exists(), f"craquement timeout absent : {craquement}"
        contenu = craquement.read_text(encoding="utf-8")
        assert "agent : mj (banc-mj)" in contenu, contenu
        assert "fichier attendu" in contenu and "tour-01.md" in contenu, contenu
        assert "relance envoyée : oui" in contenu, contenu
        assert "transcription canned" in contenu, (
            f"30 dernières lignes de `herdr agent read` attendues dans le craquement : {contenu}"
        )
        print("3) craquement-timeout-01.md : agent=mj, fichier attendu, relance envoyée, "
              "transcription jointe")

        resume = (partie_dir / "resume-run.md").read_text(encoding="utf-8")
        assert "raison_arret: craquement-timeout" in resume, resume
        print("4) resume-run.md : raison_arret craquement-timeout")

        print("\nALL NUIT_RELANCE_TIMEOUT TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
