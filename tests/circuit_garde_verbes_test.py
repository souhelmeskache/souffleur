"""Issue #255 : circuit.sh point d'entrée unique — verbes `garde`/`lancer`/
`revoir` et aide sans argument. Offline (pas de gh, pas de herdr, pas de
`powershell` réel) : `garde_core_bare` est exercée par `source` sur un dépôt
Git JETABLE (jamais le vrai MAIN_REPO codé en dur dans circuit.sh — on
réaffecte les variables globales après le `source`, avant l'appel) ; le
script est invoqué en process réel seulement sur les chemins qui ne touchent
ni gh ni herdr (aide, arguments manquants).
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


def run(args):
    return subprocess.run([BASH, str(CIRCUIT_SH), *args], capture_output=True, text=True, timeout=30)


# ---- aide sans argument : les six verbes -------------------------------------

p = run([])
assert p.returncode == 1, f"circuit.sh sans argument devrait sortir 1, code={p.returncode}"
for verbe in ("lancer", "veiller", "revoir", "nettoyer", "etat", "garde"):
    assert verbe in p.stderr, f"verbe {verbe!r} absent de l'aide : {p.stderr!r}"
print("1) circuit.sh sans argument liste les six verbes")

# ---- lancer/revoir sans argument : usage, jamais d'appel a powershell -------

p = run(["lancer"])
assert p.returncode == 1, f"lancer sans ISSUE devrait sortir 1, code={p.returncode}"
assert "Usage" in p.stderr and "lancer" in p.stderr, p.stderr
print("2) 'lancer' sans ISSUE : usage, pas de lancement")

p = run(["revoir"])
assert p.returncode == 1, f"revoir sans PR devrait sortir 1, code={p.returncode}"
assert "Usage" in p.stderr and "revoir" in p.stderr, p.stderr
print("3) 'revoir' sans PR : usage, pas de lancement")

# ---- garde_core_bare : dépôt Git jetable, jamais le vrai MAIN_REPO ----------

tmp = Path(tempfile.mkdtemp(prefix="circuit-garde-"))
try:
    subprocess.run(["git", "init", "-q", str(tmp)], check=True, timeout=30)
    # `git init` pose lui-même `core.bare = false` dans le config créé — le
    # retirer d'abord pour simuler l'état "absent" réel (une repo neuve n'a
    # jamais cette clé tant que rien ne l'y écrit).
    subprocess.run(["git", "-C", str(tmp), "config", "--unset", "core.bare"], check=True, timeout=30)
    log = tmp / "core-bare.log"

    # core.bare absent : idempotent, rien loggé.
    script = (
        f'source "{CIRCUIT_SH.as_posix()}" && '
        f'MAIN_REPO="{tmp.as_posix()}" && CORE_BARE_LOG="{log.as_posix()}" && '
        f'garde_core_bare "test-absent"'
    )
    p = subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    assert "absent" in p.stdout, p.stdout
    assert not log.exists(), "aucun log attendu quand core.bare est déjà absent"
    print("4) garde_core_bare : core.bare absent -> idempotent, rien loggé")

    # core.bare présent : retire + logge (heure, origine, commande).
    subprocess.run(["git", "-C", str(tmp), "config", "core.bare", "true"], check=True, timeout=30)
    script = (
        f'source "{CIRCUIT_SH.as_posix()}" && '
        f'MAIN_REPO="{tmp.as_posix()}" && CORE_BARE_LOG="{log.as_posix()}" && '
        f'garde_core_bare "test-present"'
    )
    p = subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr

    valeur = subprocess.run(
        ["git", "-C", str(tmp), "config", "--get", "core.bare"],
        capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    assert valeur == "", f"core.bare aurait dû être retiré, encore = {valeur!r}"
    assert log.exists(), "core-bare.log attendu quand core.bare était présent"
    ligne = log.read_text(encoding="utf-8").strip()
    assert "test-present" in ligne, f"commande absente de la ligne de log : {ligne!r}"
    print("5) garde_core_bare : core.bare présent -> retiré + loggé (commande incluse)")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nALL CIRCUIT_GARDE_VERBES TESTS PASSED")
