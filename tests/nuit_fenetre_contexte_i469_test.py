"""I-469 §F0.4 (Issue #332) — `tools/banc/nuit.sh::journaliser_fenetre` lit,
APRÈS chaque tour joué, le pourcentage de remplissage de fenêtre que Claude
Code affiche sur l'écran du pane MJ (sonde d'écran de #305, `herdr pane
read`), et le journalise dans `events.jsonl` de la save jouée :
`{"type": "fenetre", "turn": N, "role": "mj", "pct": NN}`.

Motif de lecture NON CONFIRMÉ contre un écran réel à la date de cette lane
(aucun run de nuit n'a tourné pendant son développement, #332 « ce qu'on ne
fait pas » — aucune modification du paquet, seulement une mesure) : ce test
fixe la fixture (faux `herdr pane read` répondant un texte synthétique
portant « Context left until auto-compact: 62% ») et vérifie la lecture +
la journalisation mécaniques, jamais la fidélité du motif à l'écran réel de
Claude Code — voir le corps de la PR pour la capture demandée par l'Issue.

Un seul tour (`-Tours 1`), `-LancementCmd` écrit `tour-01.md` immédiatement
(même convention que #295, `tests/nuit_prose_voie_fichier_test.py`) — aucun
agent réel lancé, le faux `herdr` répond seulement à `pane read`."""
from __future__ import annotations

import json
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

# tour-01.md écrit immédiatement par le faux lancement (aucun agent réel,
# aucun herdr agent start/prompt exercé pour l'écriture du tour) — voie
# extraction, section « Prose du Narrateur » inline (#269).
LANCEMENT_CMD_FAKE = (
    'echo "Pane MJ: fake-mj-pane"; '
    'echo "Pane joueur-banc: fake-joueur-pane"; '
    'printf "# tour 01\\n\\n## Visee du Director\\n\\n'
    'la marche vers le Donjon Factice.\\n\\n'
    '## Prose du Narrateur\\n\\n'
    'Le vent mord les joues des voyageurs synthetiques.\\n" > "$partie_dir/tour-01.md"; '
    'exit 0'
)

# Faux `herdr` : seul `pane read` répond utilement (texte synthétique portant
# un pourcentage de fenêtre) -- tout le reste (agent list, agent get, pane
# close...) échoue comme le ferait le vrai herdr contre un pane/agent qui
# n'existe pas (mêmes noms factices que le fake -LancementCmd ci-dessus), ce
# que les gardes de nuit.sh traitent déjà comme "agent absent" sans échouer
# la partie (voir tests/nuit_prose_voie_fichier_test.py, aucun faux herdr).
FAKE_HERDR_SH = """#!/bin/bash
if [ "$1" = "pane" ] && [ "$2" = "read" ]; then
  printf 'Some header\\nContext left until auto-compact: 62%%\\nmore text\\n'
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "list" ]; then
  echo '{"result":{"agents":[]}}'
  exit 0
fi
exit 1
"""


def main() -> int:
    assert NUIT_SH.exists(), f"script absent : {NUIT_SH}"

    tmp = Path(tempfile.mkdtemp(prefix="nuit-fenetre-contexte-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Fenetre Contexte Test", mode="rpg",
            premise="Save 100% synthétique — Issue #332, jamais de matériau réel.",
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

        # I-318 : faux `gh` -- même étanchéité que les tests nuit.sh existants.
        fake_gh = fake_bin / "gh"
        fake_gh.write_text("#!/bin/bash\nexit 1\n", encoding="utf-8", newline="\n")
        fake_gh.chmod(0o755)

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
             "-RunDir", str(run_dir), "-LancementCmd", LANCEMENT_CMD_FAKE],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert p.returncode == 0, (
            f"un tour joué reste sortie 0 -- reçu {p.returncode}\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )
        print("1) nuit.sh -Parties 1 -Tours 1, faux herdr pane read : sortie 0")

        events_path = run_dir / "partie-01" / "save" / "memory" / "events.jsonl"
        assert events_path.exists(), f"events.jsonl attendu : {events_path}"
        lignes = [json.loads(l) for l in
                  events_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        fenetres = [e for e in lignes if e.get("type") == "fenetre"]
        assert len(fenetres) == 1, fenetres
        f0 = fenetres[0]
        assert f0["role"] == "mj", f0
        assert f0["turn"] == 1, f0
        assert f0["pct"] == 62, f0
        print("2) events.jsonl porte {\"type\": \"fenetre\", \"turn\": 1, "
              "\"role\": \"mj\", \"pct\": 62} -- lu sur l'écran synthétique")

        print("\nALL NUIT_FENETRE_CONTEXTE (#332) TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
