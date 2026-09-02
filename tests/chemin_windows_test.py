"""Issue #270 : tools/banc/chemin-windows.sh -- fonction de conversion
`chemin_windows_depuis_bash`, frontière bash ⊥ Windows.

Cas couverts (repris de la demande #270) :
1. `/c/Users/x`   -> converti en chemin Windows valide (lettre de lecteur C:).
2. `C:/Users/x`   -> inchangé (déjà en forme Windows, slash).
3. `C:\\Users\\x` -> inchangé (déjà en forme Windows, backslash).
4. `/home/x`      -> inchangé (pas de lettre de lecteur à traduire).

Le test ne peut pas dépendre de `cygpath` (peut être absent) ni de sa forme
exacte de sortie (slash vs backslash) : il vérifie que le résultat, une fois
formé, DÉSIGNE le bon fichier pour python.exe -- test de bout en bout plutôt
que de chaîne exacte, sauf pour les cas "inchangé" où l'égalité stricte est
le contrat.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "banc" / "chemin-windows.sh"


def find_bash():
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


BASH = find_bash()
assert BASH, "bash introuvable (Git for Windows le fournit)"


def convertir(chemin: str) -> str:
    p = subprocess.run(
        [BASH, "-c", f'source "{SCRIPT.as_posix()}" && chemin_windows_depuis_bash "$1"',
         "_", chemin],
        capture_output=True, timeout=30, encoding="utf-8", errors="replace",
    )
    assert p.returncode == 0, f"chemin_windows_depuis_bash a échoué sur {chemin!r} : {p.stderr}"
    return p.stdout.strip()


def python_voit_le_fichier(chemin_windows: str, cible: Path) -> bool:
    """python.exe (natif Windows) ouvre-t-il `chemin_windows` comme désignant `cible` ?"""
    p = subprocess.run(
        ["python", "-c", f"open(r'{chemin_windows}', encoding='utf-8').read()"],
        capture_output=True, timeout=30, encoding="utf-8", errors="replace",
    )
    return p.returncode == 0


def main():
    assert SCRIPT.exists(), f"script absent : {SCRIPT}"

    tmp_root = Path(tempfile.mkdtemp(prefix="chemin-windows-test-"))
    try:
        marqueur = tmp_root / "marqueur.txt"
        marqueur.write_text("ok", encoding="utf-8")

        # --------------------------------------------------------------
        # Cas 1 : /c/Users/x (forme Git Bash réelle du fichier créé ci-dessus)
        # --------------------------------------------------------------
        drive = tmp_root.drive.rstrip(":").lower()
        reste = str(marqueur)[len(tmp_root.drive):].replace("\\", "/")
        forme_gitbash = f"/{drive}{reste}"
        assert forme_gitbash.startswith(f"/{drive}/"), forme_gitbash

        converti = convertir(forme_gitbash)
        assert converti != forme_gitbash, (
            f"cas 1 : {forme_gitbash!r} aurait dû être converti, reçu inchangé"
        )
        assert python_voit_le_fichier(converti, marqueur), (
            f"cas 1 : {forme_gitbash!r} converti en {converti!r}, "
            f"mais python.exe ne retrouve pas le fichier"
        )
        print(f"PASS: cas 1 -- {forme_gitbash!r} -> {converti!r} (python.exe le lit)")

        # --------------------------------------------------------------
        # Cas 2 : C:/Users/x -- déjà en forme Windows (slash) -- inchangé
        # --------------------------------------------------------------
        forme_windows_slash = str(marqueur).replace("\\", "/")
        converti2 = convertir(forme_windows_slash)
        assert converti2 == forme_windows_slash, (
            f"cas 2 : {forme_windows_slash!r} aurait dû rester inchangé, reçu {converti2!r}"
        )
        print(f"PASS: cas 2 -- {forme_windows_slash!r} inchangé")

        # --------------------------------------------------------------
        # Cas 3 : C:\Users\x -- déjà en forme Windows (backslash) -- inchangé
        # --------------------------------------------------------------
        forme_windows_backslash = str(marqueur)
        converti3 = convertir(forme_windows_backslash)
        assert converti3 == forme_windows_backslash, (
            f"cas 3 : {forme_windows_backslash!r} aurait dû rester inchangé, reçu {converti3!r}"
        )
        print(f"PASS: cas 3 -- {forme_windows_backslash!r} inchangé")

        # --------------------------------------------------------------
        # Cas 4 : /home/x -- pas de lettre de lecteur -- inchangé
        # --------------------------------------------------------------
        forme_home = "/home/x/fichier.txt"
        converti4 = convertir(forme_home)
        assert converti4 == forme_home, (
            f"cas 4 : {forme_home!r} aurait dû rester inchangé, reçu {converti4!r}"
        )
        print(f"PASS: cas 4 -- {forme_home!r} inchangé")

        print("chemin_windows_test: 4/4 OK")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
