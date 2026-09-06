"""#323 -- circuit.sh veiller n'est pas idempotent et `etat` ne liste pas les
veilles : deux veilles sur la meme issue le 06/09 (#313/#317/#319, relais cru
sur parole).

Trois volets, chacun un appel bash independant (source, jamais execution
directe -- le garde `BASH_SOURCE == $0` n'entre dans le dispatch qu'en mode
execute) :

  (a) `verrou_acquerir`/`veiller` sont idempotents : un verrou vivant deja
      pose -> message + sortie 0 immediate, aucun second travail ; un verrou
      orphelin (PID mort) est repris.
  (b) `etat` liste les veilles en cours (issue/pid/depuis/phase), signale un
      verrou orphelin.
  (c) `veiller` sans argument relance une veille pour chaque lane en vol qui
      n'en a pas de vivante, et seulement celle-la.

Offline : pas de vrai `gh`/`herdr` (redefinis en fonctions bash apres le
`source`, ou evites completement quand la fonction testee ne les appelle
pas -- `verrou_acquerir` ne touche ni l'un ni l'autre).
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


def run(script_body, timeout=30):
    tmp = Path(tempfile.mkdtemp(prefix="circuit-verrou-"))
    try:
        veilles_dir = tmp / "veilles"
        script = (
            f'source "{CIRCUIT_SH.as_posix()}"\n'
            f'REPO="test/repo"\n'
            f'ISSUE="{ISSUE}"\n'
            f'VEILLES_DIR="{veilles_dir.as_posix()}"\n'
            + script_body
        )
        p = subprocess.run(
            [BASH, "-c", script], capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return p, veilles_dir
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- (a) double acquisition : la seconde sort sans rien faire ---------------

script_a1 = '''
verrou_acquerir "$ISSUE"
echo "PREMIER=$?"
verrou_acquerir "$ISSUE"
echo "SECOND=$?"
cat "$(verrou_veille_chemin "$ISSUE")"
'''
p, _ = run(script_a1)
assert "PREMIER=0" in p.stdout, p.stdout
assert "SECOND=1" in p.stdout, p.stdout
assert "veille déjà en cours sur #999" in p.stdout, p.stdout
assert p.stdout.count("pid=") == 1, f"un seul verrou attendu (la seconde acquisition ne l'a pas recree) : {p.stdout!r}"
print("1) verrou_acquerir : deuxieme acquisition sur verrou vivant -> message, sortie 1, verrou inchange")

# ---- (a) verrou orphelin (PID mort) : repris -------------------------------

script_a2 = '''
mkdir -p "$VEILLES_DIR"
sleep 30 &
mortpid=$!
kill "$mortpid" 2>/dev/null
wait "$mortpid" 2>/dev/null
printf 'pid=%s\\ndepuis=08:00\\nphase=revue\\n' "$mortpid" > "$(verrou_veille_chemin "$ISSUE")"
verrou_acquerir "$ISSUE"
echo "ACQUIS=$?"
cat "$(verrou_veille_chemin "$ISSUE")"
'''
p, _ = run(script_a2)
assert "ACQUIS=0" in p.stdout, p.stdout
assert "verrou orphelin" in p.stdout, p.stdout
assert "phase=demarrage" in p.stdout, f"le verrou repris doit reinitialiser la phase : {p.stdout!r}"
print("2) verrou_acquerir : verrou orphelin (PID mort) -> repris, message, sortie 0")

# ---- (b) etat liste les veilles (vivante + orpheline) ----------------------

script_b = '''
herdr() { echo '{"result":{"agents":[]}}'; return 0; }
gh() {
  case "$*" in
    *"pr list"*) echo "[]" ;;
    *) echo "" ;;
  esac
  return 0
}
mkdir -p "$VEILLES_DIR"
printf 'pid=%s\\ndepuis=09:41\\nphase=revue\\n' "$$" > "$VEILLES_DIR/317.pid"
sleep 30 &
mortpid=$!
kill "$mortpid" 2>/dev/null
wait "$mortpid" 2>/dev/null
printf 'pid=%s\\ndepuis=08:12\\nphase=ci\\n' "$mortpid" > "$VEILLES_DIR/313.pid"
etat
'''
p, _ = run(script_b)
assert "--- veilles en cours ---" in p.stdout, p.stdout
assert "#317" in p.stdout and "phase=revue" in p.stdout, p.stdout
assert "depuis=09:41" in p.stdout, p.stdout
assert "#313" in p.stdout and "verrou orphelin" in p.stdout, p.stdout
print("3) etat : section 'veilles en cours' montre la veille vivante et signale le verrou orphelin")

# ---- (c) veiller sans argument relance ce qui manque, seulement ca ---------

script_c = '''
herdr() {
  case "$*" in
    *"agent list"*) echo '{"result":{"agents":[{"name":"lane-100"},{"name":"lane-200"}]}}' ;;
    *) : ;;
  esac
  return 0
}
veiller() { echo "VEILLER-CALL: $1" >> "$CALLS_FILE"; }
mkdir -p "$VEILLES_DIR"
printf 'pid=%s\\ndepuis=09:00\\nphase=ci\\n' "$$" > "$VEILLES_DIR/100.pid"
veiller_relancer_manquantes
wait
echo "=== CALLS ==="
cat "$CALLS_FILE" 2>/dev/null
'''
tmp_c = Path(tempfile.mkdtemp(prefix="circuit-verrou-c-"))
calls_c = tmp_c / "calls.log"
try:
    p, _ = run(f'CALLS_FILE="{calls_c.as_posix()}"\n' + script_c)
finally:
    shutil.rmtree(tmp_c, ignore_errors=True)
assert "#100 : veille déjà vivante" in p.stdout, p.stdout
assert "#200 : pas de veille vivante" in p.stdout, p.stdout
assert "VEILLER-CALL: 100" not in p.stdout, f"lane-100 a deja une veille vivante, ne doit pas etre relancee : {p.stdout!r}"
assert "VEILLER-CALL: 200" in p.stdout, f"lane-200 sans veille vivante devait etre relancee : {p.stdout!r}"
print("4) veiller (sans argument) : relance seulement la lane sans veille vivante")

# ---- (a) deux `veiller <ISSUE>` lances a la suite : un seul travail --------
#
# Critere de l'Issue #323 : "deux veiller 317 lances a la suite -> un seul
# processus, le second sort immediatement avec le message." Le premier
# `veiller` est ralenti (attendre_pr mockee avec un sleep) pour laisser le
# temps au second de constater le verrou vivant avant que le premier ne
# libere le sien (trap EXIT).

script_e = '''
gh() {
  case "$*" in
    *"issue view $ISSUE"*"--json state"*) echo "OPEN" ;;
    *) echo "" ;;
  esac
  return 0
}
pr_mergee_pour_issue() { echo ""; }
attendre_pr() { sleep 3; _PR="42"; return 0; }
attendre_ci() { return 0; }
lancer_revue() { _VERDICT_BODY="REVUE : APPROUVE"; return 0; }
merger_et_nettoyer() { return 0; }
(veiller "$ISSUE") > "$CALLS_FILE" 2>&1 &
premier_pid=$!
sleep 1
(veiller "$ISSUE"); echo "SECOND_EXIT=$?"
wait "$premier_pid"; echo "PREMIER_EXIT=$?"
echo "=== PREMIER (fond) ==="
cat "$CALLS_FILE"
echo "=== VERROU APRES COUP ==="
[ -f "$(verrou_veille_chemin "$ISSUE")" ] && echo "VERROU_RESTE" || echo "VERROU_LIBERE"
'''
tmp_e = Path(tempfile.mkdtemp(prefix="circuit-verrou-e-"))
calls_e = tmp_e / "calls.log"
try:
    p, _ = run(f'CALLS_FILE="{calls_e.as_posix()}"\n' + script_e, timeout=30)
finally:
    shutil.rmtree(tmp_e, ignore_errors=True)
assert "veille déjà en cours sur #999" in p.stdout, f"le second aurait du voir le verrou vivant : {p.stdout!r}"
assert "SECOND_EXIT=0" in p.stdout, p.stdout
assert "PREMIER_EXIT=0" in p.stdout, f"le premier (en fond) devait aller jusqu'au bout : {p.stdout!r}"
assert "VERROU_LIBERE" in p.stdout, "le verrou doit etre libere (trap EXIT) une fois le premier termine"
print("5) deux 'veiller #999' a la suite -> un seul travail, le second sort avec le message, verrou libere ensuite")

# ---- (a) le verrou pose en fond porte le PID du SOUS-SHELL, pas du parent --
#
# REVUE PR #327 (bloquant) : `veiller "$issue" &` (utilise par
# veiller_relancer_manquantes) est un sous-shell -- `$$` y designe le PID du
# shell PARENT (celui du dispatcher `circuit.sh veiller` sans argument, mort
# des sa boucle finie), jamais celui du sous-shell qui execute reellement la
# veille. `$BASHPID` est le bon identifiant. Verifie ici en isolant
# `verrou_acquerir` du reste de `veiller` (le sujet est le choix de variable,
# pas la boucle de phases).

script_f = '''
(verrou_acquerir "$ISSUE"; sleep 2) &
child_pid=$!
sleep 0.3
recorded_pid=$(verrou_lire_champ "$ISSUE" pid)
echo "PARENT_DOLLAR=$$"
echo "CHILD_PID=$child_pid"
echo "RECORDED_PID=$recorded_pid"
wait "$child_pid"
'''
p, _ = run(script_f)
lignes = dict(l.split("=", 1) for l in p.stdout.strip().splitlines() if "=" in l)
assert lignes.get("RECORDED_PID") == lignes.get("CHILD_PID"), (
    f"le verrou doit porter le PID reel du sous-shell (\\$!), pas celui du parent (\\$$) : {p.stdout!r}"
)
assert lignes.get("RECORDED_PID") != lignes.get("PARENT_DOLLAR"), (
    f"le verrou d'une veille en fond ne doit jamais porter le PID du parent (mort des sa sortie) : {p.stdout!r}"
)
print("6) verrou_acquerir en sous-shell (&) : le verrou porte le PID du sous-shell, pas celui du parent")

# ---- (c) chemin de bout en bout : la veille relancee en fond reste vivante
# au sens du verrou apres que le relanceur (dispatcher) est reparti ---------
#
# Reprend le scenario 4 mais sans mocker `veiller` : la vraie fonction pose
# son propre verrou via `verrou_acquerir`, comme en production. Le
# dispatcher (`veiller_relancer_manquantes`) rend la main sans attendre le
# `sleep` de la veille -- exactement le chemin ou le bogue du PID se serait
# manifeste (verrou marque orphelin alors que la veille tourne encore).

script_g = '''
herdr() {
  case "$*" in
    *"agent list"*) echo '{"result":{"agents":[{"name":"lane-500"}]}}' ;;
    *) : ;;
  esac
  return 0
}
veiller() { verrou_acquerir "$1" || return 0; sleep 2; }
veiller_relancer_manquantes
sleep 0.5
recorded_pid=$(verrou_lire_champ "500" pid)
echo "DISPATCHER_DOLLAR=$$"
echo "RECORDED_PID=$recorded_pid"
pid_vivant "$recorded_pid" && echo "VIVANT" || echo "MORT"
'''
p, _ = run(script_g, timeout=30)
lignes = dict(l.split("=", 1) for l in p.stdout.strip().splitlines() if "=" in l and "VIVANT" not in l and "MORT" not in l)
assert "VIVANT" in p.stdout, f"la veille relancee en fond doit rester vivante au sens du verrou : {p.stdout!r}"
assert "MORT" not in p.stdout, p.stdout
assert lignes.get("RECORDED_PID") != lignes.get("DISPATCHER_DOLLAR"), (
    f"le verrou de la veille relancee ne doit pas porter le PID du dispatcher : {p.stdout!r}"
)
print("7) veiller (sans argument) : la veille relancee en fond garde un verrou vivant apres le retour du dispatcher")

print("\nALL CIRCUIT_VEILLER_VERROU TESTS PASSED")
