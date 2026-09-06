"""#328 (d) -- `circuit.sh veiller <ISSUE>` doit lancer le travail dans un
processus DÉTACHÉ du fil appelant : sa fin ne doit réveiller personne.
Mesuré le 06/09 : le fil du matin (clôturé 09:56) s'est réveillé à la fin
de sa veille #313 (merge 11:01, tâche de fond du fil qui l'avait lancée), a
relancé la lane #311 et rouvert #321 -- deux tours de contrôle sur le même
circuit.

`setsid` est absent de ce bash de Git for Windows (jamais sur PATH) --
`veiller_detachee` utilise `nohup` (ignore SIGHUP) + `disown` (retire le job
de la table de jobs du shell courant). Ce test vérifie :

  1) `veiller_detachee` rend la main en moins de 2s (critère #328).
  2) le travail continue dans un second process, journalisé sous
     $VEILLES_DIR/<ISSUE>.log, MÊME APRÈS que le process appelant (celui qui
     a invoqué `veiller_detachee`) est terminé -- la preuve du détachement.

`CIRCUIT_SCRIPT` (réaffectée après `source`, même discipline que
REPO/MAIN_REPO/VEILLES_DIR) pointe vers un petit script wrapper qui source
le vrai circuit.sh, redéfinit gh/herdr/attendre_pr offline, puis dispatche
sur `_veiller_interne` -- le process détaché s'exécute donc entièrement
hors-ligne, jamais contre le vrai dépôt/repo GitHub.
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

tmp = Path(tempfile.mkdtemp(prefix="circuit-detachee-"))
try:
    veilles_dir = tmp / "veilles"
    veilles_dir.mkdir()

    # Wrapper hors-ligne re-invoqué par veiller_detachee (à la place du vrai
    # circuit.sh) : source le vrai script (fonctions réelles), écrase les
    # variables/fonctions qui toucheraient un vrai gh/herdr/repo, puis
    # dispatche lui-même sur `_veiller_interne` -- même garde de dispatch
    # que le vrai fichier, en plus court.
    wrapper = tmp / "circuit-wrapper.sh"
    wrapper.write_text(
        f'#!/bin/bash\n'
        f'set -u\n'
        f'source "{CIRCUIT_SH.as_posix()}"\n'
        f'REPO="test/repo"\n'
        f'VEILLES_DIR="{veilles_dir.as_posix()}"\n'
        'gh() { echo "CLOSED"; return 0; }\n'
        'herdr() { : ; return 0; }\n'
        'case "${1:-}" in\n'
        '  _veiller_interne) veiller "${2:-}" ;;\n'
        '  *) exit 1 ;;\n'
        'esac\n',
        encoding="utf-8", newline="\n",
    )

    caller = tmp / "caller.sh"
    caller.write_text(
        f'#!/bin/bash\n'
        f'set -u\n'
        f'source "{CIRCUIT_SH.as_posix()}"\n'
        f'VEILLES_DIR="{veilles_dir.as_posix()}"\n'
        f'CIRCUIT_SCRIPT="{wrapper.as_posix()}"\n'
        f'veiller_detachee "{ISSUE}"\n',
        encoding="utf-8", newline="\n",
    )

    t0 = time.monotonic()
    p = subprocess.run(
        [BASH, str(caller)], capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
    )
    elapsed = time.monotonic() - t0
    assert p.returncode == 0, f"veiller_detachee (process appelant) doit sortir 0 : {p.stdout!r} {p.stderr!r}"
    assert elapsed < 2, f"attendu retour en moins de 2s, mesuré {elapsed:.2f}s"
    assert f"veille #{ISSUE}" in p.stdout and "détachée" in p.stdout, p.stdout
    print(f"1) veiller_detachee rend la main en {elapsed:.2f}s (< 2s), le process appelant est déjà terminé")

    # Le process appelant (caller.sh) est terminé depuis le `assert` ci-dessus
    # -- toute activité observée maintenant vient nécessairement du second
    # process, détaché. Le journal de l'issue #999 doit exister et avancer
    # (gh() de la veille (issue CLOSED) -> `veiller` sort 0 immédiatement
    # sans rien attendre 90 min, donc le journal se remplit vite).
    log = veilles_dir / f"{ISSUE}.log"
    contenu = ""
    for _ in range(30):
        if log.exists():
            contenu = log.read_text(encoding="utf-8", errors="replace")
            if "déjà fermée" in contenu:
                break
        time.sleep(0.5)
    assert log.exists(), f"journal {log} absent -- le second process n'a jamais démarré"
    assert "déjà fermée" in contenu, (
        f"le second process (détaché) doit avoir tourné jusqu'à sa sortie idempotente "
        f"après la fin du process appelant : {contenu!r}"
    )
    print("2) le travail continue dans un second process (journal rempli) après la fin du process appelant -- détachement effectif")

    print("\nALL CIRCUIT_VEILLER_DETACHEE TESTS PASSED")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
