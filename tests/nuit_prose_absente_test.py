"""Issue #269 : tools/banc/nuit.sh craque `prose-absente-NN` (partie fermée,
suivante lancée, nuit PAS arrêtée) quand `tour-NN.md` apparaît sans section
« Prose du Narrateur » exploitable — plutôt que d'attendre indéfiniment un
`prose-NN.md` que le gabarit MJ ne spécifie pas d'écrire (constat du 02/09,
nuit N0 : 6 min de timeout par partie, zéro tour joué).

Utilise `-LancementCmd` (même convention que #263, tests/nuit_echec_lancement_test.py)
pour simuler, sans herdr/powershell réels, un MJ qui écrit tour-01.md SANS
section prose — déterministe, aucun agent réel lancé.
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

# Simule le lancement : imprime les deux lignes de pane que nuit.sh parse
# dans lancement.log, puis écrit tour-01.md SANS section « Prose du
# Narrateur » — reproduit un MJ qui n'a livré que le gabarit spécifié,
# jamais la prose séparée.
LANCEMENT_CMD_FAKE = (
    'echo "Pane MJ: fake-mj-pane"; '
    'echo "Pane joueur-banc: fake-joueur-pane"; '
    'printf "# tour 01\\n\\n## Visee du Director\\n\\nrien ici.\\n" '
    '> "$partie_dir/tour-01.md"; '
    'exit 0'
)


def main() -> int:
    assert NUIT_SH.exists(), f"script absent : {NUIT_SH}"

    tmp = Path(tempfile.mkdtemp(prefix="nuit-prose-absente-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Prose Absente Test", mode="rpg",
            premise="Save 100% synthétique — Issue #269, jamais de matériau réel.",
        )
        assert slug, "création de la save synthétique a échoué"

        run_dir = tmp / "run"

        env = {
            **os.environ,
            "SAVES_DIR": str(lib_root / "saves"),
            "NUIT_CONSERVER_SAVES_DIR": "1",  # #271, voir nuit_dryrun_test.py
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        env = {k: v for k, v in env.items() if not k.startswith("GIT_")}

        p = subprocess.run(
            [BASH, str(NUIT_SH), "-Parties", "1", "-Tours", "1", "-Save", slug,
             "-RunDir", str(run_dir), "-LancementCmd", LANCEMENT_CMD_FAKE],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert p.returncode == 0, (
            f"une seule partie craquée (prose-absente) reste sortie 0 (n'arrête pas "
            f"la nuit) — reçu {p.returncode}\nstdout={p.stdout}\nstderr={p.stderr}"
        )
        print("1) nuit.sh -Parties 1 avec tour-01.md sans prose : sortie 0 (nuit pas arrêtée)")

        partie_dir = run_dir / "partie-01"
        assert (partie_dir / "tour-01.md").exists(), "tour-01.md attendu (écrit par le fake)"
        assert not (partie_dir / "prose-01.md").exists(), (
            "prose-01.md ne doit PAS exister : extraction impossible (section absente)"
        )
        craquement = partie_dir / "craquement-prose-absente-01.md"
        assert craquement.exists(), f"craquement prose-absente absent : {craquement}"
        print("2) craquement-prose-absente-01.md écrit, prose-01.md jamais créé")

        resume = (partie_dir / "resume-run.md").read_text(encoding="utf-8")
        assert "raison_arret: craquement-prose-absente" in resume, resume
        assert "craquement-prose-absente-01.md" in resume, resume
        print("3) resume-run.md : raison_arret craquement-prose-absente, craquement listé")

        print("\nALL NUIT_PROSE_ABSENTE TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
