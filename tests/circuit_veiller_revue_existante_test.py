"""#328 (e) -- circuit.sh veiller, phase revue : `lancer_revue` doit lire un
verdict `REVUE :` EXISTANT, postérieur au DERNIER COMMIT de la PR (`gh pr
view --json commits`), avant d'en relancer une. T0 = date de ce dernier
commit, jamais l'heure de la veille (#317/PR#320 : la veille relancée à
12:01:27 n'a pas vu l'APPROUVE de 12:01:37, une 3e revue a été jouée pour
rien).

Ce test source circuit.sh (jamais exécuté directement -- pas de dispatch,
donc pas besoin de gh/herdr réels) et redéfinit `gh` en fonction bash après
le source, comme les autres tests `circuit_veiller_*`. `powershell.exe` est
également redéfinie (nom de fonction avec point, valide en bash) pour
détecter tout lancement de revue qui ne devrait pas avoir lieu -- c'est le
sujet du volet 1.

Deux volets, chacun un appel bash indépendant :
  1) APPROUVE postérieur au dernier commit -> pas de relance, `_VERDICT_BODY`
     porte ce verdict directement.
  2) APPROUVE ANTÉRIEUR au dernier commit -> ignoré, une revue est relancée
     (powershell.exe appelée), le nouveau verdict est celui posté après.
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

PR = "42"


def run(gh_fakes, calls_file, timeout=30):
    script = (
        f'source "{CIRCUIT_SH.as_posix()}"\n'
        f'REPO="test/repo"\n'
        f'PR="{PR}"\n'
        f'CALLS_FILE="{calls_file.as_posix()}"\n'
        'nettoyer_une() { echo "NETTOYER-CALL: $*" >> "$CALLS_FILE"; return 0; }\n'
        + gh_fakes
        + 'lancer_revue "$PR"; echo "EXIT=$?"\n'
        + 'echo "VERDICT_BODY=$_VERDICT_BODY"\n'
    )
    return subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=timeout)


# ---- 1) APPROUVE postérieur au dernier commit -> pas de relance -----------

tmp1 = Path(tempfile.mkdtemp(prefix="circuit-revue-existante-1-"))
calls1 = tmp1 / "calls.log"
try:
    gh_fakes_1 = '''
gh() {
  case "$*" in
    *"pr view $PR"*"--json commits"*) echo "2026-09-06T12:00:00Z" ;;
    *"pr view $PR"*"--json comments"*)
      echo "REVUE : APPROUVE -- rien a redire (postee 12:01:37)" ;;
    *) echo "" ;;
  esac
  return 0
}
powershell.exe() { echo "POWERSHELL-CALL: $*" >> "$CALLS_FILE"; return 0; }
'''
    p = run(gh_fakes_1, calls1)
    assert "EXIT=0" in p.stdout, f"attendu succès sans relance : {p.stdout!r} {p.stderr!r}"
    assert "VERDICT_BODY=REVUE : APPROUVE" in p.stdout, p.stdout
    assert not calls1.exists() or "POWERSHELL-CALL" not in calls1.read_text(encoding="utf-8"), (
        "un APPROUVE postérieur au dernier commit ne doit PAS relancer -Revue"
    )
    print("1) APPROUVE postérieur au dernier commit : pas de relance, verdict existant repris")
finally:
    shutil.rmtree(tmp1, ignore_errors=True)

# ---- 2) APPROUVE antérieur au dernier commit -> ignoré, revue relancée ----

tmp2 = Path(tempfile.mkdtemp(prefix="circuit-revue-existante-2-"))
calls2 = tmp2 / "calls.log"
try:
    gh_fakes_2 = '''
gh() {
  case "$*" in
    *"pr view $PR"*"--json commits"*) echo "2026-09-06T12:05:00Z" ;;
    *"pr view $PR"*"--json comments"*)
      # Le verdict "existant" est ANTERIEUR au dernier commit (12:01:37 <
      # 12:05:00) -- le jq réel du script filtre sur createdAt > T0, mais ce
      # faux gh n'exécute pas jq : il simule directement le résultat déjà
      # filtré, càd rien avant la relance, puis l'APPROUVE frais après.
      if [ -f "$CALLS_FILE.releve" ]; then
        echo "REVUE : APPROUVE -- verdict frais post-relance"
      else
        echo ""
      fi
      ;;
    *) echo "" ;;
  esac
  return 0
}
powershell.exe() {
  echo "POWERSHELL-CALL: $*" >> "$CALLS_FILE"
  echo "1" > "$CALLS_FILE.releve"
  return 0
}
'''
    p = run(gh_fakes_2, calls2)
    assert "EXIT=0" in p.stdout, f"attendu succès après relance : {p.stdout!r} {p.stderr!r}"
    assert calls2.exists() and "POWERSHELL-CALL" in calls2.read_text(encoding="utf-8"), (
        "un APPROUVE antérieur au dernier commit doit être ignoré et une revue relancée"
    )
    assert "VERDICT_BODY=REVUE : APPROUVE -- verdict frais post-relance" in p.stdout, p.stdout
    print("2) APPROUVE antérieur au dernier commit : ignoré, revue relancée, nouveau verdict repris")
finally:
    shutil.rmtree(tmp2, ignore_errors=True)

print("\nALL CIRCUIT_VEILLER_REVUE_EXISTANTE TESTS PASSED")
