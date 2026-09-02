"""Issue #200 : R1 de `paquet_narrateur` n'était aveugle QU'AU sous-système
combat — `_last_applied_events` (Issue #192, D-269) n'était posé que par
`apply_envelope`, jamais par `start_combat`/`submit_intent`/`monster_turn`
(dnd5e-engine via `CombatBridge`). Un tour dont la SEULE mécanique était un
combat forçait donc `sans_mecanique=True` (littéralement exact, faussement
au sens large) et la section « Mécaniques résolues » disparaissait du paquet
en plein combat (run 20260831-202617, tours 07-08).

Bout-en-bout, fixtures 100% synthétiques (D-109) :

  1. `start_combat` seul arme déjà le signal R1 (événements d'ouverture —
     `round_started`, etc.) ;
  2. combat ouvert + un `submit_intent` résolu => `paquet_narrateur` passe
     SANS `sans_mecanique`, et la section « Mécaniques résolues » porte les
     événements du round (accumulés, pas seulement le dernier appel) ;
  3. `monster_turn` alimente lui aussi le signal.

Needs dnd5e-engine==0.3.0 installed (requirements.txt) ; saute bruyamment si
absent, même convention que `test_rules_engine.py`.
"""
from __future__ import annotations

import asyncio
import json
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

from coderain.converter import projection
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition, Record
from coderain.memory import Entry, Library
from coderain import validator as validator_mod

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


# ── partition synthétique minimale — un seul node, pas de rendu_md requis
# ici (déjà couvert par le test I-192) ─────────────────────────────────

def _manifest():
    return Manifest(titre="module factice I-200", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"],
                    hash_source="4" * 64,
                    date_conversion="2026-08-31T00:00:00+00:00",
                    version_convertisseur="test")


def _build_partition() -> Partition:
    p = Partition(_manifest())
    p.nodes.append(Node(
        "para-01", "scene", "La cour", "Un gobelin vous barre la route.",
        "scene", anchors=[(0, 40)]))
    p.records.append(Record(
        "gobelin-01", "pnj", "Gobelin",
        {"role": "adversaire", "description_md": "Un gobelin nerveux.",
         "tokens_initial": [{"node_id": "para-01", "count": 1,
                             "placement_md": "au milieu de la cour"}]},
        anchors=[(0, 40)]))
    p.aventure = None
    return p


TMP = Path(tempfile.gettempdir()) / "se_paquet_narrateur_combat_i200"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = TMP / "partition"
write_partition(_build_partition(), partition_dir)
(partition_dir / "directeur.md").write_text(
    "## Brief de direction\n\nCombat tendu, pas de répit.\n", encoding="utf-8")

lib = Library(TMP / "app")
slug = lib.create_story("Test I-200", "Une cour assiégée.")
projection.derive(partition_dir, TMP / "app", slug, corpus_dir=TMP / "corpus")
sdir = lib.saves.dir(slug)
(sdir / "module.json").write_text(
    json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
store = lib.store(slug)

mcp_server._engine = None       # pas d'Engine chargé -- le pont doit s'en passer
mcp_server._store = store
mcp_server._slug = slug
mcp_server._last_applied_events = None

state = store.world_state()
assert validator_mod.current_location(state) == "para-01", state.get("player")

# ── combattants synthétiques (D-109) ────────────────────────────────
KAEL = {"entity_id": "pj:kael", "name": "Kael", "initiative": 15,
        "hp_current": 12, "hp_max": 12, "ac": 16, "attack_bonus": 5,
        "strength": 16, "dexterity": 14, "constitution": 14, "zone_id": "z1",
        "equipment": ["longsword"]}
GOBLIN = {"entity_id": "pnj:gob1", "entity_type": "Monster", "name": "Goblin",
          "initiative": 8, "hp_current": 7, "hp_max": 7, "ac": 15,
          "attack_bonus": 4, "damage_dice": "1d6+2", "damage_type": "slashing",
          "zone_id": "z1", "monster_template_slug": "goblin-warrior"}


section("1) start_combat seul arme déjà le signal R1")
started = asyncio.run(mcp_server.start_combat(
    session_id="i200-test", party=[KAEL], encounter=[GOBLIN],
    rng_seed=1337, zones=["z1"]))
handle = started["handle_id"]
assert mcp_server._last_applied_events, \
    "start_combat aurait dû armer _last_applied_events"
assert any(e.startswith("combat:") for e in mcp_server._last_applied_events)
print(f"  OK : {len(mcp_server._last_applied_events)} événement(s) d'ouverture armés")

section("2) paquet_narrateur passe SANS sans_mecanique après un combat ouvert")
result = mcp_server.paquet_narrateur(
    "Angle : le gobelin recule, terrifié.", "Je dégaine mon épée.")
assert "path" in result
texte = Path(result["path"]).read_text(encoding="utf-8")
assert "Mécaniques résolues" in result["sections"]
assert "MÉCANIQUES RÉSOLUES CE TOUR" in texte
assert "combat:" in texte
print("  OK : R1 passe sans sans_mecanique, section Mécaniques résolues présente")

section("3) submit_intent puis monster_turn alimentent le signal — accumulation")
mcp_server._last_applied_events = None
# lecture live directement via le pont (même contrat que test_rules_engine.py)
bridge = mcp_server.get_bridge()
live_view = bridge.live(handle)
assert live_view["active_actor_id"] == "pj:kael"  # initiative 15 > 8, Kael d'abord
asyncio.run(mcp_server.submit_intent(
    handle_id=handle, actor_id="pj:kael",
    intent={"intent_type": "attack", "target_id": "pnj:gob1",
            "weapon_id": "longsword"}))
after_intent = len(mcp_server._last_applied_events or [])
assert after_intent > 0, "submit_intent aurait dû armer _last_applied_events"

live_view = bridge.live(handle)
if not live_view["ended"] and live_view["active_actor_id"] == "pnj:gob1":
    asyncio.run(mcp_server.monster_turn(handle_id=handle))
n_events = len(mcp_server._last_applied_events)
assert n_events >= after_intent, \
    "les événements du round devraient s'accumuler, pas s'écraser"
print(f"  OK : {n_events} événements de combat accumulés sur le round")

section("4) paquet_narrateur porte les événements du round accumulés")
result2 = mcp_server.paquet_narrateur(
    "Angle : le duel tourne au corps-à-corps.", "Je frappe.")
texte2 = Path(result2["path"]).read_text(encoding="utf-8")
assert "Mécaniques résolues" in result2["sections"]
for e in mcp_server._last_applied_events:
    assert e in texte2, f"événement de combat absent du paquet : {e!r}"
print("  OK : tous les événements accumulés du round sont dans le paquet")

asyncio.run(mcp_server.end_combat(handle))

print(f"\nOK test-paquet-narrateur-combat-i200 — {len(FAIT)} sections vertes")
