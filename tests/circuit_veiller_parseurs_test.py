"""I-250 -- circuit.sh veiller : parseurs offline (pas de gh, pas de herdr).

`tools/banc/circuit.sh veiller <ISSUE>` est UN watcher par circuit de lane
(attente PR -> CI -> revue -> merge, avec renvoi automatique du verdict a la
lane sur REFUS). Ce test n'exerce pas la boucle elle-meme (elle appelle gh/
herdr, hors perimetre offline de cette suite) mais les deux parseurs purs
dont depend sa logique de branchement :

  - `parser_verdict` : premiere ligne d'un commentaire "REVUE : ..." ->
    APPROUVE / REFUS / ABSENT.
  - `parser_termine_pr` : corps d'un commentaire TERMINE -> numero de PR
    extrait de la derniere URL /pull/NNN qu'il contient (vide si aucune).

Le fichier est `source`, jamais execute : le garde `BASH_SOURCE == $0` en
bas de circuit.sh n'entre dans le dispatch (et donc n'exige pas gh/herdr)
que lorsque le script est lance directement.
"""
import shutil
import subprocess
import sys
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


def appelle(fonction, entree):
    """Source circuit.sh, appelle `fonction` avec `entree` sur stdin, renvoie stdout (trim)."""
    script = f'source "{CIRCUIT_SH.as_posix()}" && {fonction}'
    p = subprocess.run([BASH, "-c", script], input=entree, capture_output=True,
                        text=True, timeout=30)
    assert p.returncode == 0, f"{fonction}({entree!r}) a echoue : {p.stderr}"
    return p.stdout.strip()


# ---- parser_verdict ----------------------------------------------------------

assert appelle("parser_verdict", "REVUE : APPROUVE\ndetail...\n") == "APPROUVE"
print("1) verdict APPROUVE reconnu")

assert appelle("parser_verdict", "REVUE : REFUS\nmotif...\n") == "REFUS"
print("2) verdict REFUS reconnu")

assert appelle("parser_verdict", "un commentaire quelconque, pas un verdict\n") == "ABSENT"
print("3) commentaire sans verdict -> ABSENT")

assert appelle("parser_verdict", "") == "ABSENT"
print("4) commentaire vide -> ABSENT (pas de crash sur head -1 vide)")

# la premiere ligne fait foi, pas une occurrence plus bas dans le corps
assert appelle("parser_verdict", "un commentaire de lane\nqui cite REVUE : APPROUVE en exemple\n") == "ABSENT"
print("5) 'REVUE : APPROUVE' hors premiere ligne n'est pas pris pour un verdict")

# ---- parser_termine_pr --------------------------------------------------------

assert appelle("parser_termine_pr",
               "TERMINE : https://github.com/souhelmeskache/souffleur/pull/123\n") == "123"
print("6) URL de PR extraite d'un TERMINE simple")

assert appelle("parser_termine_pr",
               "TERMINE : voir aussi https://github.com/x/y/pull/1 puis "
               "https://github.com/x/y/pull/456 — REVUE REQUISE\n") == "456"
print("7) plusieurs URLs -> la derniere est retenue (verdict le plus recent)")

assert appelle("parser_termine_pr", "TERMINE : correctif pousse, pas de PR ici\n") == ""
print("8) aucune URL de PR -> vide (jamais de faux numero)")

print("\nALL CIRCUIT_VEILLER_PARSEURS TESTS PASSED")
