"""Issue #176 (SOCLE) : champ rendu_md sur le Node + garde anti-rail D-065.

100% synthétique (D-109) : aucun matériau de module réel. Couvre :
  1. rendu_md couleur (ton/rythme) accepté, node construit normalement ;
  2. rendu_md par défaut vide, aucune régression sur un node sans rendu_md ;
  3. rendu_md posant une séquence d'événements imposée refusé à la
     construction (marqueurs "puis"/"ensuite"/... et listes d'étapes
     numérotées) — garde anti-rail, jamais une couleur travestie en script ;
  4. rendu_md disponible à toute altitude, pas réservé à 'scenario'
     (contrairement à objectif_md/debouches/heritage) ;
  5. sérialisation : rendu_md survit à l'écriture/lecture de la partition
     (write_partition / get_node), comme les autres rubriques du node.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.converter.aval import get_node
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def manifest():
    return Manifest(titre="module factice rendu_md", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"], hash_source="3" * 64,
                    date_conversion="2026-08-30T00:00:00+00:00",
                    version_convertisseur="test")


# 1 -- rendu_md couleur : accepté ---------------------------------------------
section("rendu_md couleur (ton/rythme) accepté")
COULEUR = ("registre feutré ; joue les silences et les regards, ne révèle "
           "rien, laisse le doute monter")
n1 = Node("scene-1", "scene", "Le seuil", "Vous êtes devant une porte close.",
         "scene", anchors=[(0, 40)], rendu_md=COULEUR)
assert n1.rendu_md == COULEUR

# 2 -- valeur par défaut vide : aucune régression -----------------------------
section("rendu_md par défaut vide sur un node sans consigne")
n2 = Node("scene-2", "scene", "Le couloir", "Un couloir sombre.", "scene",
         anchors=[(40, 80)])
assert n2.rendu_md == ""

# 3 -- garde anti-rail : séquence d'événements imposée refusée ---------------
section("garde anti-rail : séquence d'événements imposée refusée")
SEQUENCES_INTERDITES = [
    "le joueur fait X puis Y",
    "décris le garde qui s'approche, ensuite il dégaine",
    "d'abord la porte grince, après quoi la lumière s'éteint",
    "1. le joueur entre\n2. le garde l'interpelle",
    "étape 1 : présente le PNJ\nétape 2 : révèle le piège",
]
for texte in SEQUENCES_INTERDITES:
    try:
        Node("x", "scene", "X", "b", "scene", anchors=[(0, 1)], rendu_md=texte)
        raise AssertionError(f"séquence imposée acceptée : {texte!r}")
    except ValueError as e:
        assert "D-065" in str(e), e

# 4 -- disponible à toute altitude, pas réservé à 'scenario' -----------------
section("rendu_md disponible à toute altitude (pas réservé à scenario)")
n4 = Node("scene-3", "chapitre", "Chapitre I", "Prose.", "adventure",
         anchors=[(0, 10)], rendu_md="registre solennel, presque cérémoniel")
assert n4.rendu_md == "registre solennel, presque cérémoniel"
n5 = Node("scene-4", "scene", "Scénario", "Prose.", "scenario",
         anchors=[(0, 10)], objectif_md="atteindre la tour",
         rendu_md="tension continue, jamais de répit")
assert n5.rendu_md == "tension continue, jamais de répit"
assert n5.objectif_md == "atteindre la tour"

# 5 -- sérialisation : survit à l'écriture/lecture de la partition -----------
section("sérialisation : rendu_md survit à write_partition/get_node")
tmp = Path(tempfile.mkdtemp(prefix="rendu-md-anti-rail-"))
try:
    p = Partition(manifest())
    p.nodes.append(n1)
    p.nodes.append(n2)
    write_partition(p, tmp)
    loaded1 = get_node(tmp, "scene-1")
    assert loaded1["meta"]["rendu_md"] == COULEUR, loaded1["meta"]
    loaded2 = get_node(tmp, "scene-2")
    assert "rendu_md" not in loaded2["meta"], (
        "rendu_md vide ne doit pas polluer le front matter (comme "
        "objectif_md/heritage/debouches, cf. emit.py)")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\nOK rendu-md-anti-rail-test — {len(FAIT)} sections vertes")
