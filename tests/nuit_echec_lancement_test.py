"""#263 : tools/banc/nuit.sh s'arrête après DEUX échecs de lancement
consécutifs plutôt que de consommer tout le budget -Parties sur le même
craquement (nuit N0 du 02/09 : 4 parties/4 craquées au lancement, 0 tour
joué, la nuit avait quand même conclu « budget -Parties atteint »).

Utilise `-LancementCmd` (paramètre interne, non documenté côté opérateur,
même convention que `-RunDir`) pour forcer un échec de lancement
DÉTERMINISTE sans herdr/powershell réels — la commande donnée remplace
l'appel `powershell.exe .../lancer-banc-fumee.ps1`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from coderain.memory import Library  # noqa: E402

NUIT_SH = REPO_ROOT / "tools" / "banc" / "nuit.sh"


def find_bash():
    git = shutil.which("git")
    if git:
        cand = Path(git).parents[1] / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("bash")


BASH = find_bash()
assert BASH, "bash introuvable (Git for Windows le fournit)"


def main() -> int:
    assert NUIT_SH.exists(), f"script absent : {NUIT_SH}"

    tmp = Path(tempfile.mkdtemp(prefix="nuit-echec-lancement-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Echec Lancement Test", mode="rpg",
            premise="Save 100% synthétique — Issue #263, jamais de matériau réel.",
        )
        assert slug, "création de la save synthétique a échoué"

        run_dir = tmp / "run"

        env = {
            **os.environ,
            "SAVES_DIR": str(lib_root / "saves"),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        env = {k: v for k, v in env.items() if not k.startswith("GIT_")}

        # -Parties 4, mais la commande de lancement échoue TOUJOURS
        # (`exit 1`) — la nuit doit s'arrêter au 2e échec, pas consommer les
        # 4 parties du budget.
        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "4", "-Save", slug,
             "-RunDir", str(run_dir), "-LancementCmd", "exit 1"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert p.returncode == 6, (
            f"attendu code de sortie 6 (lancement impossible), reçu {p.returncode}\n"
            f"stdout={p.stdout}\nstderr={p.stderr}"
        )
        print("1) nuit.sh -LancementCmd 'exit 1' -Parties 4 : sortie 6")

        # Seulement partie-01 et partie-02 créées (arrêt au 2e échec) — PAS
        # partie-03/partie-04, budget non consommé au-delà.
        assert (run_dir / "partie-01").is_dir(), "partie-01 doit être créée (1er échec)"
        assert (run_dir / "partie-02").is_dir(), "partie-02 doit être créée (2e échec, arrêt)"
        assert not (run_dir / "partie-03").is_dir(), (
            "partie-03 ne doit PAS être créée — la nuit doit s'arrêter au 2e "
            "échec de lancement consécutif, pas consommer tout le budget."
        )
        print("2) arrêt après partie-02 : partie-03/partie-04 jamais lancées")

        for pnn in ("01", "02"):
            craquement = run_dir / f"partie-{pnn}" / "craquement-lancement-00.md"
            assert craquement.exists(), f"craquement de lancement absent : {craquement}"
        print("3) craquement-lancement-00.md écrit pour chaque partie échouée")

        nuit_md = run_dir / "nuit.md"
        assert nuit_md.exists(), f"nuit.md absent : {nuit_md}"
        contenu = nuit_md.read_text(encoding="utf-8")
        assert "lancement impossible" in contenu, (
            f"raison d'arrêt attendue 'lancement impossible' absente de nuit.md\n{contenu}"
        )
        assert "2 échecs de lancement consécutifs" in contenu, contenu
        print("4) nuit.md porte la raison d'arrêt 'lancement impossible (2 échecs ...)'")

        print("\nALL NUIT_ECHEC_LANCEMENT TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
