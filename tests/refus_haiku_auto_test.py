"""Issue #276 (cadrage complémentaire, 03/09) : `--permission-mode auto`
n'existe pas pour Haiku — Claude Code y retombe EN SILENCE en mode manuel,
et un agent de nuit gèle à la première question posée à personne. Refus
nommé, testé à deux niveaux :

1. La fonction partagée `Assure-ModeAutoCompatibleAvecModele`
   (`tools/refus-haiku-auto.ps1`) directement, sur les quatre combinaisons
   qui comptent (refus haiku+auto ; passage sonnet+auto, haiku+acceptEdits,
   alias complet `claude-haiku-...`+auto).
2. `tools/lancer-lane.ps1` (`Start-AgentClaude`, toujours `--permission-mode
   auto`) : un lancement Modele=haiku est refusé AVANT tout `herdr agent
   start` — jamais un `agent start` émis.

`tools/lancer-banc-fumee.ps1` appelle la même fonction mais avec le mode
toujours `acceptEdits` (jamais `auto`, voir tools/banc/README.md, § Liste
blanche) : cette combinaison passe toujours, déjà couverte par les tests
existants (tests/lancer_banc_fumee_test.py) qui lancent le script réel avec
`-ModeleJoueur haiku` sans jamais échouer.
"""
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REFUS_HAIKU_AUTO = REPO_ROOT / "tools" / "refus-haiku-auto.ps1"
LANCER_LANE = REPO_ROOT / "tools" / "lancer-lane.ps1"

FONCTION_HARNESS_TEMPLATE = textwrap.dedent("""\
    $ErrorActionPreference = 'Stop'
    . '{refus_haiku_auto}'
    Assure-ModeAutoCompatibleAvecModele -Modele '{modele}' -PermissionMode '{mode}'
    exit 0
    """)

FAKE_HERDR_TEMPLATE = textwrap.dedent("""\
    param([Parameter(ValueFromRemainingArguments=$true)] $Args)
    Add-Content -Path '{log}' -Value ($Args -join ' | ')
    exit 0
    """)

START_AGENT_HARNESS_TEMPLATE = textwrap.dedent("""\
    $ErrorActionPreference = 'Stop'
    $src = Get-Content -Raw '{script}'
    $start = $src.IndexOf('function ConvertTo-Win32Arg')
    $end = $src.IndexOf('$RepoRoot = (git -C $PSScriptRoot')
    if ($start -lt 0 -or $end -lt 0) {{ throw "extraction des fonctions a echoue" }}
    Invoke-Expression $src.Substring($start, $end - $start)
    . '{refus_haiku_auto}'

    Start-AgentClaude -HerdrExe '{fake_herdr}' -AgentName 'agent-test' -PaneId 'pane-test' -Modele '{modele}' -Effort 'medium'
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
    assert REFUS_HAIKU_AUTO.exists(), f"script absent : {REFUS_HAIKU_AUTO}"
    assert LANCER_LANE.exists(), f"script absent : {LANCER_LANE}"

    tmp = Path(tempfile.mkdtemp(prefix="refus-haiku-auto-test-"))
    try:
        def run_fonction(modele: str, mode: str) -> subprocess.CompletedProcess:
            harness = FONCTION_HARNESS_TEMPLATE.format(
                refus_haiku_auto=str(REFUS_HAIKU_AUTO).replace("'", "''"),
                modele=modele.replace("'", "''"),
                mode=mode.replace("'", "''"),
            )
            harness_path = tmp / f"fn-{modele}-{mode}.ps1"
            harness_path.write_text(harness, encoding="utf-8")
            return subprocess.run(
                [ps_exe, "-NoProfile", "-File", str(harness_path)],
                capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace",
            )

        # --- 1. la fonction seule -------------------------------------------
        p = run_fonction("haiku", "auto")
        assert p.returncode != 0, f"haiku+auto doit être refusé : {p.stdout}\n{p.stderr}"
        assert "REFUS" in p.stderr and "auto" in p.stderr, p.stderr
        print("1) Assure-ModeAutoCompatibleAvecModele haiku+auto : REFUS nommé")

        p = run_fonction("claude-haiku-4-5-20251001", "auto")
        assert p.returncode != 0, f"alias complet haiku+auto doit être refusé : {p.stdout}\n{p.stderr}"
        print("2) alias complet (identifiant Haiku) + auto : REFUS nommé aussi")

        p = run_fonction("sonnet", "auto")
        assert p.returncode == 0, f"sonnet+auto doit passer : {p.stdout}\n{p.stderr}"
        print("3) sonnet+auto : passe")

        p = run_fonction("haiku", "acceptEdits")
        assert p.returncode == 0, f"haiku+acceptEdits doit passer : {p.stdout}\n{p.stderr}"
        print("4) haiku+acceptEdits : passe (mode du banc)")

        # --- 2. lancer-lane.ps1 (Start-AgentClaude, toujours --permission-mode
        # auto) : Modele=haiku refusé AVANT tout `herdr agent start` ----------
        log_path = tmp / "fake-herdr.log"
        log_path.write_text("", encoding="utf-8")
        fake_herdr_path = tmp / "fake-herdr.ps1"
        fake_herdr_path.write_text(
            FAKE_HERDR_TEMPLATE.format(log=str(log_path).replace("'", "''")),
            encoding="utf-8",
        )
        harness = START_AGENT_HARNESS_TEMPLATE.format(
            script=str(LANCER_LANE).replace("'", "''"),
            refus_haiku_auto=str(REFUS_HAIKU_AUTO).replace("'", "''"),
            fake_herdr=str(fake_herdr_path).replace("'", "''"),
            modele="haiku",
        )
        harness_path = tmp / "start-agent-haiku.ps1"
        harness_path.write_text(harness, encoding="utf-8")
        p = subprocess.run(
            [ps_exe, "-NoProfile", "-File", str(harness_path)],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
        assert p.returncode != 0, (
            f"lancer-lane.ps1 Start-AgentClaude Modele=haiku doit être refusé : "
            f"{p.stdout}\n{p.stderr}"
        )
        appels = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert not any(a.startswith("agent | start") for a in appels), (
            f"aucun 'herdr agent start' ne doit être émis avant le refus : {appels}"
        )
        print("5) lancer-lane.ps1 Start-AgentClaude Modele=haiku : REFUS avant tout "
              "'herdr agent start' (jamais émis)")

        print("\nALL REFUS_HAIKU_AUTO TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
