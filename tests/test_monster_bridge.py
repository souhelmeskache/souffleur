"""I-205 — Issue #205 : plus de pass silencieux quand un membre d'encounter
n'a pas de comportement de combat jouable.

Volet 1 (bruyant) : un `monster_template_slug` absent ou non résolu dans
`dnd5e-srd-data` fait porter un avertissement explicite par
`coderain.rules_engine.engine_bridge` — sur `start_combat` ET sur chaque
`monster_turn` de l'acteur concerné, jamais seulement à l'ouverture.

Volet 2 (pont minimal) : `coderain.rules_engine.monster_bridge` mappe un
record de module (`get_record()`, champs français `ca`/`pv`/`attaque_bonus`/
`degats`) vers un template de combat générique 'brute' paramétré par ces
mêmes chiffres — le monstre produit alors des intents non-pass.

100% synthétique (D-109) : le record `creature` ci-dessous est un stat block
factice, aucun matériau de module réel. `ice-fiend` n'apparaît qu'en nom
d'exemple documentaire (docs/annexe-a-stats-5e.md), jamais copié ici.

Needs dnd5e-engine==0.3.0 installed (requirements.txt); skips loudly if absent.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import dnd5e_engine  # noqa: F401
except ImportError:
    print("SKIP: dnd5e-engine not installed (pip install -r requirements.txt)")
    sys.exit(0)

from coderain.rules_engine import get_bridge
from coderain.rules_engine.monster_bridge import (
    brute_template_slug,
    encounter_member_from_record,
)

KAEL = {"entity_id": "pj:kael", "name": "Kael", "initiative": 15,
        "hp_current": 12, "hp_max": 12, "ac": 10, "attack_bonus": 5,
        "strength": 16, "dexterity": 14, "constitution": 14, "zone_id": "z1",
        "equipment": ["longsword"]}

# Record synthétique classe `creature` — champs obligatoires D-109
# (`converter/annexe_a.py::REQUIRED_STATS["creature"]`), forme renvoyée par
# `coderain.converter.aval.get_record` ({"meta": ..., "stats": ...}).
FAKE_CREATURE_RECORD = {
    "meta": {"id": "creature-factice", "classe": "creature"},
    "stats": {"nom": "Bête factice", "ca": 15, "pv": 30,
             "vitesse": "30 ft.", "attaque_bonus": 6, "degats": "2d8+4 cold"},
}

bridge = get_bridge()


# 1) Aucun monster_template_slug du tout -> avertissement explicite, jamais
#    un pass indiscernable d'une passivité voulue (start_combat ET
#    monster_turn portent l'avertissement).
async def no_slug_probe():
    encounter = [{"entity_id": "pnj:mob1", "entity_type": "Monster", "name": "Blob",
                  "initiative": 5, "hp_current": 5, "hp_max": 5, "ac": 10, "zone_id": "z1"}]
    st = await bridge.start_combat(session_id="i205-no-slug", party=[KAEL],
                                   encounter=encounter, rng_seed=1, zones=["z1"])
    h = st["handle_id"]
    try:
        assert len(st["warnings"]) == 1, st["warnings"]
        w = st["warnings"][0]
        assert w["entity_id"] == "pnj:mob1"
        assert w["monster_template_slug"] is None
        assert "non résolu" in w["reason"]

        await bridge.submit_intent(h, "pj:kael", {"intent_type": "pass"})
        res = await bridge.monster_turn(h)
        assert res["warnings"] == [w]
        pass_events = [e for e in res["events"] if e.get("type") == "intent_submitted"]
        assert pass_events and pass_events[0]["intent_type"] == "pass"
    finally:
        await bridge.end_combat(h)


asyncio.run(no_slug_probe())
print("1) encounter sans monster_template_slug => avertissement explicite, "
      "start_combat + chaque monster_turn, jamais un pass silencieux")


# 2) monster_template_slug fourni mais absent du corpus SRD -> même
#    avertissement (le slug est rendu, la raison est identique).
async def unresolved_slug_probe():
    encounter = [{"entity_id": "pnj:mob2", "entity_type": "Monster", "name": "Fantôme",
                  "initiative": 5, "hp_current": 5, "hp_max": 5, "ac": 10, "zone_id": "z1",
                  "monster_template_slug": "does-not-exist-in-srd"}]
    st = await bridge.start_combat(session_id="i205-bad-slug", party=[KAEL],
                                   encounter=encounter, rng_seed=1, zones=["z1"])
    h = st["handle_id"]
    try:
        assert len(st["warnings"]) == 1, st["warnings"]
        assert st["warnings"][0]["monster_template_slug"] == "does-not-exist-in-srd"
    finally:
        await bridge.end_combat(h)


asyncio.run(unresolved_slug_probe())
print("2) monster_template_slug fourni mais absent de dnd5e-srd-data => "
      "même avertissement explicite")


# 3) Pont minimal : record de module -> template 'brute' -> le monstre
#    produit des intents NON-pass (une vraie attaque), zéro avertissement.
async def brute_bridge_probe():
    member = encounter_member_from_record(
        FAKE_CREATURE_RECORD, record_id="creature-factice",
        entity_id="pnj:factice-1", zone_id="z1", initiative=8)
    assert member["monster_template_slug"] == brute_template_slug("creature-factice")

    st = await bridge.start_combat(session_id="i205-brute", party=[KAEL],
                                   encounter=[member], rng_seed=1, zones=["z1"])
    h = st["handle_id"]
    try:
        assert st["warnings"] == [], st["warnings"]
        await bridge.submit_intent(h, "pj:kael", {"intent_type": "pass"})
        res = await bridge.monster_turn(h)
        assert res["warnings"] == []
        intents = [e for e in res["events"] if e.get("type") == "intent_submitted"]
        assert intents and intents[0]["intent_type"] != "pass", intents
        assert any(e.get("type") == "damage_applied" for e in res["events"]), res["events"]
    finally:
        await bridge.end_combat(h)


asyncio.run(brute_bridge_probe())
print("3) record de module -> template 'brute' (monster_bridge) => intent "
      "non-pass, zéro avertissement")

print("\nMONSTER-BRIDGE TESTS PASSED")
