"""Issue #295 : tools/banc/nuit.sh — reproduction du craquement
`prose-absente` constaté en production (run du 05/09, `bench/nuit-20260905/`)
alors que `prose-NN.md` existe et est non vide sur le disque, écrit par le
MJ conformément à l'ancienne étape 8 du gabarit `banc-mj.md` : un renvoi
dans `tour-01.md` ("voir prose-01.md — relue sur le disque, non vide"),
sans section « Prose du Narrateur » exploitable dans `tour-01.md` lui-même.

Avant #295, `nuit.sh` n'essayait QUE l'extraction depuis `tour-NN.md`
(#269) et craquait `prose-absente` dans ce cas précis — alors même que le
MJ avait suivi le gabarit (d'alors) à la lettre. Le complément #295 a
depuis réécrit le gabarit pour IMPOSER la prose inline dans `tour-NN.md`
(voie extraction, désormais PRIMAIRE) ; la voie fichier exercée ici reste
un REPLI TOLÉRANT — ce test rejoue exactement la forme de
tour-01.md/prose-01.md constatée en production, à travers
`tools/banc/arbitrer_prose.py` (appelé désormais par `nuit.sh`), et
vérifie que le tour est quand même joué par ce repli, sans craquement.

Note : les fichiers RÉELS de `bench/nuit-20260905/partie-0{1,2}/` cités
dans l'Issue vivent uniquement sur la machine où tourne le banc de nuit
(`bench/nuit-*/` est gitignoré, jamais commité — D-109, aucun matériau réel
dans ce dépôt) ; ce test en reconstruit une forme 100% synthétique
équivalente (même structure de renvoi, même absence de section) plutôt que
de dépendre de fichiers absents de ce worktree.

Utilise `-LancementCmd` (même convention que #269,
tests/nuit_prose_absente_test.py) pour écrire `tour-01.md` ET `prose-01.md`
de façon déterministe, sans agent réel lancé. `prose-01.md` reçoit un mtime
loin dans le futur pour garantir qu'il est bien "postérieur à l'envoi du
go" quel que soit l'instant exact où `nuit.sh` capture `go_ts` (la fenêtre
entre l'écriture synchrone du fake et le calcul de `go_ts` est de l'ordre
de la milliseconde -- ce test ne cherche pas à l'exercer, juste à vérifier
que la voie fichier fonctionne quand `prose-01.md` est bien postérieur).
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

# Reproduit la forme exacte constatée en production (#295) : tour-01.md ne
# porte qu'un renvoi, jamais la section "## Prose du Narrateur" ; prose-01.md
# est écrit séparément par le MJ (étape 8 du gabarit), avec un mtime placé
# loin dans le futur pour être certainement "postérieur au go".
LANCEMENT_CMD_FAKE = (
    'echo "Pane MJ: fake-mj-pane"; '
    'echo "Pane joueur-banc: fake-joueur-pane"; '
    'printf "# tour 01\\n\\n## Visee du Director\\n\\n'
    'la marche glaciale vers le Chateau de la Folie... scene #1 du module.\\n\\n'
    'Prose retournee par le narrateur (verbatim) : voir prose-01.md -- '
    'relue sur le disque, non vide.\\n" > "$partie_dir/tour-01.md"; '
    'printf "Le vent glacial mord les joues des voyageurs qui avancent vers '
    'le chateau.\\n" > "$partie_dir/prose-01.md"; '
    'python -c "import os,sys; f=sys.argv[1]; os.utime(f, (9999999999, 9999999999))" '
    '"$partie_dir/prose-01.md"; '
    'exit 0'
)


def main() -> int:
    assert NUIT_SH.exists(), f"script absent : {NUIT_SH}"

    tmp = Path(tempfile.mkdtemp(prefix="nuit-prose-voie-fichier-test-"))
    try:
        lib_root = tmp / "lib"
        lib = Library(lib_root)
        slug = lib.saves.create(
            "Nuit Prose Voie Fichier Test", mode="rpg",
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
            f"un tour joué par la voie fichier reste sortie 0 -- reçu "
            f"{p.returncode}\nstdout={p.stdout}\nstderr={p.stderr}"
        )
        print("1) nuit.sh -Parties 1 avec prose-01.md écrit par le MJ (voie fichier) : sortie 0")

        partie_dir = run_dir / "partie-01"
        assert (partie_dir / "tour-01.md").exists(), "tour-01.md attendu"
        prose = partie_dir / "prose-01.md"
        assert prose.exists() and prose.stat().st_size > 0, (
            "prose-01.md doit être PRÉSENT (voie fichier) -- exactement le cas "
            "constaté en production où il craquait à tort"
        )
        assert "Le vent glacial" in prose.read_text(encoding="utf-8"), (
            "prose-01.md doit garder le texte écrit par le MJ (voie fichier), "
            "jamais réécrit par l'extraction"
        )
        print("2) prose-01.md PRÉSENT, contenu du MJ préservé (voie fichier, pas d'extraction)")

        assert not (partie_dir / "craquement-prose-absente-01.md").exists(), (
            "aucun craquement prose-absente attendu : la voie fichier a servi"
        )
        assert not (partie_dir / "craquement-prose-polluee-01.md").exists(), (
            "aucun craquement prose-polluee attendu : le fichier est de la prose pure"
        )
        print("3) aucun craquement -- le tour est bien joué")

        resume = (partie_dir / "resume-run.md").read_text(encoding="utf-8")
        assert "tours_joues: 1" in resume, resume
        print("4) resume-run.md : tours_joues 1")

        assert "prose via fichier" in p.stdout, p.stdout
        print("5) journal du tour : voie fichier mentionnée dans la sortie standard")

        print("\nALL NUIT_PROSE_VOIE_FICHIER TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
