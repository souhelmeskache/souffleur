"""D-275 §6 (Issue #339, découpe (b) de #316) : la partition DÉCLARE ses
combats — entrée `combats` par nœud dans `mapping-regles.json` (créature,
déclencheur, régime au vocabulaire fermé `docs/couverture-moteur.md` §4).

100% synthétique (D-109) : partition factice (3 nœuds, 2 créatures dont une
sans bloc de stats) — aucun matériau de campagne réel.

Couvre :
- déclaration attendue : node.combats -> mapping-regles.json (aval.
  extract_combats), régime dérivé à froid des faits déjà validés du record
  (ancre_srd/delta_vs_ancre), jamais improvisé.
- refus attendu : une créature déclarée sans bloc de stats projeté (aucun
  record classe creature du même slug) est un refus de forme NOMMÉ (nœud,
  slug) — validate_form, jamais un bouchage.
- zéro faux positif : le nœud sans déclaration ne produit aucune entrée et
  n'est jamais nommé dans un refus.
- garde de forme (schemas.Node._check_combats) : forme exacte exigée,
  slug kebab, declencheur_md non vide.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.converter import validate_form
from coderain.converter.aval import extract_combats
from coderain.converter.schemas import (
    COMBAT_REGIME_HORS_VOCABULAIRE, Manifest, Node, Partition, Record,
)

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def manifest():
    return Manifest(titre="module factice", corpus_source="5e", corpus_cible="5e",
                    structures=["S1"], hash_source="0" * 64,
                    date_conversion="2026-08-29T00:00:00+00:00",
                    version_convertisseur="test")


# -- fixture: 3 noeuds, 2 creatures dont une sans bloc de stats -------------
p = Partition(manifest())
p.nodes.append(Node("scene-couloir", "scene", "COULOIR",
                    "Un couloir vide et poussiéreux.", "scene",
                    anchors=[(0, 30)]))
p.nodes.append(Node("scene-embuscade", "scene", "EMBUSCADE",
                    "Un Gobelin Bondissant surgit de l'ombre.", "scene",
                    anchors=[(30, 70)],
                    combats=[{"creature": "gobelin-bondissant",
                              "declencheur_md": "Un Gobelin Bondissant "
                                                "surgit de l'ombre."}]))
p.nodes.append(Node("scene-fosse", "scene", "FOSSE",
                    "Un Gobelin Fantome hurle depuis la fosse.", "scene",
                    anchors=[(70, 110)],
                    combats=[{"creature": "gobelin-fantome",
                              "declencheur_md": "Un Gobelin Fantome hurle "
                                                "depuis la fosse."}]))
# une seule créature porte un bloc de stats projeté (l'autre, gobelin-
# fantome, n'a AUCUN record — la déclaration existe côté node, pas le bloc)
p.records.append(Record(
    "gobelin-bondissant", "creature", "Gobelin Bondissant",
    {"ca": 13, "pv": 7, "vitesse": "30 ft", "attaque_bonus": 4,
     "degats": "1d6+2", "ancre_srd": "goblin-warrior"}, [(30, 60)]))


# 1 -- déclaration attendue : 2 entrées, une par créature déclarée ----------
section("declaration attendue : extract_combats liste les 2 declarations")
combats = extract_combats(p)
assert len(combats) == 2, combats
par_noeud = {c["noeud"]: c for c in combats}
assert set(par_noeud) == {"scene-embuscade", "scene-fosse"}, par_noeud

# 2 -- régime dérivé (vocabulaire fermé) pour la créature avec bloc de stats
section("regime derive : ancre_srd sans delta -> monster.srd_direct")
c1 = par_noeud["scene-embuscade"]
assert c1["creature"] == "gobelin-bondissant"
assert c1["declencheur"] == ("Un Gobelin Bondissant surgit de l'ombre.")
assert c1["regime"] == "monster.srd_direct", c1

# 3 -- créature sans bloc de stats -> hors-vocabulaire (jamais invente) -----
section("creature sans bloc de stats projete : regime hors-vocabulaire")
c2 = par_noeud["scene-fosse"]
assert c2["creature"] == "gobelin-fantome"
assert c2["regime"] == COMBAT_REGIME_HORS_VOCABULAIRE, c2

# 4 -- zero faux positif : le noeud sans declaration n'emet aucune entree --
section("zero faux positif : scene-couloir absent de la liste")
assert "scene-couloir" not in par_noeud

# 5 -- refus de forme NOMME (noeud, slug) : creature declaree sans record --
section("valideur : refus de forme nomme (noeud, slug) pour gobelin-fantome")
errs = validate_form.validate_form(p)
refus = [e for e in errs if "gobelin-fantome" in e]
assert len(refus) == 1, errs
assert "scene-fosse" in refus[0], refus
assert "D-275" in refus[0], refus
# la créature backée par un record ne produit AUCUN refus de ce type
assert not [e for e in errs if "gobelin-bondissant" in e], errs
# zero faux positif cote valideur aussi : scene-couloir jamais nomme
assert not [e for e in errs if "scene-couloir" in e], errs

# 6 -- garde de forme (schemas.Node._check_combats) -------------------------
section("garde de forme : slug invalide refuse a la construction")
try:
    Node("scene-x", "scene", "X", "texte", "scene", anchors=[(0, 5)],
        combats=[{"creature": "Gobelin Invalide", "declencheur_md": "x"}])
    raise AssertionError("slug invalide aurait du etre refuse")
except ValueError as e:
    assert "slug" in str(e)

section("garde de forme : declencheur_md vide refuse a la construction")
try:
    Node("scene-y", "scene", "Y", "texte", "scene", anchors=[(0, 5)],
        combats=[{"creature": "gobelin-x", "declencheur_md": "   "}])
    raise AssertionError("declencheur_md vide aurait du etre refuse")
except ValueError as e:
    assert "declencheur_md" in str(e)

section("garde de forme : cle en trop refusee a la construction")
try:
    Node("scene-z", "scene", "Z", "texte", "scene", anchors=[(0, 5)],
        combats=[{"creature": "gobelin-x", "declencheur_md": "x",
                  "regime": "monster.srd_direct"}])
    raise AssertionError("cle en trop aurait du etre refusee")
except ValueError as e:
    assert "forme exacte" in str(e)

print(f"\nOK test-combats-declares-d275-6-i339 — {len(FAIT)} sections vertes")
