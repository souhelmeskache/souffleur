"""I-288 -- circuit.sh veiller, phase merge : une PR CONFLICTING (ou
mergeState=DIRTY stable) est un verdict a renvoyer a la lane (rebase sur
main), pas une sortie ECHEC MERGE. Meme famille que #280 (CI rouge) et #281/
#285 (constat initial) : lane vivante -> consigne de rebase + retour en
attente TERMINE (le diff a change, la revue se refait) ; lane morte ->
sortie nommee "CONFLIT avec lane morte : relancer la lane".

Ce test source circuit.sh (jamais execute directement -- pas de dispatch,
donc pas besoin de gh/herdr reels) puis redefinit `gh`/`herdr` en FONCTIONS
bash apres le source, comme circuit_veiller_ci_rouge_test.py. `lancer_revue`
et `nettoyer_une` sont egalement redefinies pour eviter tout appel reel
(PowerShell / herdr workspace / git worktree) -- aucune des deux n'est le
sujet de ce test.

Les appels `herdr agent prompt`/`gh issue comment`/`nettoyer_une` sont
journalises dans un fichier ($CALLS_FILE) plutot que sur stdout : le code
reel redirige le premier vers `/dev/null`. `nettoyer_une` est journalisee
(pas seulement stubbee a `return 0`) pour attraper la fuite de lane de
revue signalee en REFUS de revue adversariale (ce qui cree detruit, I-243 :
la lane revue-$pr, deja creee pour obtenir le verdict APPROUVE avant le
conflit, doit etre detruite avant tout rebouclage/sortie, sinon
`lancer_revue` echouerait au cycle suivant en recreant un worktree/branche
revue-$pr deja existant).

Deux scenarios, chacun un appel bash independant :
  1) PR APPROUVEE mais CONFLICTING + lane vivante, persistant -> consigne de
     rebase envoyee, retour en attente TERMINE puis reboucle (CI, revue),
     jusqu'a sortie 4 "CONFLIT de merge persistant" au 3e cycle (meme
     compteur que REFUS/CI rouge).
  2) PR APPROUVEE mais CONFLICTING + lane morte -> sortie 1 nommee
     "CONFLIT avec lane morte : relancer la lane", aucun renvoi tente.
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
    calls = Path(tempfile.mkdtemp(prefix="circuit-conflit-merge-")) / "calls.log"
    try:
        script = (
            f'source "{CIRCUIT_SH.as_posix()}"\n'
            f'REPO="test/repo"\n'
            f'ISSUE="{ISSUE}"\n'
            f'PR="{PR}"\n'
            f'CALLS_FILE="{calls.as_posix()}"\n'
            'nettoyer_une() { echo "NETTOYER-CALL: $*" >> "$CALLS_FILE"; return 0; }\n'
            'lancer_revue() { _VERDICT_BODY="REVUE : APPROUVE -- rien a redire"; return 0; }\n'
            + gh_herdr_fakes + extra_prelude + scenario_tail
            + f'echo "=== CALLS ==="; cat "{calls.as_posix()}" 2>/dev/null\n'
        )
        p = subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=60)
        return p
    finally:
        shutil.rmtree(calls.parent, ignore_errors=True)


# ---- 1) CONFLICTING + lane vivante -> renvoi, cycle, sortie 4 (persistant) --

gh_conflit_vivante = '''
MSCT_FILE="$CALLS_FILE.msct"
gh() {
  case "$*" in
    *"issue view $ISSUE"*"--json state"*) echo "OPEN" ;;
    *"pr list"*"--state merged"*) echo "" ;;
    *"pr list"*"--head lane-$ISSUE"*"--state open"*) echo "$PR" ;;
    *"pr view $PR"*"--json statusCheckRollup"*) echo "SUCCESS" ;;
    *"pr view $PR"*"--json mergeStateStatus"*)
      # 1er relevé de chaque cycle = phase CI (attendre_ci, veut CLEAN) ;
      # 2e relevé = phase merge (merger_et_nettoyer, veut DIRTY) --
      # compteur fichier car gh() tourne en sous-shell a chaque appel.
      n=$(( $(cat "$MSCT_FILE" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$MSCT_FILE"
      if [ $((n % 2)) -eq 1 ]; then echo "CLEAN"; else echo "DIRTY"; fi
      ;;
    *"pr view $PR"*"--json mergeable"*) echo "CONFLICTING" ;;
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
'''

p = run(gh_conflit_vivante)
assert "EXIT=4" in p.stdout, f"attendu sortie 4 (conflit persistant) : stdout={p.stdout!r} stderr={p.stderr!r}"
assert p.stdout.count("HERDR-CALL: agent prompt lane-999 CONFLIT DE MERGE") == 2, \
    f"attendu 2 renvois (compteur de cycles partage, le 3e cycle sort direct) : {p.stdout!r}"
assert "rebase sur origin/main" in p.stdout
assert "push --force-with-lease" in p.stdout
assert p.stdout.count("GH-CALL: issue comment 999") >= 2, \
    "attendu un commentaire clair sur l'Issue a chaque renvoi"
assert "1 échec du merge merge" not in p.stdout, "jamais le message inutilisable historique"
assert "en conflit avec main" in p.stdout
assert p.stdout.count("NETTOYER-CALL: revue-42") == 3, \
    f"attendu un teardown de la lane de revue a chaque cycle de conflit (ce qui cree detruit, I-243) : {p.stdout!r}"
print("1) CONFLICTING + lane vivante persistante -> renvoi a chaque cycle, sortie 4 au 3e, revue-42 nettoyee a chaque cycle")

# ---- 2) CONFLICTING + lane morte -> sortie 1 nommee, aucun renvoi ----------

gh_conflit_morte = '''
MSCT_FILE="$CALLS_FILE.msct"
gh() {
  case "$*" in
    *"issue view $ISSUE"*"--json state"*) echo "OPEN" ;;
    *"pr list"*"--state merged"*) echo "" ;;
    *"pr list"*"--head lane-$ISSUE"*"--state open"*) echo "$PR" ;;
    *"pr view $PR"*"--json statusCheckRollup"*) echo "SUCCESS" ;;
    *"pr view $PR"*"--json mergeStateStatus"*)
      n=$(( $(cat "$MSCT_FILE" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$MSCT_FILE"
      if [ $((n % 2)) -eq 1 ]; then echo "CLEAN"; else echo "DIRTY"; fi
      ;;
    *"pr view $PR"*"--json mergeable"*) echo "CONFLICTING" ;;
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

p = run(gh_conflit_morte)
assert "EXIT=1" in p.stdout, f"attendu sortie 1 (conflit, lane morte) : stdout={p.stdout!r} stderr={p.stderr!r}"
assert "HERDR-CALL: agent prompt" not in p.stdout, "aucun renvoi attendu, la lane est morte"
assert "GH-CALL: issue comment 999 -R test/repo --body VEILLE 999 : 1 CONFLIT avec lane morte : relancer la lane merge" in p.stdout
assert "NETTOYER-CALL: revue-42" in p.stdout, \
    "attendu un teardown de la lane de revue avant la sortie nommee (ce qui cree detruit, I-243)"
print("2) CONFLICTING + lane morte -> sortie 1 nommee, revue-42 nettoyee, aucun renvoi tente")

print("\nALL CIRCUIT_VEILLER_CONFLIT_MERGE TESTS PASSED")
