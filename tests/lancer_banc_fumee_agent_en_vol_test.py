"""Issue #271 : tools/lancer-banc-fumee.ps1 -- refus NOMMÉ si `banc-mj` ou
`banc-joueur` est déjà en vol (nuit N0 02/09 : un `banc-joueur` survivant
faisait échouer `herdr agent start` sur la partie suivante avec un « échec
de herdr agent start » muet, aucune indication de la cause).

Même infrastructure que tests/lancer_banc_fumee_test.py (dépôt Git jetable,
faux `herdr` en tête de PATH, jamais réellement lancé en -DryRun) -- le faux
`herdr` répond ici à `agent list` par un agent `banc-joueur` déjà en vol,
pour vérifier que le refus nommé est posé AVANT tout `pane split`/`agent
start`, y compris en -DryRun (le refus doit être testable sans rien
lancer)."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_REEL = REPO_ROOT / "tools" / "lancer-banc-fumee.ps1"
GABARIT_MJ_REEL = REPO_ROOT / "tools" / "prompts" / "banc-mj.md"
GABARIT_JOUEUR_REEL = REPO_ROOT / "tools" / "prompts" / "banc-joueur.md"
LISTE_BLANCHE_REEL = REPO_ROOT / "tools" / "banc" / "liste-blanche.ps1"

ENV_SANS_GIT = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

# Répond à `agent list` par un `banc-joueur` déjà en vol sur le pane
# "w1:p2" ; toute autre sous-commande réussit trivialement (code 0), comme
# le faux herdr minimal de lancer_banc_fumee_test.py.
FAKE_HERDR_CMD = (
    "@echo off\r\n"
    'if "%~1"=="agent" if "%~2"=="list" (\r\n'
    '  echo {"result":{"agents":[{"name":"banc-joueur","pane_id":"w1:p2"}]}}\r\n'
    "  exit /b 0\r\n"
    ")\r\n"
    "exit /b 0\r\n"
)


def find_powershell():
    for name in ("powershell", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return None


def build_repo_jetable(tmp_root: Path) -> Path:
    repo = tmp_root / "repo-jetable"
    (repo / "tools" / "prompts").mkdir(parents=True)
    (repo / "tools" / "banc").mkdir(parents=True)
    shutil.copy(SCRIPT_REEL, repo / "tools" / "lancer-banc-fumee.ps1")
    shutil.copy(LISTE_BLANCHE_REEL, repo / "tools" / "banc" / "liste-blanche.ps1")
    shutil.copy(GABARIT_MJ_REEL, repo / "tools" / "prompts" / "banc-mj.md")
    shutil.copy(GABARIT_JOUEUR_REEL, repo / "tools" / "prompts" / "banc-joueur.md")
    subprocess.run(["git", "init", "-q"], cwd=repo, env=ENV_SANS_GIT, check=True)
    return repo


def main():
    ps_exe = find_powershell()
    assert ps_exe, "powershell/pwsh introuvable -- requis pour ce test (CI: windows-latest)"
    assert SCRIPT_REEL.exists(), f"script absent : {SCRIPT_REEL}"

    tmp_root = Path(tempfile.mkdtemp(prefix="lancer-banc-fumee-agent-en-vol-test-"))
    try:
        repo = build_repo_jetable(tmp_root)
        script_path = repo / "tools" / "lancer-banc-fumee.ps1"

        bin_dir = tmp_root / "fake-bin"
        bin_dir.mkdir()
        (bin_dir / "herdr.cmd").write_text(FAKE_HERDR_CMD, encoding="utf-8")

        env = {**ENV_SANS_GIT, "PATH": f"{bin_dir}{os.pathsep}{ENV_SANS_GIT.get('PATH', '')}"}
        cmd = [
            ps_exe, "-NoProfile", "-File", str(script_path),
            "-SessionTour", "banc-test-tour", "-Save", "banc-test-save",
            "-DryRun",
        ]
        p = subprocess.run(
            cmd, capture_output=True, timeout=60, env=env,
            encoding="utf-8", errors="replace",
        )
        assert p.returncode != 0, (
            f"refus attendu (agent banc-joueur déjà en vol) : code de sortie non nul, "
            f"reçu {p.returncode}\nstdout={p.stdout}\nstderr={p.stderr}"
        )
        sortie = p.stdout + p.stderr
        assert "banc-joueur" in sortie, f"message de refus attendu nommant l'agent : {sortie}"
        assert "w1:p2" in sortie, f"message de refus attendu nommant le pane : {sortie}"
        assert "DryRun" not in p.stdout, (
            f"le refus doit avoir lieu AVANT l'affichage du montage -DryRun : {p.stdout}"
        )
        print("PASS: refus nommé (agent + pane) quand banc-joueur est déjà en vol, avant tout montage")

        print("lancer_banc_fumee_agent_en_vol_test: 1/1 OK")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
