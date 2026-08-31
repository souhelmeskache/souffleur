"""Verrou du comportement « deux entrées `declaration_rendu` pour la même
scène » (Issue #191, découpe de #189 pt 2 -- volet TEST uniquement). Aucun
changement de code : ce test constate et verrouille le comportement ACTUEL
de `coderain.converter.rendu_auteur.ecrire_rendu_auteur` (via
`ecrivain_module.vers_scenario_auteur` puis `_fusionner`) quand deux entrées
de `declaration_rendu` visent le MÊME node_id (même scène, même titre) :
la DERNIÈRE entrée gagne, silencieusement -- pas d'ajout de retour
d'appelant listant les scènes écrasées, ça reste dans #189.

Fixture 100% synthétique (D-109) : partition fabriquée pour le test, aucun
matériau de campagne réel.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.converter.rendu_auteur import ecrire_rendu_auteur
from coderain.converter.schemas import Manifest, Node, Partition


def _manifest():
    return Manifest(titre="module factice doublon scene",
                    corpus_source="5e", corpus_cible="5e",
                    structures=["S1"], hash_source="9" * 64,
                    date_conversion="2026-08-31T00:00:00+00:00",
                    version_convertisseur="test")


TITRE = "Scène -- le relais fabriqué"
node = Node("sc-relais", "section", TITRE, "Halte fabriquée.", "scene",
           anchors=[(0, 10)])
partition = Partition(_manifest())
partition.nodes.append(node)

# deux entrées declaration_rendu pour la MÊME scène (même titre -> même
# node_id après mapping) -- ordre volontaire, la seconde doit gagner.
declaration_rendu = (
    {"scene": TITRE, "rendu_md": "registre feutré ; première proposition"},
    {"scene": TITRE, "rendu_md": "registre urgent ; seconde proposition"},
)

tmp = Path(tempfile.mkdtemp(prefix="rendu-auteur-doublon-i191-"))
try:
    chemin = tmp / "scenario-auteur.json"
    res = ecrire_rendu_auteur(declaration_rendu, partition, [chemin])

    data = json.loads(chemin.read_text(encoding="utf-8"))
    entrees_node = [s for s in data["scenarios"] if s["node_id"] == "sc-relais"]

    # une seule entrée dans le fichier fusionné pour ce node_id (fusion par
    # node_id dans _fusionner -- pas de doublon en sortie)
    assert len(entrees_node) == 1, entrees_node
    # la DERNIÈRE entrée de declaration_rendu gagne, silencieusement
    assert entrees_node[0]["rendu_md"] == "registre urgent ; seconde proposition", \
        entrees_node

    # côté retour de ecrire_rendu_auteur, `entrees` reflète bien les DEUX
    # entrées câblées par vers_scenario_auteur (une par entrée de
    # declaration_rendu, avant fusion) -- pas de déduplication à cette étape
    entrees_res = [e for e in res["entrees"] if e["node_id"] == "sc-relais"]
    assert len(entrees_res) == 2, entrees_res
    assert [e["rendu_md"] for e in entrees_res] == [
        "registre feutré ; première proposition",
        "registre urgent ; seconde proposition"]
    # aucun avertissement pour ce cas (scène connue, titre non ambigu) --
    # le silence sur l'écrasement lui-même reste le comportement actuel,
    # hors périmètre de cette lane (#189)
    assert res["avertissements"] == [], res["avertissements"]
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("test-rendu-auteur-doublon-scene-i191: OK -- deux entrées pour la "
     "même scène, la dernière gagne silencieusement dans "
     "scenario-auteur.json (comportement actuel verrouillé)")
