"""Issue #330 (D-264, brique 0 / F0.1) : tools/banc/nuit.sh -Reset N — preuve
que le banc TUE la session MJ en vol au tour N et en relance une NEUVE (pas
`--resume`) sur la même save, avant le go du tour N+1 (§ Preuve à fournir,
point 1 : « reset simulé sur fixture — session tuée, session neuve, go
N+1 »).

Faux `herdr` (même convention que tests/nuit_paires_reel_test.py et
tests/nuit_processus_sorti_test.py, #318) :
- `agent list` : toujours vide.
- `agent send-keys` (envoyer_exit_agent, l'"exit" de la session en vol) : rc 0.
- `pane read` : rend toujours le bandeau de reprise Claude Code (« Resume
  this session with: claude --resume <id-avant> ») -- lu par
  `effectuer_reset` comme `session_avant`, jamais une vraie fermeture.
- `agent start ... --model ... --effort ... --permission-mode acceptEdits`
  (SANS `--resume`, #330 — la relance à froid) : journalisé, rc 0.
- `agent get` (session_apres) : rend un `session_id` fixe.
- `agent prompt <nom> <texte>` : si `<texte>` commence par « go », ÉCRIT le
  fichier de tour attendu (action-NN.md pour le joueur, tour-NN.md pour le
  MJ, prose incluse) -- simule un tour complet sans aucun LLM réel ; sinon
  (le gabarit `banc-mj.md` entier envoyé à la session neuve) journalise
  seulement.

`-LancementCmd` (#263) écrit directement `tour-01.md` au lancement -- le
reset a lieu au tour 1 (`-Reset 1`), le tour 2 est donc entièrement produit
par le faux `herdr` ci-dessus.
"""
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

ID_SESSION_AVANT = "session-avant-reset-fixture"
ID_SESSION_APRES = "session-apres-reset-fixture"

FAKE_HERDR_SH = r"""#!/bin/bash
STATE_DIR="__STATE_DIR__"
PARTIE_DIR="__PARTIE_DIR__"
ID_AVANT="__ID_AVANT__"
ID_APRES="__ID_APRES__"

if [ "$1" = "agent" ] && [ "$2" = "list" ]; then
  echo '{"result":{"agents":[]}}'
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "send-keys" ]; then
  printf '%s\n' "$*" >> "$STATE_DIR/send-keys.log"
  exit 0
fi
if [ "$1" = "pane" ] && [ "$2" = "read" ]; then
  printf 'Claude Code session ended.\nResume this session with: claude --resume %s\n' "$ID_AVANT"
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "start" ]; then
  printf '%s\n' "$*" >> "$STATE_DIR/start.log"
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "get" ]; then
  echo '{"result":{"agent":{"name":"'"$3"'","session_id":"'"$ID_APRES"'"}}}'
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "prompt" ]; then
  nom="$3"; texte="$4"
  printf '%s\t%s\n' "$nom" "${texte:0:40}" >> "$STATE_DIR/prompts.log"
  case "$texte" in
    go*)
      # Le numéro de tour est TOUJOURS littéral dans le texte du go réel
      # ("go — tour NN ...", nuit.sh) -- jamais un compteur séparé, qui
      # désynchroniserait joueur (tours 2+ seulement) et MJ (tour 1 = ouverture
      # SEULE, sans joueur) l'un de l'autre.
      brut="$(printf '%s' "$texte" | grep -oE 'tour [0-9]+' | head -1 | grep -oE '[0-9]+')"
      [ -n "$brut" ] || exit 0
      nn=$(printf '%02d' "$((10#$brut))")
      case "$nom" in
        *joueur*)
          printf 'Action synthétique du joueur, tour %s.\n' "$nn" > "$PARTIE_DIR/action-$nn.md"
          ;;
        *mj*)
          printf '# tour %s\n\n## Prose du Narrateur (verbatim)\n\nProse synthétique du tour %s.\n' \
            "$nn" "$nn" > "$PARTIE_DIR/tour-$nn.md"
          ;;
      esac
      ;;
  esac
  exit 0
fi
exit 0
"""

LANCEMENT_CMD_FAKE = (
    'printf \'# tour 01\\n\\n## Prose du Narrateur (verbatim)\\n\\n'
    'Prose de test synthetique.\\n\' > "$partie_dir/tour-01.md"; '
    'echo "Pane MJ: fake-mj-pane"; '
    'echo "Pane joueur-banc: fake-joueur-pane"; '
    'exit 0'
)


