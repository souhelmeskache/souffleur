"""Issue #255 : deux défauts constatés le 02/09 sur `tools/lancer-lane.ps1`
en mode -Issue (couverts ensemble ici par un vrai lancement -DryRun, `gh`
étant remplacé par un stub hors-ligne — aucun réseau, aucun modèle) :

- **UTF-8** : `-DryRun` affichait le gabarit en mojibake (« R´┐¢gles » au lieu
  de « Règles ») — la sortie capturée d'un programme natif (`gh`) était
  décodée avec l'encodage par défaut de PowerShell 5.1 plutôt qu'UTF-8. Ce
  test vérifie que la sortie -DryRun, décodée en UTF-8, ne contient aucun
  caractère de remplacement (U+FFFD) et restitue intacts les accents du
  corps d'Issue simulé.
- **Cadrage** : un commentaire posté après l'ouverture de l'Issue, dont le
  corps commence par `Cadrage`, doit apparaître dans le gabarit sous le
  titre « Cadrage (commentaires de l'Issue) » ; un commentaire qui ne
  commence pas par ce mot ne doit PAS y apparaître.

Le stub `gh` répond directement en fonction des champs `--json` demandés
(`labels` pour l'Issue elle-même, `comments` pour ses commentaires) — pas
besoin d'un vrai dépôt ni d'un jeton `gh`. `herdr` est stubé (jamais invoqué
par la branche -DryRun du mode -Issue, mais sa seule PRÉSENCE sur le PATH
est nécessaire : le script résout `gh`/`herdr` avant de savoir qu'il est en
-DryRun).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "lancer-lane.ps1"

ISSUE_NUMBER = 999999
CORPS_ACCENTUE = "Ceci est le corps de l'Issue, avec des accents : é è à ç ù œ."
COMMENTAIRE_CADRAGE = "Cadrage : précise le périmètre — n'inclus pas la partie réseau."
COMMENTAIRE_HORS_CADRAGE = "Un simple commentaire de suivi, sans rapport avec le cadrage."

GH_STUB = r"""
import json
import sys

args = sys.argv[1:]
# Trouve la valeur qui suit --json (dernier argument dans les deux appels du
# script sous test : `... --json number,title,body,labels,url` puis
# `... --json comments`).
json_fields = ""
for i, a in enumerate(args):
    if a == "--json" and i + 1 < len(args):
        json_fields = args[i + 1]
        break

if "labels" in json_fields:
    payload = {
        "number": %(issue)d,
        "title": "Titre de test",
        "body": %(body)r,
        "labels": [{"name": "prete"}],
        "url": "https://github.com/souhelmeskache/souffleur/issues/%(issue)d",
    }
elif "comments" in json_fields:
    payload = {
        "comments": [
            {"body": %(cadrage)r},
            {"body": %(hors_cadrage)r},
        ]
    }
else:
    sys.stderr.write("gh stub: --json inattendu: " + json_fields + "\n")
    sys.exit(1)

sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
sys.stdout.buffer.write(b"\n")
""" % {
    "issue": ISSUE_NUMBER,
    "body": CORPS_ACCENTUE,
    "cadrage": COMMENTAIRE_CADRAGE,
    "hors_cadrage": COMMENTAIRE_HORS_CADRAGE,
}

GH_CMD = "@echo off\r\npython \"%~dp0gh_stub.py\" %*\r\n"
HERDR_CMD = "@echo off\r\nrem stub herdr (#255 dryrun test) : jamais invoque par la branche -DryRun\r\n"


def find_powershell():
    for name in ("powershell", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return None


def main():
    ps_exe = find_powershell()
    assert ps_exe, "powershell/pwsh introuvable — requis pour ce test (CI: windows-latest)"
    assert SCRIPT.exists(), f"script absent : {SCRIPT}"

    stub_dir = Path(tempfile.mkdtemp(prefix="lancer-lane-dryrun-"))
    try:
        (stub_dir / "gh_stub.py").write_text(GH_STUB, encoding="utf-8")
        (stub_dir / "gh.cmd").write_text(GH_CMD, encoding="utf-8")
        (stub_dir / "herdr.cmd").write_text(HERDR_CMD, encoding="utf-8")

        env = {**os.environ, "PATH": str(stub_dir) + os.pathsep + os.environ.get("PATH", "")}

        p = subprocess.run(
            [ps_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
             str(ISSUE_NUMBER), "-DryRun"],
            capture_output=True, timeout=60, env=env,
        )
        assert p.returncode == 0, (
            f"lancer-lane.ps1 -DryRun a échoué (code {p.returncode})\n"
            f"stdout={p.stdout!r}\nstderr={p.stderr!r}"
        )

        sortie = p.stdout.decode("utf-8")  # lève si un octet n'est pas de l'UTF-8 valide
        assert "�" not in sortie, (
            f"caractère de remplacement (U+FFFD) trouvé dans la sortie -DryRun — "
            f"mojibake encore présent.\nsortie={sortie!r}"
        )
        print("PASS: sortie -DryRun décodable en UTF-8 strict, sans U+FFFD")

        assert CORPS_ACCENTUE in sortie, (
            f"le corps accentué du gabarit n'est pas restitué intact.\nsortie={sortie!r}"
        )
        print("PASS: accents du corps d'Issue restitués intacts")

        assert "Cadrage (commentaires de l'Issue)" in sortie, (
            f"titre de section cadrage absent de la sortie -DryRun.\nsortie={sortie!r}"
        )
        assert COMMENTAIRE_CADRAGE in sortie, (
            f"commentaire de cadrage absent du gabarit.\nsortie={sortie!r}"
        )
        assert COMMENTAIRE_HORS_CADRAGE not in sortie, (
            f"commentaire hors cadrage transmis à tort au gabarit.\nsortie={sortie!r}"
        )
        print("PASS: commentaires de cadrage inclus, commentaire hors cadrage filtré")

        print("lancer_lane_dryrun_test: 3/3 OK")
    finally:
        shutil.rmtree(stub_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
