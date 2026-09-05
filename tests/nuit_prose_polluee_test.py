"""Issue #295 : tools/banc/nuit.sh craque nommément `prose-polluee-NN`
(partie fermée, suivante lancée, nuit PAS arrêtée) quand `prose-NN.md`,
écrit directement par le MJ (voie fichier, étape 8 du gabarit), fuite du
matériau que le zéro-spoiler (D-219) interdit au joueur — ici une mention
explicite du Director, à côté des cas titre markdown / bloc de code déjà
couverts par tests/arbitrer_prose_test.py au niveau unitaire.

Utilise `-LancementCmd` (même convention que #269,
tests/nuit_prose_absente_test.py / tests/nuit_prose_voie_fichier_test.py).
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

# prose-01.md écrit directement par le MJ, mais fuite une mention du
# Director -- jamais de la prose pure.
LANCEMENT_CMD_FAKE = (
    'echo "Pane MJ: fake-mj-pane"; '
    'echo "Pane joueur-banc: fake-joueur-pane"; '
    'printf "# tour 01\\n\\nrenvoi vers prose-01.md.\\n" > "$partie_dir/tour-01.md"; '
    'printf "Le Director a decide que la nuit tombait sur le chateau.\\n" '
    '> "$partie_dir/prose-01.md"; '
    'python -c "import os,sys; f=sys.argv[1]; os.utime(f, (9999999999, 9999999999))" '
    '"$partie_dir/prose-01.md"; '
    'exit 0'
)


def main() -> int:
    assert NUIT_SH.exists(), f"script absent : {NUIT_SH}"

    tmp = Path(tempfile.mkdtemp(prefix="nuit-prose-polluee-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Prose Polluee Test", mode="rpg",
            premise="Save 100% synthétique — Issue #295, jamais de matériau réel.",
        )
        assert slug, "création de la save synthétique a échoué"
        (lib.saves.dir(slug) / "module.json").write_text(
            '{"partition": "/dev/null/partition-factice", '
            '"titre": "Module factice de test"}', encoding="utf-8")
        (lib.saves.dir(slug) / "locations.md").write_text(
            (lib.saves.dir(slug) / "locations.md").read_text(encoding="utf-8")
            + "\n## Lieu factice  {#lieu-factice}\nimportance: 3\n\n"
              "Un lieu 100% synthétique.\n",
            encoding="utf-8")

        run_dir = tmp / "run"

        env = {
            **os.environ,
            "SAVES_DIR": str(lib_root / "saves"),
            "NUIT_CONSERVER_SAVES_DIR": "1",
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
            f"une seule partie craquée (prose-polluee) reste sortie 0 (n'arrête "
            f"pas la nuit) — reçu {p.returncode}\nstdout={p.stdout}\nstderr={p.stderr}"
        )
        print("1) nuit.sh -Parties 1 avec prose-01.md pollué (mention Director) : sortie 0")

        partie_dir = run_dir / "partie-01"
        craquement = partie_dir / "craquement-prose-polluee-01.md"
        assert craquement.exists(), f"craquement prose-polluee absent : {craquement}"
        print("2) craquement-prose-polluee-01.md écrit")

        resume = (partie_dir / "resume-run.md").read_text(encoding="utf-8")
        assert "raison_arret: craquement-prose-polluee" in resume, resume
        assert "craquement-prose-polluee-01.md" in resume, resume
        print("3) resume-run.md : raison_arret craquement-prose-polluee, craquement listé")

        print("\nALL NUIT_PROSE_POLLUEE TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
