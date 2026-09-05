"""Issue #298 : tools/banc/fermer-workspace-banc.sh -- ferme tous les panes
d'un workspace herdr par label, jamais le workspace lui-même (garde
symétrique de circuit.sh nettoyer). Extrait de nuit.sh (finaliser_nuit) pour
être testable avec un faux `herdr` sur PATH, même discipline que
tests/lancer_banc_fumee_test.py.

1. Aucun workspace de ce label -> sortie 0, aucun `pane close` appelé (journal
   vide).
2. Workspace présent avec deux panes -> les deux `pane close` sont appelés
   (journal les liste), jamais un `workspace close` (aucune ligne "workspace"
   dans le journal des appels reçus par le faux herdr).
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "banc" / "fermer-workspace-banc.sh"

ENV_SANS_GIT = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def find_bash():
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


BASH = find_bash()
assert BASH, "bash introuvable (Git for Windows le fournit)"


def build_fake_herdr(tmp_root: Path, journal: Path, workspaces_json: str, panes_json: str) -> Path:
    """Faux `herdr` : répond à `workspace list` par $workspaces_json, à
    `pane list --workspace <id>` par $panes_json, journalise CHAQUE appel
    (argv complet, une ligne) dans $journal -- pour vérifier qu'aucun
    `workspace close` n'a jamais lieu."""
    bin_dir = tmp_root / "fake-bin"
    bin_dir.mkdir(parents=True)
    script = f"""#!/bin/bash
echo "$*" >> "{journal.as_posix()}"
if [ "$1" = "workspace" ] && [ "$2" = "list" ]; then
  echo '{workspaces_json}'
  exit 0
fi
if [ "$1" = "pane" ] && [ "$2" = "list" ]; then
  echo '{panes_json}'
  exit 0
fi
exit 0
"""
    herdr_path = bin_dir / "herdr"
    herdr_path.write_text(script, encoding="utf-8")
    herdr_path.chmod(0o755)
    return bin_dir


def run(fake_bin: Path, label: str):
    env = {**ENV_SANS_GIT, "PATH": f"{fake_bin}{os.pathsep}{ENV_SANS_GIT.get('PATH', '')}"}
    return subprocess.run(
        [BASH, str(SCRIPT), label],
        capture_output=True, timeout=30, env=env, encoding="utf-8", errors="replace",
    )


def main():
    assert SCRIPT.exists(), f"script absent : {SCRIPT}"

    tmp_root = Path(tempfile.mkdtemp(prefix="fermer-workspace-banc-test-"))
    try:
        # ------------------------------------------------------------
        # Cas 1 : aucun workspace de ce label -> sortie 0, rien fermé
        # ------------------------------------------------------------
        journal1 = tmp_root / "journal1.log"
        fake_bin1 = build_fake_herdr(
            tmp_root / "bin1", journal1,
            '{"result":{"workspaces":[{"label":"autre-chose","workspace_id":"w1"}]}}',
            '{"result":{"panes":[]}}',
        )
        p1 = run(fake_bin1, "banc-20260905")
        assert p1.returncode == 0, f"cas 1 : code 0 attendu, reçu {p1.returncode}\n{p1.stderr}"
        contenu1 = journal1.read_text(encoding="utf-8") if journal1.exists() else ""
        assert "close" not in contenu1, f"cas 1 : aucun close attendu ({contenu1!r})"
        print("PASS: cas 1 -- workspace absent, sortie 0, aucun pane fermé")

        # ------------------------------------------------------------
        # Cas 2 : workspace présent avec deux panes -> les deux fermés,
        # jamais un `workspace close`.
        # ------------------------------------------------------------
        journal2 = tmp_root / "journal2.log"
        fake_bin2 = build_fake_herdr(
            tmp_root / "bin2", journal2,
            '{"result":{"workspaces":[{"label":"banc-20260905","workspace_id":"w9"}]}}',
            '{"result":{"panes":[{"pane_id":"w9:p1"},{"pane_id":"w9:p2"}]}}',
        )
        p2 = run(fake_bin2, "banc-20260905")
        assert p2.returncode == 0, f"cas 2 : code 0 attendu, reçu {p2.returncode}\n{p2.stderr}"
        contenu2 = journal2.read_text(encoding="utf-8")
        assert "pane close w9:p1" in contenu2, f"cas 2 : close de w9:p1 attendu ({contenu2!r})"
        assert "pane close w9:p2" in contenu2, f"cas 2 : close de w9:p2 attendu ({contenu2!r})"
        assert "workspace close" not in contenu2, (
            f"cas 2 : le workspace lui-même ne doit JAMAIS être fermé de force (#298) ({contenu2!r})"
        )
        print("PASS: cas 2 -- les deux panes fermés, jamais le workspace lui-même")

        print("fermer_workspace_banc_test: 2/2 OK")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
