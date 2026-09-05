"""Issue #298 : tools/lancer-banc-fumee.ps1 -- les deux panes MJ/joueur
naissent DANS un workspace herdr dédié (-WorkspaceLabel), jamais depuis
`herdr pane current` : craquement du 05/09, panes ouverts dans le workspace
d'une lane focalisée juste avant, fermés avec elle par `circuit.sh nettoyer`
en pleine partie.

Même infrastructure que tests/lancer_banc_fumee_test.py (dépôt Git jetable,
faux `herdr` en tête de PATH, exécution réelle -- pas de -DryRun, le
montage du workspace ne tourne que dans ce chemin) :

1. Workspace absent (label neuf) : `herdr workspace create --no-focus` est
   appelé, jamais `herdr pane current`, et les deux `pane split` portent
   `--no-focus`.
2. Workspace déjà présent (même label) : `herdr workspace create` n'est PAS
   appelé (réutilisation), le premier split part du pane déjà présent dans
   ce workspace (`herdr pane list --workspace <id>`), jamais `pane current`.

Le faux `herdr` journalise CHAQUE appel (argv complet, une ligne par appel)
dans un fichier -- les assertions portent sur ce journal, jamais sur un
minutage ou une inspection de processus.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_REEL = REPO_ROOT / "tools" / "lancer-banc-fumee.ps1"
GABARIT_MJ_REEL = REPO_ROOT / "tools" / "prompts" / "banc-mj.md"
GABARIT_JOUEUR_REEL = REPO_ROOT / "tools" / "prompts" / "banc-joueur.md"
LISTE_BLANCHE_REEL = REPO_ROOT / "tools" / "banc" / "liste-blanche.ps1"
REFUS_HAIKU_AUTO_REEL = REPO_ROOT / "tools" / "refus-haiku-auto.ps1"

ENV_SANS_GIT = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def find_powershell():
    for name in ("powershell", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return None


def build_repo_jetable(tmp_root: Path, nom: str) -> Path:
    repo = tmp_root / nom
    (repo / "tools" / "prompts").mkdir(parents=True)
    (repo / "tools" / "banc").mkdir(parents=True)
    shutil.copy(SCRIPT_REEL, repo / "tools" / "lancer-banc-fumee.ps1")
    shutil.copy(LISTE_BLANCHE_REEL, repo / "tools" / "banc" / "liste-blanche.ps1")
    shutil.copy(REFUS_HAIKU_AUTO_REEL, repo / "tools" / "refus-haiku-auto.ps1")
    for nom_gabarit in ("banc-mj.md", "banc-joueur.md"):
        (repo / "tools" / "prompts" / nom_gabarit).write_text(
            "gabarit synthétique de test -- {{SAVE}} {{TOURS}} {{SESSION_TOUR}} {{JOURNAL_DIR}}\n",
            encoding="utf-8",
        )
    subprocess.run(["git", "init", "-q"], cwd=repo, env=ENV_SANS_GIT, check=True)
    return repo


# Faux `herdr` (cas 1, workspace absent) : `workspace list` -> aucun résultat
# ; `workspace create` -> workspace + pane ancre neufs ; `pane` (split) ->
# pane_id générique. Journalise chaque appel (argv complet) dans %JOURNAL%.
FAKE_HERDR_ABSENT_CMD = (
    "@echo off\r\n"
    "echo %* >> \"%JOURNAL%\"\r\n"
    'if "%~1"=="workspace" if "%~2"=="list" (\r\n'
    '  echo {"result":{"workspaces":[]}}\r\n'
    "  exit /b 0\r\n"
    ")\r\n"
    'if "%~1"=="workspace" if "%~2"=="create" (\r\n'
    '  echo {"result":{"workspace":{"workspace_id":"w-neuf"},"root_pane":{"pane_id":"w-neuf:p1"}}}\r\n'
    "  exit /b 0\r\n"
    ")\r\n"
    'if "%~1"=="pane" (\r\n'
    '  echo {"result":{"pane":{"pane_id":"pane-test"}}}\r\n'
    "  exit /b 0\r\n"
    ")\r\n"
    "exit /b 0\r\n"
)

# Faux `herdr` (cas 2, workspace déjà présent, label "banc-test-existant") :
# `workspace list` -> UN workspace de ce label (id "w-existant") ; `pane
# list --workspace w-existant` -> un pane déjà là (id "w-existant:p1") ;
# `pane` (split) -> pane_id générique. `workspace create` ne devrait JAMAIS
# être appelé dans ce cas -- s'il l'était, il répondrait quand même (pour ne
# pas faire planter le script si le test échoue) mais l'assertion sur le
# journal le détecterait.
FAKE_HERDR_PRESENT_CMD = (
    "@echo off\r\n"
    "echo %* >> \"%JOURNAL%\"\r\n"
    'if "%~1"=="workspace" if "%~2"=="list" (\r\n'
    '  echo {"result":{"workspaces":[{"label":"banc-test-existant","workspace_id":"w-existant"}]}}\r\n'
    "  exit /b 0\r\n"
    ")\r\n"
    'if "%~1"=="workspace" if "%~2"=="create" (\r\n'
    '  echo {"result":{"workspace":{"workspace_id":"w-ne-devrait-pas-exister"},"root_pane":{"pane_id":"w-x:p1"}}}\r\n'
    "  exit /b 0\r\n"
    ")\r\n"
    'if "%~1"=="pane" if "%~2"=="list" (\r\n'
    '  echo {"result":{"panes":[{"pane_id":"w-existant:p1"}]}}\r\n'
    "  exit /b 0\r\n"
    ")\r\n"
    'if "%~1"=="pane" (\r\n'
    '  echo {"result":{"pane":{"pane_id":"pane-test"}}}\r\n'
    "  exit /b 0\r\n"
    ")\r\n"
    "exit /b 0\r\n"
)


def build_fake_herdr(tmp_root: Path, nom: str, cmd: str) -> Path:
    bin_dir = tmp_root / nom
    bin_dir.mkdir()
    (bin_dir / "herdr.cmd").write_text(cmd, encoding="utf-8")
    return bin_dir


def run_reel(ps_exe, script_path: Path, fake_bin: Path, journal: Path, workspace_label: str):
    env = {
        **ENV_SANS_GIT,
        "PATH": f"{fake_bin}{os.pathsep}{ENV_SANS_GIT.get('PATH', '')}",
        "JOURNAL": str(journal),
    }
    cmd = [
        ps_exe, "-NoProfile", "-File", str(script_path),
        "-SessionTour", "banc-test-tour", "-Save", "banc-test-save",
        "-WorkspaceLabel", workspace_label,
    ]
    return subprocess.run(
        cmd, capture_output=True, timeout=60, env=env,
        encoding="utf-8", errors="replace",
    )


def main():
    ps_exe = find_powershell()
    assert ps_exe, "powershell/pwsh introuvable -- requis pour ce test (CI: windows-latest)"
    assert SCRIPT_REEL.exists(), f"script absent : {SCRIPT_REEL}"

    tmp_root = Path(tempfile.mkdtemp(prefix="lancer-banc-fumee-workspace-test-"))
    try:
        # ------------------------------------------------------------
        # Cas 1 : workspace absent -> `workspace create --no-focus`,
        # jamais `pane current`, les deux splits portent `--no-focus`.
        # ------------------------------------------------------------
        repo1 = build_repo_jetable(tmp_root, "repo-cas1")
        fake_bin1 = build_fake_herdr(tmp_root, "bin-cas1", FAKE_HERDR_ABSENT_CMD)
        journal1 = tmp_root / "journal1.log"
        p1 = run_reel(ps_exe, repo1 / "tools" / "lancer-banc-fumee.ps1", fake_bin1, journal1, "banc-test-neuf")
        assert p1.returncode == 0, (
            f"cas 1 : code de sortie attendu 0, reçu {p1.returncode}\n"
            f"stdout={p1.stdout}\nstderr={p1.stderr}"
        )
        appels1 = journal1.read_text(encoding="utf-8") if journal1.exists() else ""
        assert "pane current" not in appels1, f"cas 1 : 'pane current' ne doit JAMAIS être appelé (#298) ({appels1!r})"
        assert "workspace create" in appels1, f"cas 1 : 'workspace create' attendu (workspace absent) ({appels1!r})"
        lignes_create = [l for l in appels1.splitlines() if l.startswith("workspace create")]
        assert lignes_create and "--no-focus" in lignes_create[0], (
            f"cas 1 : 'workspace create' doit porter --no-focus ({lignes_create!r})"
        )
        assert "banc-test-neuf" in lignes_create[0], f"cas 1 : le label demandé doit être transmis ({lignes_create!r})"
        lignes_split = [l for l in appels1.splitlines() if l.startswith("pane split")]
        assert len(lignes_split) == 2, f"cas 1 : deux splits attendus (MJ + joueur) ({lignes_split!r})"
        assert all("--no-focus" in l for l in lignes_split), (
            f"cas 1 : les deux splits doivent porter --no-focus (#298) ({lignes_split!r})"
        )
        print("PASS: cas 1 -- workspace absent : créé --no-focus, jamais 'pane current', splits --no-focus")

        # ------------------------------------------------------------
        # Cas 2 : workspace déjà présent -> réutilisé, `workspace create`
        # jamais appelé, premier split part du pane déjà là.
        # ------------------------------------------------------------
        repo2 = build_repo_jetable(tmp_root, "repo-cas2")
        fake_bin2 = build_fake_herdr(tmp_root, "bin-cas2", FAKE_HERDR_PRESENT_CMD)
        journal2 = tmp_root / "journal2.log"
        p2 = run_reel(ps_exe, repo2 / "tools" / "lancer-banc-fumee.ps1", fake_bin2, journal2, "banc-test-existant")
        assert p2.returncode == 0, (
            f"cas 2 : code de sortie attendu 0, reçu {p2.returncode}\n"
            f"stdout={p2.stdout}\nstderr={p2.stderr}"
        )
        appels2 = journal2.read_text(encoding="utf-8") if journal2.exists() else ""
        assert "pane current" not in appels2, f"cas 2 : 'pane current' ne doit JAMAIS être appelé (#298) ({appels2!r})"
        assert "workspace create" not in appels2, (
            f"cas 2 : workspace déjà présent -- 'workspace create' ne doit PAS être appelé ({appels2!r})"
        )
        lignes_split2 = [l for l in appels2.splitlines() if l.startswith("pane split")]
        assert len(lignes_split2) == 2, f"cas 2 : deux splits attendus (MJ + joueur) ({lignes_split2!r})"
        assert "w-existant:p1" in lignes_split2[0], (
            f"cas 2 : le premier split doit partir du pane déjà présent du workspace réutilisé ({lignes_split2!r})"
        )
        assert all("--no-focus" in l for l in lignes_split2), (
            f"cas 2 : les deux splits doivent porter --no-focus (#298) ({lignes_split2!r})"
        )
        print("PASS: cas 2 -- workspace présent : réutilisé, jamais recréé, split depuis le pane existant")

        print("lancer_banc_fumee_workspace_test: 2/2 OK")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
