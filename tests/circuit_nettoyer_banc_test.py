"""Issue #298 : circuit.sh nettoyer <label> refuse nommément tout label
commençant par "banc" -- garde symétrique : le workspace herdr dédié au banc
(tools/lancer-banc-fumee.ps1) ne se nettoie jamais via `circuit.sh
nettoyer`, seul nuit.sh en ferme les panes en fin de nuit.

Offline (jamais de herdr/gh appelés) : le refus a lieu avant tout accès
externe, dans le dispatch de arguments lui-même.
"""
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CIRCUIT_SH = REPO_ROOT / "tools" / "banc" / "circuit.sh"


def find_bash():
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


BASH = find_bash()
assert BASH, "bash introuvable (Git for Windows le fournit)"


def run(args):
    return subprocess.run(
        [BASH, str(CIRCUIT_SH), *args],
        capture_output=True, text=True, timeout=30,
    )


def main():
    assert CIRCUIT_SH.exists(), f"script absent : {CIRCUIT_SH}"

    for label in ("banc", "banc-20260905", "banc-mj-01"):
        p = run(["nettoyer", label])
        assert p.returncode != 0, f"nettoyer {label!r} : code non nul attendu, reçu {p.returncode}"
        assert "REFUS" in p.stderr and label in p.stderr, (
            f"nettoyer {label!r} : refus nommé attendu citant le label ({p.stderr!r})"
        )
        print(f"PASS: circuit.sh nettoyer {label!r} -- REFUS nommé")

    # Garde-fou : le format strict lane-NNN/revue-NNN, lui, reste inchangé
    # (usage générique, pas "REFUS" spécifique banc) pour un label qui ne
    # commence ni par "banc" ni par lane-NNN/revue-NNN.
    p = run(["nettoyer", "autre-chose"])
    assert p.returncode != 0, f"nettoyer 'autre-chose' : code non nul attendu, reçu {p.returncode}"
    assert "Usage" in p.stderr, f"nettoyer 'autre-chose' : message d'usage générique attendu ({p.stderr!r})"
    print("PASS: circuit.sh nettoyer 'autre-chose' -- usage générique, inchangé")

    print("circuit_nettoyer_banc_test: 4/4 OK")


if __name__ == "__main__":
    main()
