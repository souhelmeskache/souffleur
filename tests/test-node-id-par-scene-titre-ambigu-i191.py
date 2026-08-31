"""Verrou du chemin « titre ambigu » (Issue #191, découpe de #189 pt 6) :
`coderain.converter.rendu_auteur.node_id_par_scene` face à une partition où
DEUX scènes portent le même titre. Comportement documenté (docstring de
`node_id_par_scene`) : le titre ambigu est exclu du mapping, jamais résolu
au hasard, et un avertissement motivé est émis. Ce test verrouille ce
comportement ACTUEL — aucun changement de code.

Fixture 100% synthétique (D-109) : partition fabriquée pour le test, aucun
matériau de campagne réel.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.converter.rendu_auteur import node_id_par_scene
from coderain.converter.schemas import Manifest, Node, Partition


def _manifest():
    return Manifest(titre="module factice titre ambigu",
                    corpus_source="5e", corpus_cible="5e",
                    structures=["S1"], hash_source="8" * 64,
                    date_conversion="2026-08-31T00:00:00+00:00",
                    version_convertisseur="test")


TITRE_AMBIGU = "Scène -- la traversée du pont fabriqué"
TITRE_UNIQUE = "Scène -- le campement fabriqué"

node_a = Node("sc-pont-a", "section", TITRE_AMBIGU,
             "Premier passage fabriqué.", "scene", anchors=[(0, 10)])
node_b = Node("sc-pont-b", "section", TITRE_AMBIGU,
             "Second passage fabriqué, même titre.", "scene",
             anchors=[(10, 20)])
node_unique = Node("sc-campement", "section", TITRE_UNIQUE,
                   "Halte fabriquée.", "scene", anchors=[(20, 30)])

partition = Partition(_manifest())
partition.nodes.extend([node_a, node_b, node_unique])

mapping, ambigus, avertissements = node_id_par_scene(partition)

# le titre ambigu est exclu du mapping, jamais résolu au hasard sur l'un
# des deux nodes candidats
assert TITRE_AMBIGU not in mapping, mapping
# le titre unique, lui, reste câblé normalement
assert mapping.get(TITRE_UNIQUE) == "sc-campement", mapping
# signalé dans les titres ambigus
assert ambigus == {TITRE_AMBIGU}, ambigus
# et dans les avertissements, motivé (les deux node_id cités)
assert len(avertissements) == 1, avertissements
assert TITRE_AMBIGU in avertissements[0]
assert "sc-pont-a" in avertissements[0] and "sc-pont-b" in avertissements[0]
assert "ambigu" in avertissements[0]

print("test-node-id-par-scene-titre-ambigu-i191: OK — titre porté par deux "
     "nodes exclu du mapping, signalé, jamais résolu au hasard")
