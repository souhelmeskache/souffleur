"""Issue #265 : les lanes et revues démarrent en `--permission-mode auto` et
plus jamais en `bypassPermissions` — l'écran d'acceptation bloquant que ce
dernier affichait au tout premier lancement dans un worktree neuf gelait
tout démarrage sans humain devant l'écran, et le filet censé y répondre seul
(détection « Yes, I accept » + touche 2 + Entrée) ne fonctionnait pas
(constat du 02/09 : agent tué au lieu de démarré, cf. corps de l'Issue #265).

Ce test n'a pas besoin de `herdr` réel : il extrait la fonction
`Start-AgentClaude` du script (par extraction textuelle, même technique que
`lancer_lane_argv_test.py`) et l'exerce contre un faux `herdr` (script
PowerShell) qui journalise l'argv reçu par `agent start` puis répond succès
à `agent start` et `agent wait` — exactement les deux appels que fait la
fonction.
"""
import json
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "lancer-lane.ps1"

# Faux herdr : journalise l'argv de chaque appel dans un fichier JSON lines,
# répond succès (exit 0) systématiquement — Start-AgentClaude ne doit pas
# emprunter le chemin d'erreur pour qu'on puisse lire l'argv qu'elle a émis.
FAKE_HERDR_TEMPLATE = textwrap.dedent("""\
    param([Parameter(ValueFromRemainingArguments=$true)] $Args)
    $line = ($Args -join ' | ')
    Add-Content -Path '{log}' -Value $line
    exit 0
    """)

HARNESS_TEMPLATE = textwrap.dedent("""\
    $ErrorActionPreference = 'Stop'
    $src = Get-Content -Raw '{script}'
    $start = $src.IndexOf('function ConvertTo-Win32Arg')
    $end = $src.IndexOf('$RepoRoot = (git -C $PSScriptRoot')
    if ($start -lt 0 -or $end -lt 0) {{ throw "extraction des fonctions a echoue" }}
    Invoke-Expression $src.Substring($start, $end - $start)

    Start-AgentClaude -HerdrExe '{fake_herdr}' -AgentName 'agent-test' -PaneId 'pane-test' -Modele 'sonnet' -Effort 'medium'
    exit 0
    """)


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

    tmp = Path(tempfile.mkdtemp(prefix="lancer-lane-permmode-"))
    try:
        log_path = tmp / "fake-herdr.log"
        log_path.write_text("", encoding="utf-8")
        fake_herdr_path = tmp / "fake-herdr.ps1"
        fake_herdr_path.write_text(
            FAKE_HERDR_TEMPLATE.format(log=str(log_path).replace("'", "''")),
            encoding="utf-8",
        )

        harness = HARNESS_TEMPLATE.format(
            script=str(SCRIPT).replace("'", "''"),
            fake_herdr=str(fake_herdr_path).replace("'", "''"),
        )
        harness_path = tmp / "harness.ps1"
        harness_path.write_text(harness, encoding="utf-8")

        p = subprocess.run(
            [ps_exe, "-NoProfile", "-File", str(harness_path)],
            capture_output=True, text=True, timeout=60,
        )
        assert p.returncode == 0, (
            f"le harnais a echoue (code {p.returncode})\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )

        calls = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        start_calls = [c for c in calls if c.startswith("agent | start")]
        assert len(start_calls) == 1, f"attendu un seul appel 'agent start', reçu : {calls}"
        start_argv = start_calls[0]

        assert "--permission-mode | auto" in start_argv, (
            f"'agent start' doit être lancé avec --permission-mode auto : {start_argv}"
        )
        assert "bypassPermissions" not in start_argv, (
            f"'agent start' ne doit plus jamais porter bypassPermissions : {start_argv}"
        )

        wait_calls = [c for c in calls if c.startswith("agent | wait")]
        assert len(wait_calls) == 1, f"attendu un seul appel 'agent wait' (idle), reçu : {calls}"

        print("lancer_lane_permission_mode_test: OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
