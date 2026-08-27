"""I-200 evolution interne du personnage — 4 tests.

1. Creation personnage avec 2 vecteurs (schema + validate_form)
2. Increment par acte role-play (journal2vecteur)
3. Refus grille 9 cases (D-090)
4. Persistance apres save/load
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from coderain.memory import Library
from mcp_server import (
    _validate_evolution_interne,
    journal2vecteur,
    _FORBIDDEN_ALIGNMENTS,
    _EVOLUTION_INTERNE_MIN,
    _EVOLUTION_INTERNE_MAX,
)

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


# ---- 1) Creation personnage avec 2 vecteurs --------------------------------
section("1. Creation personnage avec 2 vecteurs")

schema_path = ROOT / "schemas" / "character.json"
assert schema_path.exists(), f"schema introuvable : {schema_path}"
schema = json.loads(schema_path.read_text(encoding="utf-8"))
assert "evolution_interne" in schema["properties"], \
    "schema: champ evolution_interne absent"
ei_schema = schema["properties"]["evolution_interne"]
assert ei_schema["type"] == "object"
assert "vecteurs" in ei_schema["properties"]
vec_items = ei_schema["properties"]["vecteurs"]["items"]["properties"]
assert "id" in vec_items
assert "label" in vec_items
assert "valeur" in vec_items
assert "source" in vec_items
assert vec_items["valeur"]["minimum"] == -5
assert vec_items["valeur"]["maximum"] == 5
assert vec_items["source"]["enum"] == ["interoception", "journal"]
assert ei_schema["properties"]["vecteurs"]["minItems"] == 2

vecteurs_ok = [
    {"id": "audace--retenue", "label": "audace--retenue",
     "valeur": 2, "source": "interoception"},
    {"id": "altruisme--pragmatisme", "label": "altruisme--pragmatisme",
     "valeur": -1, "source": "journal"},
]
clean = _validate_evolution_interne(vecteurs_ok)
assert len(clean) == 2
assert clean[0]["valeur"] == 2
assert clean[1]["source"] == "journal"
print("  schema OK, 2 vecteurs valides, bornes [-5,+5], sources OK")

# ---- 2) Increment par acte role-play ----------------------------------------
section("2. Increment par acte role-play (journal2vecteur)")

root = os.path.join(tempfile.gettempdir(), "se_evo_i200")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
slug = lib.create_story("EI200", "A character evolving internally.")
store = lib.store(slug)

rpg = store.rpg_state()
rpg["enabled"] = True
rpg["evolution_interne"] = {
    "vecteurs": [
        {"id": "audace--retenue", "label": "audace--retenue",
         "valeur": 0, "source": "interoception"},
        {"id": "altruisme--pragmatisme", "label": "altruisme--pragmatisme",
         "valeur": 0, "source": "interoception"},
    ]
}
store.set_rpg_state(rpg)

res = journal2vecteur("Le personnage sauve un enfant du feu.", "audace--retenue")
assert res["delta"] == 1, res
assert not res.get("refused"), res

rpg = store.rpg_state()
vecteurs = rpg["evolution_interne"]["vecteurs"]
for v in vecteurs:
    if v["id"] == "audace--retenue":
        old = v["valeur"]
        v["valeur"] = max(_EVOLUTION_INTERNE_MIN,
                          min(_EVOLUTION_INTERNE_MAX, old + res["delta"]))
        v["source"] = "journal"
store.set_rpg_state(rpg)

rpg2 = store.rpg_state()
v_audace = [v for v in rpg2["evolution_interne"]["vecteurs"]
            if v["id"] == "audace--retenue"][0]
assert v_audace["valeur"] == 1
assert v_audace["source"] == "journal"

res_neg = journal2vecteur("Le personnage trahit son allie.", "audace--retenue")
assert res_neg["delta"] == -1, res_neg
print("  acte positif -> delta +1, acte negatif -> delta -1, source -> journal")

# ---- 3) Refus grille 9 cases (D-090) ----------------------------------------
section("3. Refus grille 9 cases (D-090)")

vecteurs_bad = [
    {"id": "align", "label": "neutral good",
     "valeur": 0, "source": "interoception"},
    {"id": "autre", "label": "autre-axe",
     "valeur": 0, "source": "interoception"},
]
try:
    _validate_evolution_interne(vecteurs_bad)
    assert False, "should have raised ValueError for alignment label"
except ValueError as e:
    assert "D-090" in str(e) or "alignment" in str(e).lower(), \
        f"erreur attendue D-090/alignment, recu : {e}"

for align_label in ["lawful good", "chaotic evil", "true neutral", "LG", "CE"]:
    vecteurs_test = [
        {"id": "test", "label": align_label, "valeur": 0, "source": "interoception"},
        {"id": "test2", "label": "autre", "valeur": 0, "source": "interoception"},
    ]
    try:
        _validate_evolution_interne(vecteurs_test)
        assert False, f"should have refused alignment {align_label!r}"
    except ValueError:
        pass

res_meta = journal2vecteur("Je pense que mon personnage est lawful good", "x")
assert res_meta.get("refused") is True, res_meta
assert "D-090" in res_meta["reason"]

res_meta2 = journal2vecteur("as a player, I feel my character is neutral", "x")
assert res_meta2.get("refused") is True, res_meta2
print("  grille 9 cases refusee (5 labels testes), meta-probing refuse (D-090)")

# ---- 4) Persistance apres save/load -----------------------------------------
section("4. Persistance apres save/load")

rpg_before = store.rpg_state()
ei_before = rpg_before["evolution_interne"]
assert len(ei_before["vecteurs"]) == 2

store2 = lib.store(slug)
rpg_after = store2.rpg_state()
ei_after = rpg_after.get("evolution_interne")
assert ei_after is not None, "evolution_interne perdu apres reload"
assert len(ei_after["vecteurs"]) == 2
v1 = [v for v in ei_after["vecteurs"] if v["id"] == "audace--retenue"][0]
assert v1["valeur"] == 1, f"valeur attendue 1, recu {v1['valeur']}"
assert v1["source"] == "journal"
v2 = [v for v in ei_after["vecteurs"] if v["id"] == "altruisme--pragmatisme"][0]
assert v2["valeur"] == 0
print("  evolution_interne persiste apres save/load (2 vecteurs, valeurs intactes)")

# ---- bilan -------------------------------------------------------------------
assert len(FAIT) == 4, f"4 sections attendues, {len(FAIT)} faites"
print(f"\n4/4 PASSED ({len(FAIT)} sections)")
print("ALL PASSED")
