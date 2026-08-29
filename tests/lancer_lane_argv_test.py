"""I-385 (Issue #122) : le corps d'une issue injecté dans le prompt de
tools/lancer-lane.ps1 ne doit plus casser l'envoi quand il porte des
guillemets doubles (ou tout autre caractère d'interprétation shell).

Repro payée (28/08, issue #34) : un corps d'issue avec des guillemets doubles
littéraux (convention de dialogue D-092) faisait éclater l'argument PowerShell
avant d'atteindre `herdr agent prompt`, envoyant un prompt tronqué/faux —
« unknown option » côté shell, lane démarrée sans consigne exploitable.

Ce test n'a pas besoin de `herdr`/`gh` réels : il extrait les fonctions
`ConvertTo-Win32Arg` / `Invoke-NativeCommand` du script (mêmes fonctions que
la lane utilise pour envoyer le prompt) et vérifie, via un vrai process
PowerShell qui lance un dumper d'argv Python, qu'un corps contenant des
guillemets doubles arrive intact et en un seul argument de l'autre côté —
la régression concrète de l'issue #34.
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
SCRIPT = REPO_ROOT / "tools" / "lancer-lane.ps1"

# Dumper d'argv minimal : un process externe réel (comme herdr.exe), pour
# vérifier ce qui arrive vraiment en argv côté receveur, pas ce que
# PowerShell *pense* avoir envoyé.
ARGDUMP_PY = textwrap.dedent("""\
    import json
    import sys
    print(json.dumps(sys.argv[1:]))
    """)

# Harnais PowerShell : recharge les deux fonctions du script sous test par
# extraction textuelle (pas de dot-sourcing du script entier — il a des
# effets de bord dès le chargement des paramètres/gardes en tête de
# fichier), puis les exerce exactement comme les deux sites d'appel
# `agent prompt` du script (Issue et Revue).
HARNESS_TEMPLATE = textwrap.dedent("""\
    $ErrorActionPreference = 'Stop'
    $src = Get-Content -Raw '{script}'
    $start = $src.IndexOf('function ConvertTo-Win32Arg')
    $end = $src.IndexOf('$RepoRoot = (git -C $PSScriptRoot')
    if ($start -lt 0 -or $end -lt 0) {{ throw "extraction des fonctions a echoue" }}
    Invoke-Expression $src.Substring($start, $end - $start)

    Invoke-NativeCommand -FilePath 'python' -Arguments @(
        '{argdump}', $env:LANE_TEST_BODY, 'next'
    )
    exit $LASTEXITCODE
    """)


def find_powershell():
    for name in ("powershell", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return None


def run_case(ps_exe, argdump_path, body):
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
        full_env = {**os.environ, "LANE_TEST_BODY": body}
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

    tmp = Path(tempfile.mkdtemp(prefix="lancer-lane-argv-"))
    try:
        argdump_path = tmp / "argdump.py"
        argdump_path.write_text(ARGDUMP_PY, encoding="utf-8")

        cases = [
            ("guillemets pairs", 'Elle dit "Bonjour" et "Au revoir"'),
            ("guillemets impairs (repro #34)", 'Elle dit "Attends -- fin'),
            ("guillemet en fin de chaine", 'dernier mot"'),
            ("backslash + guillemet", r'chemin\avec\"quote'),
            ("multiligne + guillemets", 'ligne1\nligne2 "avec citation"\nligne3'),
        ]

        for label, body in cases:
            p = run_case(ps_exe, argdump_path, body)
            assert p.returncode == 0, (
                f"{label}: le harnais a echoue (code {p.returncode})\n"
                f"stdout={p.stdout}\nstderr={p.stderr}"
            )
            lines = json.loads(p.stdout.strip())
            # Le corps doit arriver EN UN SEUL argv (pas éclaté), intact,
            # suivi du témoin 'next' — la régression de l'issue #34 était
            # justement un éclatement en plusieurs argv avec guillemets
            # perdus/déplacés.
            assert lines == [body, "next"], (
                f"{label}: argv reçu ne correspond pas au corps envoyé\n"
                f"attendu : {[body, 'next']}\n"
                f"recu    : {lines}\n"
                f"stdout={p.stdout}\nstderr={p.stderr}"
            )
            print(f"PASS: {label}")

        print("lancer_lane_argv_test: 5/5 OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
