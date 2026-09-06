"""Issue #317 — découpe (a) de #316, second appelant du chemin de lecture
unique (`mcp_server._creature_stats`, voir aussi
`tests/test-element-lecture-fiche-projetee-i317.py`).

Constat au banc (nuit 06/09, partie 02, tour 13) :
`coderain.rules_engine.monster_bridge.encounter_member_from_record`
(pont brute, I-205) n'avait AUCUN appelant — `start_combat` s'ouvrait avec
« aucun monster_template_slug résolu », aucun comportement de combat pour
un membre non-joueur passé par simple slug.

Couvre :
  1. un membre d'`encounter` sans `monster_template_slug`, identifié par
     `entity_id` = slug d'une entrée `characters.md` projetée (bloc JSON du
     corps), se résout en membre jouable — `ca`/`pv`/`attaque_bonus` repris
     du record, template 'brute' installé, zéro avertissement moteur ;
  2. un membre déjà résolu (monster_template_slug fourni) traverse
     inchangé — pas de double résolution ;
  3. un slug qui ne correspond À AUCUNE fiche ni record est un REFUS
     explicite de `start_combat` (`{"error": ...}`), jamais un tour vide.

Needs dnd5e-engine==0.3.0 (requirements.txt) ; saute bruyamment si absent,
même convention que `test_rules_engine.py`/`test_monster_bridge.py`.

Fixtures 100% synthétiques (D-109) : chiffres repris de l'Issue #317
(ca=10, pv=26, attaque_bonus=+3, degats="4 (1d6+1)"), nom et slug fictifs.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import dnd5e_engine  # noqa: F401
except ImportError:
    print("SKIP: dnd5e-engine not installed (pip install -r requirements.txt)")
    sys.exit(0)

from coderain.memory import Entry, Library
from coderain.rules_engine.monster_bridge import brute_template_slug

import mcp_server

root = os.path.join(tempfile.gettempdir(), "se_start_combat_membre_slug_i317")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
slug = lib.saves.create(
    "StartCombatMembreSlug", mode="rpg",
    premise="Banc synthétique I-317, D-109 — aucun matériau réel.")
store = lib.store(slug)

CREATURE_SLUG = "reflet-ensanglante-banc"
CREATURE_STATS = {"nom": "Reflet ensanglanté (banc)", "ca": 10, "pv": 26,
                  "attaque_bonus": 3, "degats": "4 (1d6+1)"}
store.upsert_entry("characters.md", Entry(
    title=str(CREATURE_STATS["nom"]), slug=CREATURE_SLUG, importance=4,
    attrs={"importance": "4"},
    body=json.dumps(CREATURE_STATS, ensure_ascii=False, indent=1)))

mcp_server._engine = None
mcp_server._store = store
mcp_server._slug = slug
mcp_server._last_applied_events = None
mcp_server._saves_root = lib.saves.dir(slug).parent

KAEL = {"entity_id": "pj:kael", "name": "Kael", "initiative": 15,
        "hp_current": 12, "hp_max": 12, "ac": 10, "attack_bonus": 5,
        "strength": 16, "dexterity": 14, "constitution": 14, "zone_id": "z1",
        "equipment": ["longsword"]}


async def encounter_par_slug():
    encounter = [{"entity_id": CREATURE_SLUG, "entity_type": "Monster",
                  "name": "Reflet ensanglanté (banc)", "initiative": 8,
                  "zone_id": "z1"}]
    st = await mcp_server.start_combat(
        session_id="i317-slug", party=[KAEL], encounter=encounter,
        rng_seed=1, zones=["z1"])
    assert "error" not in st, st
    assert st["warnings"] == [], st["warnings"]
    h = st["handle_id"]
    try:
        # Le monstre a un comportement jouable : son tour produit un intent
        # NON-pass (même verdict que test_monster_bridge.py's brute_bridge_probe).
        await mcp_server.submit_intent(h, "pj:kael", {"intent_type": "pass"})
        res = await mcp_server.monster_turn(h)
        assert res["warnings"] == [], res["warnings"]
        intents = [e for e in res["events"] if e.get("type") == "intent_submitted"]
        assert intents and intents[0]["intent_type"] != "pass", intents
    finally:
        await mcp_server.end_combat(h)
    return st


st1 = asyncio.run(encounter_par_slug())
print("1) start_combat(encounter=[{entity_id: slug}]) sans monster_template_slug "
      f"=> résolu, zéro avertissement, template {brute_template_slug(CREATURE_SLUG)!r}")


async def encounter_deja_resolu():
    goblin = {"entity_id": "pnj:gob1", "entity_type": "Monster", "name": "Goblin",
             "initiative": 8, "hp_current": 7, "hp_max": 7, "ac": 15,
             "attack_bonus": 4, "damage_dice": "1d6+2", "damage_type": "slashing",
             "zone_id": "z1", "monster_template_slug": "goblin-warrior"}
    st = await mcp_server.start_combat(
        session_id="i317-deja-resolu", party=[KAEL], encounter=[goblin],
        rng_seed=1, zones=["z1"])
    assert "error" not in st, st
    assert st["warnings"] == [], st["warnings"]
    await mcp_server.end_combat(st["handle_id"])


asyncio.run(encounter_deja_resolu())
print("2) membre déjà résolu (monster_template_slug fourni) : traverse "
      "inchangé, pas de double résolution")


async def encounter_slug_inconnu():
    encounter = [{"entity_id": "personne-hors-fiche-banc",
                  "entity_type": "Monster", "name": "Personne", "initiative": 8,
                  "zone_id": "z1"}]
    return await mcp_server.start_combat(
        session_id="i317-inconnu", party=[KAEL], encounter=encounter,
        rng_seed=1, zones=["z1"])


refus = asyncio.run(encounter_slug_inconnu())
assert "error" in refus, refus
assert "unknown encounter member" in refus["error"], refus
assert "handle_id" not in refus, "un refus ne doit PAS ouvrir de combat"
print(f"3) slug sans fiche ni record => refus explicite AVANT ouverture : "
      f"{refus['error']!r}")

print("\nSTART-COMBAT-MEMBRE-SLUG TESTS PASSED")
