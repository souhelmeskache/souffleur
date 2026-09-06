"""Issue #317 — rejeu de mesure, critère (c) : « rejeu des tours 13 et 23 de
`bench/nuit-20260906/partie-02` (les appels d'outils y sont journalisés) :
zéro bouchage ». Le journal réel de cette partie vit dans `bench/nuit-*/`
(gitignoré, matériau de banc — D-109/D-206) et n'est jamais commité ; ce
script en rejoue la STRUCTURE mesurée avec des fixtures 100% synthétiques,
même discipline que `bench/rejeu-letalite-i463-tours21-27.py` (nom et slug
fictifs, seuls les champs mécaniques `ca`/`pv`/`attaque_bonus`/`degats`
publiés dans le constat de l'Issue #317 sont repris).

Constat : au tour 13, `start_combat` s'ouvrait sans comportement pour la
créature (aucun `monster_template_slug` résolu — #316(a)) ; au tour 23,
`attack` bouchait CA (deux fois), bonus d'attaque (+4 puis +3) et dégâts
(1d8+3 au lieu de 1d6+1) — 6 bouchages `bouchage_enregistre` au total pour
une créature dont tout était déjà connu, projeté en JSON dans le corps de
son entrée `characters.md` (converter/projection.py).

Rejeu ici :
  - tour 13 (structure) : `start_combat` avec la créature passée par slug
    seul — résolution automatique par le record, zéro avertissement ;
  - tour 23 (structure) : `attack` joueur <-> créature dans les deux sens —
    CA/bonus/dégâts lus tels quels sur le bloc projeté, zéro bouchage,
    zéro entrée neuve dans `rpg.provisoire`.

Needs dnd5e-engine==0.3.0 (requirements.txt) ; saute bruyamment si absent.
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

import mcp_server

root = os.path.join(tempfile.gettempdir(), "se_rejeu_tours_blood_man_i317")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
slug = lib.saves.create(
    "RejeuToursI317", mode="rpg",
    premise="Rejeu de mesure I-317 (#316(a)), D-109/D-206 — structure des "
            "tours 13/23 de bench/nuit-20260906/partie-02, fixture "
            "synthétique dérivée des chiffres publiés dans l'Issue #317.")
store = lib.store(slug)
assert store.mode() == "rpg" and store.rpg_enabled()

# Chiffres publiés dans le constat de l'Issue #317 (ca=10, pv=26,
# attaque_bonus=+3, degats=4 (1d6+1)) ; nom/slug fictifs (D-109).
CREATURE_SLUG = "reflet-ensanglante-banc"
CREATURE_STATS = {"nom": "Reflet ensanglanté (banc)", "ca": 10, "pv": 26,
                  "attaque_bonus": 3, "degats": "4 (1d6+1)"}
store.upsert_entry("items.md", Entry(
    title="Épée factice", slug="epee-factice", importance=2,
    attrs={"degats": "1d8+3", "stat": "strength", "status": "held by you"},
    body="Objet synthétique de test."))
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
        "hp_current": 20, "hp_max": 20, "ac": 12, "attack_bonus": 6,
        "strength": 16, "dexterity": 14, "constitution": 14, "zone_id": "z1",
        "equipment": ["longsword"]}


def _set_player(*, seed):
    rpg = store.rpg_state()
    p = rpg.setdefault("player", {})
    p["stats"] = {"strength": 3, "agility": 2}
    p["level"] = 5
    p["hp"], p["hp_max"] = 20, 20
    p["conditions"] = []
    p["death_saves"] = {"successes": 0, "failures": 0}
    rpg["inventory"] = {"epee-factice": {"qty": 1, "equipped": True}}
    rpg["enemies"] = {}
    rpg["provisoire"] = {}
    rpg["seed"], rpg["rolls"] = seed, 0
    store.set_rpg_state(rpg)
    return rpg


nb_bouchages = 0


def _nb_bouchages() -> int:
    from coderain import bouchage as bouchage_mod
    return bouchage_mod.nb_scenario(store.rpg_state())


# ---- tour 13 (structure) : start_combat, créature passée par slug seul ----
async def tour_13():
    encounter = [{"entity_id": CREATURE_SLUG, "entity_type": "Monster",
                  "name": str(CREATURE_STATS["nom"]), "initiative": 8,
                  "zone_id": "z1"}]
    st = await mcp_server.start_combat(
        session_id="i317-rejeu-tour13", party=[KAEL], encounter=encounter,
        rng_seed=1, zones=["z1"])
    assert "error" not in st, f"tour 13 : refus inattendu -> {st!r}"
    assert st["warnings"] == [], f"tour 13 : avertissement inattendu -> {st['warnings']!r}"
    await mcp_server.end_combat(st["handle_id"])


asyncio.run(tour_13())
print("tour 13 (rejeu) : start_combat résout la créature par slug -> "
      "membre jouable, zéro avertissement (comparer au constat : « aucun "
      "monster_template_slug résolu »)")

# ---- tour 23 (structure) : attack() dans les deux sens, zéro bouchage ----
_set_player(seed=7)
avant = _nb_bouchages()

joueur_attaque = mcp_server.attack(attacker="player", target=CREATURE_SLUG)
assert "error" not in joueur_attaque, f"tour 23 (joueur) : refus -> {joueur_attaque!r}"
assert "provisoire" not in joueur_attaque, (
    f"tour 23 (joueur) : bouchage inattendu -> {joueur_attaque!r}")
assert joueur_attaque["target_ac"] == 10, joueur_attaque

creature_attaque = mcp_server.attack(attacker=CREATURE_SLUG, target="player")
assert "error" not in creature_attaque, f"tour 23 (créature) : refus -> {creature_attaque!r}"
assert "provisoire" not in creature_attaque, (
    f"tour 23 (créature) : bouchage inattendu -> {creature_attaque!r}")
assert creature_attaque["attack_bonus"] == 3, creature_attaque

apres = _nb_bouchages()
assert apres == avant == 0, (
    f"tour 23 (rejeu) : {apres - avant} bouchage(s) enregistré(s) — attendu 0 "
    f"(constat : 6 mesurés sur la même créature avant #317)")

print("tour 23 (rejeu) : attack(joueur<->créature) résout dans les deux sens, "
      f"zéro bouchage (compteur scénario={apres}, constat pré-#317 : 6)")

print("\nREJEU-TOURS-BLOOD-MAN-I317 (structure tours 13/23, "
      "bench/nuit-20260906/partie-02) : OK")
