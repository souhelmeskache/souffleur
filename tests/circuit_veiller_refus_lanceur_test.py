"""#328 (f) -- circuit.sh veiller, phase revue : `lancer_revue` ne doit pas
avaler le refus du lanceur (`lancer-lane.ps1 -Revue`). Mesuré sur PR#320 :
`revue-320` existait déjà (pane de la revue précédente, `done`), le lanceur
a refusé (collision de nom) et la veille a attendu 90 min un verdict
impossible -- le code de sortie du lanceur, piégé derrière `| tail -1`,
était jusqu'ici ignoré.

Attendu : `nettoyer_une "revue-<PR>"` AVANT tout lancement (idempotente,
déjà utilisée ailleurs dans ce script), puis le code de sortie du lanceur
testé via PIPESTATUS[0] -- un refus (sortie != 0) doit ressortir en `return
4` de `lancer_revue`, message = dernière ligne de sa sortie, et faire
sortir `veiller` en moins de 5s avec ce message sur l'Issue (jamais une
attente de 90 min).

Deux volets, chacun un appel bash indépendant :
  1) `lancer_revue` seule : faux lanceur qui sort 1 -> return 4,
     $_LANCEUR_ECHEC porte sa dernière ligne, nettoyer_une appelée avant.
  2) `veiller` de bout en bout (attente_pr/ci mockées, revue -> refus du
     lanceur) : sortie 1 en moins de 5s, message du lanceur sur l'Issue.
"""
import shutil
import subprocess
import tempfile
import time
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

# ---- 1) lancer_revue seule : faux lanceur qui sort 1 -----------------------

tmp1 = Path(tempfile.mkdtemp(prefix="circuit-refus-lanceur-1-"))
calls1 = tmp1 / "calls.log"
try:
    script1 = (
        f'source "{CIRCUIT_SH.as_posix()}"\n'
        f'REPO="test/repo"\n'
        f'PR="{PR}"\n'
        f'CALLS_FILE="{calls1.as_posix()}"\n'
        'nettoyer_une() { echo "NETTOYER-CALL: $*" >> "$CALLS_FILE"; return 0; }\n'
        'gh() {\n'
        '  case "$*" in\n'
        '    *"pr view $PR"*"--json commits"*) echo "" ;;\n'
        '    *"pr view $PR"*"--json comments"*) echo "" ;;\n'
        '    *) echo "" ;;\n'
        '  esac\n'
        '  return 0\n'
        '}\n'
        'powershell.exe() { echo "REFUS : revue-42 existe deja (pane done)."; return 1; }\n'
        'lancer_revue "$PR"; echo "EXIT=$?"\n'
        'echo "LANCEUR_ECHEC=$_LANCEUR_ECHEC"\n'
    )
    p = subprocess.run(
        [BASH, "-c", script1], capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
    )
    assert "EXIT=4" in p.stdout, f"attendu return 4 (lanceur refusé) : {p.stdout!r} {p.stderr!r}"
    assert "LANCEUR_ECHEC=REFUS : revue-42 existe deja (pane done)." in p.stdout, p.stdout
    assert calls1.exists() and "NETTOYER-CALL: revue-42" in calls1.read_text(encoding="utf-8"), (
        "nettoyer_une doit être appelée AVANT le lancement, même en cas de refus"
    )
    print("1) lancer_revue : faux lanceur qui sort 1 -> return 4, dernière ligne portée, nettoyer_une appelée avant")
finally:
    shutil.rmtree(tmp1, ignore_errors=True)

# ---- 2) veiller de bout en bout : sortie < 5s avec le message du lanceur ---

tmp2 = Path(tempfile.mkdtemp(prefix="circuit-refus-lanceur-2-"))
calls2 = tmp2 / "calls.log"
veilles2 = tmp2 / "veilles"
try:
    script2 = (
        f'source "{CIRCUIT_SH.as_posix()}"\n'
        f'REPO="test/repo"\n'
        f'ISSUE="{ISSUE}"\n'
        f'PR="{PR}"\n'
        f'CALLS_FILE="{calls2.as_posix()}"\n'
        f'VEILLES_DIR="{veilles2.as_posix()}"\n'
        'gh() {\n'
        '  case "$*" in\n'
        '    *"issue view $ISSUE"*"--json state"*) echo "OPEN" ;;\n'
        '    *"pr list"*"--state merged"*) echo "" ;;\n'
        '    *"pr list"*"--head lane-$ISSUE"*"--state open"*) echo "$PR" ;;\n'
        '    *"pr view $PR"*"--json statusCheckRollup"*) echo "SUCCESS" ;;\n'
        '    *"pr view $PR"*"--json mergeStateStatus"*) echo "CLEAN" ;;\n'
        '    *"pr view $PR"*"--json commits"*) echo "" ;;\n'
        '    *"pr view $PR"*"--json comments"*) echo "" ;;\n'
        '    *"issue comment"*) echo "GH-CALL: $*" >> "$CALLS_FILE" ;;\n'
        '    *) echo "" ;;\n'
        '  esac\n'
        '  return 0\n'
        '}\n'
        'herdr() {\n'
        '  case "$*" in\n'
        '    *"agent list"*) echo \'{"result":{"agents":[{"name":"lane-999","agent_status":"idle"}]}}\' ;;\n'
        '    *) : ;;\n'
        '  esac\n'
        '  return 0\n'
        '}\n'
        'nettoyer_une() { echo "NETTOYER-CALL: $*" >> "$CALLS_FILE"; return 0; }\n'
        'powershell.exe() { echo "REFUS : revue-42 existe deja (pane done)."; return 1; }\n'
        '(veiller "$ISSUE"); echo "EXIT=$?"\n'
        'echo "=== CALLS ==="; cat "' + calls2.as_posix() + '" 2>/dev/null\n'
    )
    t0 = time.monotonic()
    p = subprocess.run(
        [BASH, "-c", script2], capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
    )
    elapsed = time.monotonic() - t0
    assert elapsed < 5, f"attendu sortie en moins de 5s, mesuré {elapsed:.1f}s : {p.stdout!r} {p.stderr!r}"
    assert "EXIT=1" in p.stdout, f"attendu sortie 1 (lanceur refusé) : {p.stdout!r} {p.stderr!r}"
    assert "GH-CALL: issue comment 999 -R test/repo --body VEILLE 999 : 1 lanceur de revue refusé : REFUS : revue-42 existe deja (pane done). revue" in p.stdout, (
        f"attendu le message du lanceur sur l'Issue : {p.stdout!r}"
    )
    print(f"2) veiller de bout en bout : sortie 1 en {elapsed:.2f}s avec le message du lanceur sur l'Issue")
finally:
    shutil.rmtree(tmp2, ignore_errors=True)

print("\nALL CIRCUIT_VEILLER_REFUS_LANCEUR TESTS PASSED")
