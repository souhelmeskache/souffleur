"""I-291 -- circuit.sh veiller : apres un verdict REFUS, la lane poste un
commentaire posterieur SANS commencer par TERMINE (ex. "Jalon : ... traite")
-- gabarit a moitie suivi, meme famille que #280 (CI rouge)/#288 (conflit).
Si en plus la CI de la PR est verte sur un commit pousse apres le verdict, la
veille tolere l'absence du mot TERMINE : elle considere le travail rendu et
relance le circuit (phase ci puis revue) au lieu d'attendre 90 min un mot qui
ne viendra jamais.

Meme dispositif que circuit_veiller_ci_rouge_test.py : source circuit.sh puis
redefinit `gh`/`herdr` en fonctions bash, `nettoyer_une` et `lancer_revue`
stubbees (aucune des deux n'est le sujet de ce test). `lancer_revue` est
rendue statefull (compteur $LANCER_REVUE_N) pour rejouer un second REFUS
apres la tolerance, sans jamais atteindre la phase merge (qui toucherait le
vrai depot MAIN_REPO) -- le test verifie seulement que la veille reboucle
bien vers la phase ci/revue sans avoir vu de TERMINE, jusqu'a la sortie 4
habituelle de REFUS persistant (meme compteur de cycles que #280/#288).
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

gh_fakes = '''
gh() {
  case "$*" in
    *"issue view $ISSUE"*"--json state"*) echo "OPEN" ;;
    *"pr list"*"--state merged"*) echo "" ;;
    *"pr list"*"--head lane-$ISSUE"*"--state open"*) echo "$PR" ;;
    *"pr view $PR"*"--json statusCheckRollup"*) echo "SUCCESS" ;;
    *"pr view $PR"*"--json mergeStateStatus"*) echo "CLEAN" ;;
    *"pr view $PR"*"--json commits"*) echo "9999-01-01T00:00:00Z" ;;
    *"issue view $ISSUE"*"--json comments"*"TERMIN"*) echo "0" ;;
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
lancer_revue() {
  LANCER_REVUE_N=$((${LANCER_REVUE_N:-0}+1))
  if [ "$LANCER_REVUE_N" -ge 3 ]; then
    _VERDICT_BODY="REVUE : REFUS -- motif de test (3e passage)"
  else
    _VERDICT_BODY="REVUE : REFUS -- motif de test"
  fi
  return 0
}
'''


def run():
    calls = Path(tempfile.mkdtemp(prefix="circuit-tolerance-")) / "calls.log"
    try:
        script = (
            f'source "{CIRCUIT_SH.as_posix()}"\n'
            f'REPO="test/repo"\n'
            f'ISSUE="{ISSUE}"\n'
            f'PR="{PR}"\n'
            f'CALLS_FILE="{calls.as_posix()}"\n'
            'nettoyer_une() { return 0; }\n'
            + gh_fakes
            + '(veiller "$ISSUE"); echo "EXIT=$?"\n'
            + f'echo "=== CALLS ==="; cat "{calls.as_posix()}" 2>/dev/null\n'
        )
        p = subprocess.run(
            [BASH, "-c", script], capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
        return p
    finally:
        shutil.rmtree(calls.parent, ignore_errors=True)


p = run()
assert "EXIT=4" in p.stdout, f"attendu sortie 4 (REFUS persistant) : stdout={p.stdout!r} stderr={p.stderr!r}"
assert p.stdout.count("tolérance (#291)") >= 2, \
    f"attendu la tolerance (commentaire sans TERMINE + CI verte sur commit posterieur) a chaque cycle : {p.stdout!r}"
assert "90 min sans TERMINÉ" not in p.stdout, \
    "la tolerance doit court-circuiter l'attente de 90 min, jamais l'atteindre"
assert p.stdout.count("phase revue") >= 2, \
    "attendu un rebouclage effectif vers la phase revue apres chaque tolerance"
print("REFUS + commentaire 'Jalon' (sans TERMINE) + CI verte sur commit posterieur -> tolerance, rebouclage sans attente de 90 min")

print("\nALL CIRCUIT_VEILLER_TOLERANCE_TERMINE TESTS PASSED")