def main() -> int:
    assert NUIT_SH.exists(), f"script absent : {NUIT_SH}"

    tmp = Path(tempfile.mkdtemp(prefix="nuit-reset-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Reset Test", mode="rpg",
            premise="Save 100% synthétique — Issue #330, jamais de matériau réel.",
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
        partie_dir = run_dir / "partie-01"
        state_dir = tmp / "state"
        state_dir.mkdir()

        fake_bin = tmp / "fake-bin"
        fake_bin.mkdir()
        fake_herdr = fake_bin / "herdr"
        fake_herdr.write_text(
            FAKE_HERDR_SH
            .replace("__STATE_DIR__", str(state_dir).replace("\\", "/"))
            .replace("__PARTIE_DIR__", str(partie_dir).replace("\\", "/"))
            .replace("__ID_AVANT__", ID_SESSION_AVANT)
            .replace("__ID_APRES__", ID_SESSION_APRES),
            encoding="utf-8", newline="\n",
        )
        fake_herdr.chmod(0o755)

        # I-318 : faux `gh` sur PATH (run réel, hors -DryRun).
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
            [BASH, str(NUIT_SH), "-Parties", "1", "-Tours", "2", "-Save", slug,
             "-RunDir", str(run_dir), "-Reset", "1",
             "-LancementCmd", LANCEMENT_CMD_FAKE],
            capture_output=True, encoding="utf-8", timeout=180, env=env,
        )
        assert p.returncode == 0, (
            f"attendu code 0 (2 tours, un reset au tour 1, aucun craquement), reçu {p.returncode}\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )
        print("1) nuit.sh -Reset 1 -Tours 2 : sortie 0")

        # --- 1. la session en vol a bien reçu /exit (jamais --resume) ------
        send_keys_log = (state_dir / "send-keys.log").read_text(encoding="utf-8")
        assert "banc-mj" in send_keys_log, send_keys_log
        assert "slash e x i t enter" in send_keys_log, send_keys_log
        print("2) /exit envoyé à la session MJ en vol (send-keys, jamais `agent prompt`)")

        # --- 2. relance À FROID, jamais --resume ---------------------------
        start_log = (state_dir / "start.log").read_text(encoding="utf-8")
        lignes_start = [l for l in start_log.splitlines() if l]
        assert len(lignes_start) == 1, lignes_start
        assert lignes_start[0].startswith("agent start banc-mj"), lignes_start[0]
        assert "--pane fake-mj-pane" in lignes_start[0], lignes_start[0]
        assert "--resume" not in lignes_start[0], (
            f"la relance après reset ne doit JAMAIS porter --resume : {lignes_start[0]}"
        )
        assert "--permission-mode acceptEdits" in lignes_start[0], lignes_start[0]
        print("3) session neuve lancée dans le MÊME pane, SANS --resume (#330)")

        # --- 3. le gabarit banc-mj.md entier a été envoyé à la session neuve
        prompts_log = (state_dir / "prompts.log").read_text(encoding="utf-8")
        assert "banc-mj\t# Banc de fumée" in prompts_log, prompts_log
        print("4) le gabarit tools/prompts/banc-mj.md (à froid) a été envoyé à la session neuve")

        # --- 4. events.jsonl porte l'événement reset (#330) ----------------
        events_path = partie_dir / "save" / "memory" / "events.jsonl"
        events = [json.loads(l) for l in events_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        resets = [e for e in events if e.get("type") == "reset"]
        assert len(resets) == 1, events
        assert resets[0]["tour"] == 1, resets[0]
        assert resets[0]["session_avant"] == ID_SESSION_AVANT, resets[0]
        assert resets[0]["session_apres"] == ID_SESSION_APRES, resets[0]
        print(f"5) events.jsonl porte {{'type': 'reset', 'tour': 1, "
              f"'session_avant': ..., 'session_apres': ...}} : {resets[0]}")

        # --- 5. snapshots AVANT reset écrits --------------------------------
        assert (partie_dir / "etat-avant-reset-01.json").exists()
        print("6) etat-avant-reset-01.json (snapshot de state.json au moment du reset) écrit")

        # --- 6. tour 2 joué normalement APRÈS la session neuve -------------
        assert (partie_dir / "action-02.md").exists()
        assert (partie_dir / "tour-02.md").exists()
        assert (partie_dir / "prose-02.md").exists()
        resume = (partie_dir / "resume-run.md").read_text(encoding="utf-8")
        assert "tours_joues: 2" in resume, resume
        assert "craquements: (aucun)" in resume, resume
        print("7) tour 2 (N+1) joué normalement par la session neuve, aucun craquement")

        # --- 7. verdict des 4 vérifications mécaniques écrit (#330) --------
        reset_md = partie_dir / "reset-01.md"
        assert reset_md.exists(), f"reset-01.md absent : {list(partie_dir.glob('*'))}"
        contenu = reset_md.read_text(encoding="utf-8")
        for libelle in ("Position", "cliquet", "réintroduction", "témoin"):
            assert libelle.lower() in contenu.lower(), contenu
        assert "Verdict global :" in contenu, contenu
        print("8) reset-01.md écrit par tools/banc/verifier_reset.py avec les 4 points")

        # --- 8. rapport-nuit.md porte la ligne Resets (#330) ---------------
        rapport = (run_dir / "rapport-nuit.md").read_text(encoding="utf-8")
        assert "Resets (#330, D-264) : 1 joués" in rapport, rapport
        print("9) rapport-nuit.md porte « Resets : 1 joués, N verts (4/4) »")

        print("\nALL NUIT_RESET TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
