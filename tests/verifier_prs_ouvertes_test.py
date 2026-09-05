"""Issue #297 : tools/banc/verifier-prs-ouvertes.sh -- garde extraite de
verifier-avant-nuit.sh, classant le nombre de PR ouvertes sur le dépôt.

Direction Souhel du 05/09 (D-280, #292) : les parties tournent en parallèle
du circuit de code -- une PR ouverte est l'état normal du dépôt et n'entre
pas en collision avec une nuit. #292/PR #293 avait déjà converti le refus
« lane en vol » en avertissement ; celui-ci (PR ouverte, l. 126-129) restait
un REFUS -- corrigé ici (#297).

1. Aucune PR ouverte (0) -> OK, code 0, sortie vide.
2. Une PR ouverte -> OK, code 0, AVERTISSEMENT citant le nombre.
3. Plusieurs PR ouvertes -> OK, code 0, AVERTISSEMENT citant le compte.
4. Sortie vide/non numérique (échec gh) -> OK, code 0, sortie vide (jamais
   un refus sur une panne de lecture du décompte).
"""
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "banc" / "verifier-prs-ouvertes.sh"


def find_bash():
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


BASH = find_bash()
assert BASH, "bash introuvable (Git for Windows le fournit)"


def lancer(entree: str):
    return subprocess.run(
        [BASH, str(SCRIPT)],
        input=entree, capture_output=True, timeout=60,
        encoding="utf-8", errors="replace",
    )


def main():
    assert SCRIPT.exists(), f"script absent : {SCRIPT}"

    # ------------------------------------------------------------------
    # Cas 1 : aucune PR ouverte -> OK, sortie vide
    # ------------------------------------------------------------------
    p1 = lancer("0")
    assert p1.returncode == 0, f"cas 1 : code attendu 0, reçu {p1.returncode}\n{p1.stderr}"
    assert p1.stdout.strip() == "", f"cas 1 : sortie attendue vide, reçu {p1.stdout!r}"
    print("PASS: cas 1 -- aucune PR ouverte, OK silencieux")

    # ------------------------------------------------------------------
    # Cas 2 : une PR ouverte -> OK avec avertissement
    # ------------------------------------------------------------------
    p2 = lancer("1")
    assert p2.returncode == 0, f"cas 2 : code attendu 0, reçu {p2.returncode}\n{p2.stderr}"
    assert "AVERTISSEMENT" in p2.stdout, f"cas 2 : AVERTISSEMENT attendu ({p2.stdout})"
    assert "1 PR ouverte" in p2.stdout, f"cas 2 : compte attendu dans l'avertissement ({p2.stdout})"
    print("PASS: cas 2 -- une PR ouverte, OK avec avertissement")

    # ------------------------------------------------------------------
    # Cas 3 : plusieurs PR ouvertes -> OK avec avertissement complet
    # ------------------------------------------------------------------
    p3 = lancer("3")
    assert p3.returncode == 0, f"cas 3 : code attendu 0, reçu {p3.returncode}\n{p3.stderr}"
    assert "AVERTISSEMENT" in p3.stdout
    assert "3 PR ouverte" in p3.stdout, f"cas 3 : compte attendu ({p3.stdout})"
    print("PASS: cas 3 -- plusieurs PR ouvertes, OK avec avertissement")

    # ------------------------------------------------------------------
    # Cas 4 : sortie vide/non numérique (échec gh) -> OK silencieux
    # ------------------------------------------------------------------
    p4 = lancer("")
    assert p4.returncode == 0, f"cas 4 : code attendu 0, reçu {p4.returncode}\n{p4.stderr}"
    assert p4.stdout.strip() == "", f"cas 4 : sortie attendue vide, reçu {p4.stdout!r}"
    print("PASS: cas 4 -- décompte illisible, OK silencieux")

    print("OK")


if __name__ == "__main__":
    main()
