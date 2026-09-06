"""Issue #310 : `tools/banc/nuit.sh` — une partie interrompue par la LIMITE DE
SESSION (sortie 5 d'`attendre_fichier`) recevait jusqu'ici AUCUN
`resume-run.md` — seuls les arrêts STOP/PAUSE (#271) et -FinA (#276)
appelaient `enregistrer_interruption_partie` avant `arreter_toute_la_nuit`
(#306). `nuit.md`/`metriques_nuit.py` retombaient alors sur la ligne
générique « en cours / interrompue » (0 tours, aucun nœud) même quand la
partie avait joué de nombreux tours sans incident (constat #310 : partie au
tour 47, `nuit.md` affichait « 0 » et comptait quand même la partie dans la
médiane de tours-sans-craquement).

Faux `herdr` (même convention que #299, tests/nuit_relance_timeout_test.py) :
`agent list` vide, `agent get` toujours "vivant" (processus jamais sorti,
hors périmètre de ce test), `pane read` rend un texte de limite de session
dès la première lecture -- déclenche `limite_session_detectee` (retour 5)
sans attendre le timeout complet.
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
if [ "$1" = "agent" ] && [ "$2" = "list" ]; then
  echo '{"result":{"agents":[]}}'
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "get" ]; then
  echo '{"result":{"agent_status":"working"}}'
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "prompt" ]; then
  exit 0
fi
if [ "$1" = "pane" ] && [ "$2" = "read" ]; then
  echo "Claude — you have reached your session limit for today"
  exit 0
fi
if [ "$1" = "pane" ] && [ "$2" = "close" ]; then
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

    tmp = Path(tempfile.mkdtemp(prefix="nuit-limite-session-resume-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Limite Session Resume Test", mode="rpg",
            premise="Save 100% synthétique — Issue #310, jamais de matériau réel.",
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

        fake_bin = tmp / "fake-bin"
        fake_bin.mkdir()
        fake_herdr = fake_bin / "herdr"
        fake_herdr.write_text(FAKE_HERDR_SH, encoding="utf-8", newline="\n")
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
        assert p.returncode == 5, (
            f"limite de session en cours de tour : sortie 5 attendue (arrêt de toute la nuit), "
            f"reçu {p.returncode}\nstdout={p.stdout}\nstderr={p.stderr}"
        )
        assert "LIMITE DE SESSION" in p.stdout, p.stdout
        print("1) limite de session détectée en cours de tour, sortie 5")

        partie_dir = run_dir / "partie-01"
        resume = partie_dir / "resume-run.md"
        assert resume.exists(), (
            f"resume-run.md absent après limite de session (#310, sortie 5) : {resume}\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )
        contenu = resume.read_text(encoding="utf-8")
        assert "raison_arret: limite-session" in contenu, contenu
        print("2) resume-run.md écrit avec raison_arret: limite-session")

        nuit_md = (run_dir / "nuit.md").read_text(encoding="utf-8")
        assert "en cours / interrompue" not in nuit_md, (
            f"nuit.md ne doit plus retomber sur la ligne générique une fois "
            f"resume-run.md écrit : {nuit_md}"
        )
        assert "limite-session" in nuit_md, nuit_md
        print("3) nuit.md affiche la raison réelle (limite-session), plus la ligne générique")

        print("\nALL NUIT_LIMITE_SESSION_RESUME TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
