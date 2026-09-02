"""#263 : le point d'envoi de tools/lancer-banc-fumee.ps1 (deux sites,
MJ et joueur-banc) ne doit pas casser sur un gabarit rendu portant des
guillemets doubles, guillemets échappés, retours à la ligne ou une chaîne
qui ressemble à une option (`--option`).

Repro payée (nuit N0 du 02/09, #258 → #263) : #258 a ajouté au gabarit MJ un
exemple JSON avec des guillemets doubles ; le `&` natif de PowerShell 5.1
cassait l'échappement de l'unique argument passé à `herdr agent prompt`,
« unknown option » côté herdr, 4 parties/4 craquées au lancement, 0 tour
joué en nuit.

Ce test n'a pas besoin de `herdr`/`gh` réels : il extrait les fonctions
`ConvertTo-Win32Arg` / `Invoke-NativeCommand` du script (mêmes fonctions
que le point d'envoi utilise, I-385) et vérifie, via un vrai process
PowerShell qui lance un dumper d'argv Python, qu'un gabarit synthétique
contenant `"`, `\"`, retours à la ligne et `--option` traverse le point
d'envoi intact et en un seul argument.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "lancer-banc-fumee.ps1"

ARGDUMP_PY = textwrap.dedent("""\
    import json
    import sys
    print(json.dumps(sys.argv[1:]))
    """)

# Extraction textuelle des deux fonctions (mêmes bornes que
# tests/lancer_lane_argv_test.py, adaptées aux marqueurs de ce script) — pas
# de dot-sourcing du script entier (effets de bord dès le parsing des
# paramètres obligatoires en tête de fichier).
HARNESS_TEMPLATE = textwrap.dedent("""\
    $ErrorActionPreference = 'Stop'
    $src = Get-Content -Raw '{script}'
    $start = $src.IndexOf('function ConvertTo-Win32Arg')
    $end = $src.IndexOf('$RepoRoot = (git -C $PSScriptRoot')
    if ($start -lt 0 -or $end -lt 0) {{ throw "extraction des fonctions a echoue" }}
    Invoke-Expression $src.Substring($start, $end - $start)

    Invoke-NativeCommand -FilePath 'python' -Arguments @(
        '{argdump}', $env:BANC_TEST_GABARIT, 'next'
    )
    exit $LASTEXITCODE
    """)


def find_powershell():
    for name in ("powershell", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return None


def run_case(ps_exe, argdump_path, gabarit):
    harness = HARNESS_TEMPLATE.format(
        script=str(SCRIPT).replace("'", "''"),
        argdump=str(argdump_path).replace("'", "''"),
    )
    with tempfile.NamedTemporaryFile(
        "w", suffix=".ps1", delete=False, encoding="utf-8"
    ) as f:
        f.write(harness)
        harness_path = f.name
    try:
        full_env = {**os.environ, "BANC_TEST_GABARIT": gabarit}
        p = subprocess.run(
            [ps_exe, "-NoProfile", "-File", harness_path],
            capture_output=True, text=True, timeout=60, env=full_env,
        )
        return p
    finally:
        Path(harness_path).unlink(missing_ok=True)


def main():
    ps_exe = find_powershell()
    assert ps_exe, "powershell/pwsh introuvable — requis pour ce test (CI: windows-latest)"
    assert SCRIPT.exists(), f"script absent : {SCRIPT}"

    tmp = Path(tempfile.mkdtemp(prefix="lancer-banc-fumee-argv-"))
    try:
        argdump_path = tmp / "argdump.py"
        argdump_path.write_text(ARGDUMP_PY, encoding="utf-8")

        # Gabarit synthétique reproduisant la famille de la casse #258 :
        # guillemets doubles (exemple JSON), guillemets déjà échappés,
        # retours à la ligne, et un jeton qui ressemble à une option herdr
        # (le symptôme observé : « unknown option: champ »).
        cases = [
            ("guillemets pairs (exemple JSON #258)",
             '{"champ": "valeur", "autre": "deux"}'),
            ("guillemets impairs", 'Elle dit "Attends -- fin'),
            ("guillemets deja echappes", r'texte \"deja echappe\" ici'),
            ("backslash + guillemet en fin", r'chemin\avec\"quote'),
            ("retours a la ligne + option", 'ligne1\n--option valeur\nligne3 "cite"'),
        ]

        for label, gabarit in cases:
            p = run_case(ps_exe, argdump_path, gabarit)
            assert p.returncode == 0, (
                f"{label}: le harnais a echoue (code {p.returncode})\n"
                f"stdout={p.stdout}\nstderr={p.stderr}"
            )
            lines = json.loads(p.stdout.strip())
            assert lines == [gabarit, "next"], (
                f"{label}: argv reçu ne correspond pas au gabarit envoyé\n"
                f"attendu : {[gabarit, 'next']}\n"
                f"recu    : {lines}\n"
                f"stdout={p.stdout}\nstderr={p.stderr}"
            )
            print(f"PASS: {label}")

        print("lancer_banc_fumee_argv_test: 5/5 OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
