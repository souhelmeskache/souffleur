"""I-280 -- circuit.sh veiller : CI rouge n'est une sortie que si la lane est
morte ; sinon c'est un verdict de plus a renvoyer, meme compteur de cycles
que les REFUS de revue. Cas symetrique cote REFUS : lane morte -> sortie
immediate, jamais une attente de 90 min.

Ce test source circuit.sh (jamais execute directement -- pas de dispatch,
donc pas besoin de gh/herdr reels) puis redefinit `gh`/`herdr` en FONCTIONS
bash apres le source : dans le meme process shell, une fonction masque le
binaire du meme nom pour tout le reste du script (y compris les appels faits
depuis l'interieur de `veiller`). `lancer_revue` et `nettoyer_une` sont
egalement redefinies -- la premiere pour eviter un vrai lancement
PowerShell (`lancer-lane.ps1 -Revue`), la seconde pour eviter tout appel
`herdr workspace`/`git worktree` reel -- ni l'une ni l'autre n'est le sujet
de ce test (voir circuit_veiller_parseurs_test.py pour les parseurs purs).

Les appels `herdr agent prompt`/`gh issue comment` sont journalises dans un
fichier ($CALLS_FILE) plutot que sur stdout : le code reel les redirige vers
`/dev/null` (`herdr agent prompt ... >/dev/null 2>&1`), donc les lire sur
stdout du process les manquerait silencieusement.

Trois scenarios, chacun un appel bash independant :
  1) CI rouge + lane vivante, persistante -> renvoi (message "CI ROUGE ...
     gh run view <id> --log-failed"), cycle avec attente_termine, jusqu'a
     sortie 4 "CI rouge persistante" au 3e cycle (meme compteur que REFUS).
  2) CI rouge + lane morte -> sortie 1 immediate, aucun renvoi tente.
  3) REFUS de revue + lane morte -> sortie 1 immediate (pas d'attente de
     TERMINE), avec le message qui dit de relancer un agent neuf.
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
    calls = Path(tempfile.mkdtemp(prefix="circuit-ci-rouge-")) / "calls.log"
    try:
        script = (
            f'source "{CIRCUIT_SH.as_posix()}"\n'
            f'REPO="test/repo"\n'
            f'ISSUE="{ISSUE}"\n'
            f'PR="{PR}"\n'
            f'CALLS_FILE="{calls.as_posix()}"\n'
            'nettoyer_une() { return 0; }\n'
            + gh_herdr_fakes + extra_prelude + scenario_tail
            + f'echo "=== CALLS ==="; cat "{calls.as_posix()}" 2>/dev/null\n'
        )
        p = subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=60)
        return p
    finally:
        shutil.rmtree(calls.parent, ignore_errors=True)


# ---- 1) CI rouge + lane vivante -> renvoi, cycle, sortie 4 (persistant) ------

gh_ci_vivante = '''
gh() {
  case "$*" in
    *"issue view $ISSUE"*"--json state"*) echo "OPEN" ;;
    *"pr list"*"--state merged"*) echo "" ;;
    *"pr list"*"--head lane-$ISSUE"*"--state open"*) echo "$PR" ;;
    *"pr view $PR"*"--json statusCheckRollup"*) echo "FAILURE" ;;
    *"pr view $PR"*"--json mergeStateStatus"*) echo "BLOCKED" ;;
    *"pr view $PR"*"--json headRefName"*) echo "lane-$ISSUE" ;;
    *"run list"*) echo "777" ;;
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

p = run(gh_ci_vivante)
assert "EXIT=4" in p.stdout, f"attendu sortie 4 (CI rouge persistante) : stdout={p.stdout!r} stderr={p.stderr!r}"
assert p.stdout.count("HERDR-CALL: agent prompt lane-999 CI ROUGE sur la PR #42") == 2, \
    f"attendu 2 renvois (compteur de cycles partage, le 3e cycle sort direct) : {p.stdout!r}"
assert "gh run view 777 --log-failed" in p.stdout
print("1) CI rouge + lane vivante persistante -> renvoi a chaque cycle, sortie 4 au 3e")

# ---- 2) CI rouge + lane morte -> sortie 1 immediate, aucun renvoi -----------

gh_ci_morte = '''
gh() {
  case "$*" in
    *"issue view $ISSUE"*"--json state"*) echo "OPEN" ;;
    *"pr list"*"--state merged"*) echo "" ;;
    *"pr list"*"--head lane-$ISSUE"*"--state open"*) echo "$PR" ;;
    *"pr view $PR"*"--json statusCheckRollup"*) echo "FAILURE" ;;
    *"pr view $PR"*"--json mergeStateStatus"*) echo "BLOCKED" ;;
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

p = run(gh_ci_morte)
assert "EXIT=1" in p.stdout, f"attendu sortie 1 (CI rouge, lane absente) : stdout={p.stdout!r} stderr={p.stderr!r}"
assert "HERDR-CALL: agent prompt" not in p.stdout, "aucun renvoi attendu, la lane est morte"
assert "GH-CALL: issue comment 999 -R test/repo --body VEILLE 999 : 1 CI rouge, lane absente ci" in p.stdout
print("2) CI rouge + lane morte -> sortie 1 immediate, aucun renvoi tente")

# ---- 3) REFUS de revue + lane morte -> sortie 1 immediate -------------------

gh_refus_morte = '''
gh() {
  case "$*" in
    *"issue view $ISSUE"*"--json state"*) echo "OPEN" ;;
    *"pr list"*"--state merged"*) echo "" ;;
    *"pr list"*"--head lane-$ISSUE"*"--state open"*) echo "$PR" ;;
    *"pr view $PR"*"--json statusCheckRollup"*) echo "SUCCESS" ;;
    *"pr view $PR"*"--json mergeStateStatus"*) echo "CLEAN" ;;
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
lancer_revue() { _VERDICT_BODY="REVUE : REFUS -- motif de test"; return 0; }
'''

p = run(gh_refus_morte)
assert "EXIT=1" in p.stdout, f"attendu sortie 1 (REFUS, lane absente) : stdout={p.stdout!r} stderr={p.stderr!r}"
assert "HERDR-CALL: agent prompt" not in p.stdout, "aucun renvoi de verdict attendu, la lane est morte"
assert "relancer un agent neuf" in p.stdout
assert "phase attente_termine" not in p.stdout, "pas d'attente de TERMINE quand la lane est morte"
print("3) REFUS de revue + lane morte -> sortie 1 immediate, pas d'attente de TERMINE")

print("\nALL CIRCUIT_VEILLER_CI_ROUGE TESTS PASSED")
