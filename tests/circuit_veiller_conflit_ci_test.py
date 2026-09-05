"""I-303 -- circuit.sh veiller, phase ci : une PR aux checks verts mais
mergeState=DIRTY (ou mergeable=CONFLICTING) stable boucle jusqu'au timeout
côté #288 (qui n'a câblé le renvoi que dans la phase merge). Même famille que
#280 (CI rouge) / #288 (conflit en phase merge) : un état que la lane peut
corriger est un verdict, quelle que soit la phase où on le constate.

`attendre_ci` doit sortir dès que les checks sont SUCCESS et
mergeStateStatus=DIRTY sur deux relevés consécutifs (return 2), et `veiller`
doit alors traiter ce conflit exactement comme en phase merge (fonction
factorisée `traiter_conflit`) : consigne de rebase à la lane vivante, retour
en attente TERMINÉ, puis reboucle (CI, puis revue) -- jamais de timeout 90
min pendant que la PR reste bloquée en DIRTY.

Ce test source circuit.sh (jamais exécuté directement -- pas de dispatch,
donc pas besoin de gh/herdr réels) puis redéfinit `gh`/`herdr` en FONCTIONS
bash après le source, comme circuit_veiller_conflit_merge_test.py.
`lancer_revue` et `nettoyer_une` sont également redéfinies pour éviter tout
appel réel (PowerShell / herdr workspace / git worktree).

Le scénario 1 traverse le chemin de succès de `merger_et_nettoyer` (merge au
2e cycle), qui se termine par `gh pr merge` puis `git -C "$MAIN_REPO" pull
--ff-only` -- un vrai appel réseau sur le checkout principal si on ne le
feinte pas (100% hors-ligne, CLAUDE.md). `git` y est donc également
redéfinie en fonction journalisée, comme `gh`/`herdr`.

Deux scénarios, chacun un appel bash indépendant :
  1) phase ci : checks SUCCESS + mergeState=DIRTY stable + lane vivante ->
     consigne de rebase envoyée, pas de timeout, retour en attente TERMINÉ
     puis reboucle (revue APPROUVE au 2e cycle -> merge et sortie 0).
  2) phase ci : checks SUCCESS + mergeState=DIRTY stable + lane morte ->
     sortie 1 nommée "CONFLIT avec lane morte : relancer la lane", aucun
     renvoi tenté.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CIRCUIT_SH = REPO_ROOT / "tools" / "banc" / "circuit.sh"


def find_bash():
    """Prefere le bash de Git for Windows (celui de WSL malmene les chemins C:\\)."""
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


BASH = find_bash()
assert BASH, "bash introuvable (Git for Windows le fournit)"

ISSUE = "999"
PR = "42"


def run(gh_herdr_fakes, extra_prelude="", scenario_tail='(veiller "$ISSUE"); echo "EXIT=$?"\n'):
    calls = Path(tempfile.mkdtemp(prefix="circuit-conflit-ci-")) / "calls.log"
    try:
        script = (
            f'source "{CIRCUIT_SH.as_posix()}"\n'
            f'REPO="test/repo"\n'
            f'ISSUE="{ISSUE}"\n'
            f'PR="{PR}"\n'
            f'CALLS_FILE="{calls.as_posix()}"\n'
            'nettoyer_une() { echo "NETTOYER-CALL: $*" >> "$CALLS_FILE"; return 0; }\n'
            + gh_herdr_fakes + extra_prelude + scenario_tail
            + f'echo "=== CALLS ==="; cat "{calls.as_posix()}" 2>/dev/null\n'
        )
        p = subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=60)
        return p
    finally:
        shutil.rmtree(calls.parent, ignore_errors=True)


# ---- 1) DIRTY stable en phase ci + lane vivante -> renvoi, puis merge -------

gh_dirty_ci_vivante = '''
MSCT_FILE="$CALLS_FILE.msct"
gh() {
  case "$*" in
    *"issue view $ISSUE"*"--json state"*) echo "OPEN" ;;
    *"pr list"*"--state merged"*) echo "" ;;
    *"pr list"*"--head lane-$ISSUE"*"--state open"*) echo "$PR" ;;
    *"pr view $PR"*"--json statusCheckRollup"*) echo "SUCCESS" ;;
    *"pr view $PR"*"--json mergeStateStatus"*)
      # Les 2 premiers relevés (1er cycle, phase ci) : DIRTY stable ->
      # conflit constaté dès la phase ci. Tous les relevés suivants (2e
      # cycle, la PR est passée propre entre-temps) : CLEAN -> merge normal.
      n=$(( $(cat "$MSCT_FILE" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$MSCT_FILE"
      if [ "$n" -le 2 ]; then echo "DIRTY"; else echo "CLEAN"; fi
      ;;
    *"issue view $ISSUE"*"--json comments"*) echo "1" ;;
    *"issue comment"*) echo "GH-CALL: $*" >> "$CALLS_FILE" ;;
    *) echo "" ;;
  esac
  return 0
}
herdr() {
  case "$*" in
    *"agent list"*) echo '{"result":{"agents":[{"name":"lane-'"$ISSUE"'","agent_status":"idle"}]}}' ;;
    *"agent prompt"*) echo "HERDR-CALL: $*" >> "$CALLS_FILE" ;;
    *) : ;;
  esac
  return 0
}
lancer_revue() { _VERDICT_BODY="REVUE : APPROUVE -- rien a redire"; return 0; }
# merger_et_nettoyer se termine par `git -C "$MAIN_REPO" pull --ff-only` --
# feinte, sinon vrai appel réseau sur le checkout principal (100%
# hors-ligne, CLAUDE.md).
git() { echo "GIT-CALL: $*" >> "$CALLS_FILE"; return 0; }
'''

p = run(gh_dirty_ci_vivante)
assert "EXIT=0" in p.stdout, f"attendu sortie 0 (merge au 2e cycle) : stdout={p.stdout!r} stderr={p.stderr!r}"
assert "checks verts + mergeState=DIRTY stable" in p.stdout
assert "phase attente_termine" in p.stdout, "timeout 90 min évité (#303) : on repasse par attente_termine, pas par un sleep en boucle"
assert p.stdout.count("HERDR-CALL: agent prompt lane-999 CONFLIT DE MERGE") == 1, \
    f"attendu un renvoi de consigne de rebase depuis la phase ci : {p.stdout!r}"
assert "rebase sur origin/main" in p.stdout
assert "push --force-with-lease" in p.stdout
assert "en conflit avec main" in p.stdout
assert "GIT-CALL:" in p.stdout and "pull --ff-only" in p.stdout, \
    f"attendu le pull --ff-only du checkout principal, feint (jamais réel) : {p.stdout!r}"
print("1) DIRTY stable en phase ci + lane vivante -> consigne de rebase, pas de timeout, merge au 2e cycle")

# ---- 2) DIRTY stable en phase ci + lane morte -> sortie 1 nommée -----------

gh_dirty_ci_morte = '''
gh() {
  case "$*" in
    *"issue view $ISSUE"*"--json state"*) echo "OPEN" ;;
    *"pr list"*"--state merged"*) echo "" ;;
    *"pr list"*"--head lane-$ISSUE"*"--state open"*) echo "$PR" ;;
    *"pr view $PR"*"--json statusCheckRollup"*) echo "SUCCESS" ;;
    *"pr view $PR"*"--json mergeStateStatus"*) echo "DIRTY" ;;
    *"issue view $ISSUE"*"--json comments"*) echo "1" ;;
    *"issue comment"*) echo "GH-CALL: $*" >> "$CALLS_FILE" ;;
    *) echo "" ;;
  esac
  return 0
}
herdr() {
  case "$*" in
    *"agent list"*) echo '{"result":{"agents":[]}}' ;;
    *"agent prompt"*) echo "HERDR-CALL: $*" >> "$CALLS_FILE" ;;
    *) : ;;
  esac
  return 0
}
'''

p = run(gh_dirty_ci_morte)
assert "EXIT=1" in p.stdout, f"attendu sortie 1 (conflit ci, lane morte) : stdout={p.stdout!r} stderr={p.stderr!r}"
assert "HERDR-CALL: agent prompt" not in p.stdout, "aucun renvoi attendu, la lane est morte"
assert "GH-CALL: issue comment 999 -R test/repo --body VEILLE 999 : 1 CONFLIT avec lane morte : relancer la lane ci" in p.stdout
print("2) DIRTY stable en phase ci + lane morte -> sortie 1 nommée, aucun renvoi tenté")

print("\nALL CIRCUIT_VEILLER_CONFLIT_CI TESTS PASSED")
