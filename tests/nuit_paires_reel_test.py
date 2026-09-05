"""Issue #282 : tools/banc/nuit.sh -Paires 2 -Parties 2 — preuve d'un run
« réel » (deux paires Director/joueur SIMULTANÉES, chacune sa copie de save,
son dossier partie-NN, ses noms d'agent suffixés) sans collision de nom
(#271) ni corruption croisée entre paires.

`-LancementCmd` (interne, #263, même convention que les autres tests de ce
dossier) simule un lancement réussi qui écrit directement `tour-01.md` —
évite de dépendre d'un vrai herdr/powershell/Claude Code. Un faux `herdr`
(script bash) journalise chaque agent qui lui est adressé
(`agent prompt <nom> ...`) dans un fichier par nom : la preuve « sans
collision » est qu'aucun nom d'agent n'est partagé entre les deux paires ET
que les DEUX paires ont bien reçu un « go » (les deux tournent vraiment en
même temps, pas l'une après l'autre sous un nom recyclé).
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

# Faux herdr : `agent list` ne rend jamais de survivant (fermeture toujours
# immédiate) ; `agent prompt <nom> ...` journalise <nom> dans
# $STATE_DIR/prompts-<nom>.log (append) -- preuve que CE nom précis a bien
# reçu un « go », sans dépendre d'un vrai agent/pane.
FAKE_HERDR_SH = """#!/bin/bash
STATE_DIR="__STATE_DIR__"
if [ "$1" = "agent" ] && [ "$2" = "list" ]; then
  echo '{"result":{"agents":[]}}'
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "prompt" ]; then
  echo "go" >> "$STATE_DIR/prompts-$3.log"
  exit 0
fi
exit 0
"""


def main() -> int:
    assert NUIT_SH.exists(), f"script absent : {NUIT_SH}"

    tmp = Path(tempfile.mkdtemp(prefix="nuit-paires-reel-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Paires Reel Test", mode="rpg",
            premise="Save 100% synthétique — Issue #282, jamais de matériau réel.",
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

        # $agent_mj/$agent_joueur/$partie_dir sont des variables LOCALES de
        # jouer_partie (tools/banc/nuit.sh) — visibles dans ce sous-shell
        # `eval` (même mécanisme que tests/nuit_nettoyage_agent_test.py).
        lancement_cmd = (
            'printf \'# tour 01\\n\\n## Prose du Narrateur (verbatim)\\n\\n'
            'Prose de test synthetique.\\n\' > "$partie_dir/tour-01.md"; '
            'echo "Pane MJ: pane-$agent_mj"; '
            'echo "Pane joueur-banc: pane-$agent_joueur"; exit 0'
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

        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "2", "-Paires", "2", "-Tours", "1",
             "-Save", slug, "-RunDir", str(run_dir), "-LancementCmd", lancement_cmd],
            capture_output=True, text=True, timeout=180, env=env,
        )
        assert p.returncode == 0, (
            f"attendu code 0 (2 paires, 2 parties, aucun craquement), reçu {p.returncode}\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )
        print("1) nuit.sh -Paires 2 -Parties 2 -Tours 1 (agents réels simulés) : sortie 0")

        # --- sans collision : les deux paires ont chacune reçu leur "go" ----
        # sous un nom D'AGENT DISTINCT (banc-mj-01/banc-mj-02) -- si les deux
        # paires avaient collisionné sur le même nom (#271), un seul fichier
        # prompts-banc-mj-*.log existerait.
        logs_mj = sorted(state_dir.glob("prompts-banc-mj-*.log"))
        assert len(logs_mj) == 2, (
            f"attendu 2 agents MJ distincts sollicités (banc-mj-01 et banc-mj-02), "
            f"reçu {[f.name for f in logs_mj]}"
        )
        print(f"2) deux agents MJ DISTINCTS sollicités, sans collision de nom : "
              f"{[f.name for f in logs_mj]}")

        # --- étanchéité : chaque partie a sa propre save + son propre tour --
        for pnn in ("01", "02"):
            partie_dir = run_dir / f"partie-{pnn}"
            assert (partie_dir / "save").is_dir(), f"save absente : {partie_dir / 'save'}"
            assert (partie_dir / "tour-01.md").exists(), f"tour-01.md absent : {partie_dir}"
            assert (partie_dir / "prose-01.md").exists(), f"prose-01.md absent : {partie_dir}"
            resume = (partie_dir / "resume-run.md").read_text(encoding="utf-8")
            assert "raison_arret: tours_max" in resume, resume
            assert "craquements: (aucun)" in resume, resume
        print("3) partie-01/partie-02 étanches : save + tour-01/prose-01 propres à chacune, "
              "aucun craquement")

        # --- rapport agrégé : 2 parties, 2 paires --------------------------
        nuit_md = (run_dir / "nuit.md").read_text(encoding="utf-8")
        assert "Paires simultanées : 2" in nuit_md, nuit_md
        assert "| 01 |" in nuit_md and "| 02 |" in nuit_md, nuit_md
        rapport = (run_dir / "rapport-nuit.md").read_text(encoding="utf-8")
        assert "Parties finies / lancées : 0 / 2" in rapport, rapport
        assert "Paires simultanées : 2" in rapport, rapport
        print("4) nuit.md + rapport-nuit.md agrègent les 2 parties des 2 paires")

        print("\nALL NUIT_PAIRES_REEL TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
