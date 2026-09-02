"""Issue #269 : tools/banc/extraire_prose.py — extraction MÉCANIQUE (aucun
LLM) de la section « Prose du Narrateur » d'un `tour-NN.md` synthétique.
Cas couverts : section présente (titre canonique et variantes de titre),
absente, vide.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools" / "banc"))

from extraire_prose import extraire_prose, main  # noqa: E402


def main_test() -> int:
    # 1) titre canonique, contenu multi-lignes, borné par le titre suivant.
    tour = """# tour 01

## Visée du Director

la visée, jamais lue par le joueur.

## Prose du Narrateur (verbatim)

Le vent siffle entre les tours en ruine.

Une silhouette bouge au loin.

## Événements moteur

roll_check: ...
"""
    corps = extraire_prose(tour)
    assert corps == (
        "Le vent siffle entre les tours en ruine.\n\n"
        "Une silhouette bouge au loin."
    ), repr(corps)
    print("1) section présente, bornée par le titre suivant : extraite verbatim")

    # 2) section en fin de fichier (pas de titre suivant).
    tour_fin = "## Prose du Narrateur (verbatim)\n\nDernière ligne du tour.\n"
    assert extraire_prose(tour_fin) == "Dernière ligne du tour.", repr(
        extraire_prose(tour_fin)
    )
    print("2) section en fin de fichier (aucun titre suivant) : extraite")

    # 3) variantes de titre : niveau de titre différent, casse différente,
    # sans le suffixe « (verbatim) ».
    variantes = [
        "### prose du narrateur\n\nMinuscules, niveau 3.\n",
        "## PROSE DU NARRATEUR\n\nMajuscules, sans suffixe.\n",
        "#### Prose du Narrateur :\n\nSuffixe deux-points.\n",
    ]
    attendu = [
        "Minuscules, niveau 3.",
        "Majuscules, sans suffixe.",
        "Suffixe deux-points.",
    ]
    for v, a in zip(variantes, attendu):
        assert extraire_prose(v) == a, (v, extraire_prose(v))
    print("3) variantes de titre (niveau, casse, suffixe) : toutes extraites")

    # 4) section absente.
    sans_section = "# tour 01\n\n## Visée du Director\n\nrien d'autre.\n"
    assert extraire_prose(sans_section) is None
    print("4) section absente : None")

    # 5) section présente mais vide (juste le titre suivant, ou fin de
    # fichier sans contenu).
    vide_titre_suivant = (
        "## Prose du Narrateur (verbatim)\n\n## Événements moteur\n\nrien\n"
    )
    assert extraire_prose(vide_titre_suivant) is None
    vide_fin_fichier = "## Prose du Narrateur (verbatim)\n\n   \n"
    assert extraire_prose(vide_fin_fichier) is None
    print("5) section présente mais vide : None")

    # 6) CLI bout-en-bout : écrit prose-NN.md sur succès, rien sur échec.
    tmp = Path(tempfile.mkdtemp(prefix="extraire-prose-test-"))
    try:
        tour_path = tmp / "tour-01.md"
        prose_path = tmp / "prose-01.md"
        tour_path.write_text(tour, encoding="utf-8")
        rc = main(["extraire_prose.py", str(tour_path), str(prose_path)])
        assert rc == 0, rc
        assert prose_path.exists()
        assert "Le vent siffle" in prose_path.read_text(encoding="utf-8")
        print("6a) CLI : section présente -> sortie 0, prose-01.md écrit")

        tour_vide_path = tmp / "tour-02.md"
        prose_vide_path = tmp / "prose-02.md"
        tour_vide_path.write_text(sans_section, encoding="utf-8")
        rc2 = main(["extraire_prose.py", str(tour_vide_path), str(prose_vide_path)])
        assert rc2 == 1, rc2
        assert not prose_vide_path.exists()
        print("6b) CLI : section absente -> sortie 1, prose-02.md jamais écrit")
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)

    print("\nALL EXTRAIRE_PROSE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
