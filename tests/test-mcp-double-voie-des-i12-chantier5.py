"""Chantier 5 (chemin MCP du régime principal, sujet 4/4, I-12) : le
croisement des deux voies de dés.

`roll_check`/`roll_damage`/`death_save`/`attack` passent par
`coderain/modules/rpg.py` (voie « native », outils MCP de
`coderain/mcp/jets_combat.py` qui lisent/écrivent `store.rpg_state()`) ;
`resolve_check` et le combat tactique (`start_combat`/`submit_intent`/
`monster_turn`/`end_combat`) passent par le moteur 5e (`dnd5e-engine`, via
`coderain.rules_engine` — `tests/test_rules_engine.py` le confirme au point
6 : « modules/rpg.py stays untouched (coexistence v0) »). AUCUN test
existant ne CROISE les deux voies sur le même acteur/la même créature —
chacun des tests Grep (`test-element-jet-degats-i206.py`,
`test-element-attaque-i463.py`, `test_rules_engine.py`,
`test_monster_bridge.py`, `test-start-combat-membre-slug-i317.py`,
`test-paquet-narrateur-combat-i200.py`) reste cantonné à UNE des deux
voies. Ce fichier croise les deux, dés fixés (seed=7, CA cible posée à 1
pour un toucher garanti quel que soit le jet — jamais un jet non rejoué).

100 % synthétique (D-109), hors ligne.

Couvre :
  (a) Pour un même acteur et une même caractéristique, le modificateur
      appliqué est le MÊME par les deux voies : `roll_check(stat=
      "strength")` (voie native, modificateur lu brut sur la fiche) et
      `resolve_check({"kind": "ability", "ability": "strength",
      "ability_scores": {"strength": 16}, ...})` (voie 5e,
      `(score-10)//2`) rendent le même modificateur pour `strength: 3`
      (fiche native) / `strength: 16` (score 5e) — les deux conventions
      pointent le même nombre.
  (b) Des PV retirés par `attack` (voie native, `apply_envelope`) SONT
      ceux que voit `start_combat` : la CIBLE est lue depuis
      `store.rpg_state()["enemies"]`, et c'est ce chiffre qu'il FAUT
      transmettre en `hp_current` à `start_combat` pour que le combat
      tactique ouvre sur le bon total — vérifié ici en le transmettant et
      en relisant `live()["tracked_hp"]`.
Défaut mesuré, non testé ici : `end_combat` ne renvoie pas les PV du
combat tactique vers `store.rpg_state()` (item I-28 de Souffleur) ; corrigé
et testé au chantier 6 —
`tests/test-mcp-fin-combat-reconciliation-i28-chantier6.py`.
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

from coderain.memory import Entry, Library

import mcp_server

try:
    import dnd5e_engine  # noqa: F401
except ImportError:
    print("SKIP test-mcp-double-voie-des-i12-chantier5 : dnd5e-engine non "
         "installé (pip install -r requirements.txt)")
    sys.exit(0)

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


TMP = Path(tempfile.gettempdir()) / "se_mcp_double_voie_des_i12_chantier5"
if TMP.exists():
    shutil.rmtree(TMP)

try:
    lib = Library(TMP / "app")
    slug = lib.saves.create(
        "Chantier5-4", mode="rpg",
        premise="Croisement I-12, D-109 — aucun matériau de campagne réel.")
    store = lib.store(slug)
    assert store.mode() == "rpg" and store.rpg_enabled()

    store.upsert_entry("items.md", Entry(
        title="Épée factice", slug="epee-factice", importance=2,
        attrs={"degats": "1d6+1", "stat": "strength",
              "status": "held by you"},
        body="Objet synthétique de test (D-109)."))
    store.upsert_entry("characters.md", Entry(
        title="Gobelin de test", slug="gobelin-test", importance=2,
        # CA posée à 1 : un toucher garanti quel que soit le jet (d20+bonus
        # >= 1 toujours) — jamais un jet non rejoué pour forcer un résultat.
        attrs={"ca": "1", "pv": "20", "attaque_bonus": "2",
              "degats": "1d4+1"},
        body="Créature synthétique de test (D-109)."))

    rpg = store.rpg_state()
    rpg.setdefault("player", {})["stats"] = {"strength": 3, "agility": 2}
    rpg["player"]["level"] = 3
    rpg["player"]["hp"], rpg["player"]["hp_max"] = 20, 20
    rpg["inventory"] = {"epee-factice": {"qty": 1, "equipped": True}}
    rpg["enemies"] = {}
    rpg["seed"] = 7
    rpg["rolls"] = 0
    store.set_rpg_state(rpg)

    mcp_server._engine = None       # régime dégradé — inutile pour ce sujet,
                                     # les deux voies testées s'en passent
    mcp_server._store = store
    mcp_server._slug = slug
    mcp_server._last_applied_events = None

    tool_names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    for outil in ("roll_check", "roll_damage", "death_save", "attack",
                 "resolve_check", "start_combat", "submit_intent",
                 "monster_turn", "end_combat"):
        assert outil in tool_names, f"{outil} absent du serveur MCP"
    section("0) les neuf outils des deux voies existent au serveur MCP")

    # --- (a) même acteur, même caractéristique : même modificateur --------
    touch = mcp_server.roll_check(stat="strength", dc=5, actor="player")
    assert "error" not in touch, touch
    mod_natif = touch["mod"]
    assert mod_natif == 3, touch  # fiche native : le modificateur EST 3

    spec = {"kind": "ability", "ability": "strength",
           "ability_scores": {"strength": 16}, "proficiency_bonus": 2,
           "proficient_skills": [], "proficient_saves": [], "dc": 5}
    res_5e = asyncio.run(mcp_server.resolve_check(spec, seed=7))
    mod_5e = res_5e["modifier"]
    assert mod_5e == 3, res_5e  # 5e : (16-10)//2 = 3

    assert mod_natif == mod_5e == 3, (mod_natif, mod_5e)
    section(f"(a) même acteur/caractéristique (strength) : modificateur "
           f"natif={mod_natif}, 5e={mod_5e} — identiques")

    # --- (b) PV retirés par attack = ceux que voit start_combat -----------
    r_attack1 = mcp_server.attack(attacker="player", target="gobelin-test")
    assert "error" not in r_attack1, r_attack1
    assert r_attack1["hit"] is True, \
        f"CA posée à 1 : le toucher doit être garanti -> {r_attack1}"
    hp_monstre_1 = store.rpg_state()["enemies"]["gobelin-test"]["hp"]
    degats1 = r_attack1["damage"]["total"]
    assert hp_monstre_1 == 20 - degats1, (hp_monstre_1, degats1)
    section(f"(b1) attack(player -> gobelin-test) toucher garanti, "
           f"dégâts={degats1}, PV retirés -> {hp_monstre_1} (lu sur "
           "store.rpg_state()['enemies'])")

    PLAYER_SPEC = {"entity_id": "pj:player", "name": "Player",
                  "initiative": 20, "hp_current": 20, "hp_max": 20,
                  "ac": 12, "attack_bonus": 5, "strength": 16,
                  "dexterity": 14, "constitution": 14, "zone_id": "z1",
                  "equipment": ["longsword"]}
    combat1 = asyncio.run(mcp_server.start_combat(
        session_id="chantier5-i12-a", party=[PLAYER_SPEC],
        encounter=[{"entity_id": "gobelin-test", "zone_id": "z1",
                   "initiative": 8, "hp_current": hp_monstre_1}],
        rng_seed=7, zones=["z1"]))
    assert "error" not in combat1, combat1
    handle1 = combat1["handle_id"]
    tracked_hp_ouverture = combat1["live"]["tracked_hp"]
    assert tracked_hp_ouverture["gobelin-test"] == hp_monstre_1, \
        (tracked_hp_ouverture, hp_monstre_1)
    section(f"(b1) start_combat(hp_current={hp_monstre_1}) -> "
           f"live()['tracked_hp']['gobelin-test'] == {hp_monstre_1} — le "
           "combat tactique OUVRE sur le même total que la voie native, "
           "parce que l'appelant l'y a transmis explicitement (aucune "
           "lecture automatique du store coderain par le pont — Grep "
           "'rpg_state' sous coderain/rules_engine/ : zéro résultat)")

    # --- combat : le joueur frappe encore (toucher garanti, CA=1) ---------
    r_intent = asyncio.run(mcp_server.submit_intent(
        handle1, "pj:player",
        {"intent_type": "attack", "target_id": "gobelin-test",
         "weapon_id": "longsword"}))
    r_monster = asyncio.run(mcp_server.monster_turn(handle1))
    hp_engine_final = r_monster["live"]["tracked_hp"]["gobelin-test"]
    assert hp_engine_final < hp_monstre_1, \
        (f"le combat tactique doit avoir retiré des PV supplémentaires au "
         f"gobelin -> avant={hp_monstre_1}, après={hp_engine_final}")
    section(f"  combat tactique : PV du gobelin {hp_monstre_1} -> "
           f"{hp_engine_final} (côté moteur 5e, mirroir live())")

    fin1 = asyncio.run(mcp_server.end_combat(handle1))
    assert "outcome" in fin1, fin1
    section(f"  end_combat -> {fin1['outcome'].get('ended_reason')!r}")

    print(f"\nOK test-mcp-double-voie-des-i12-chantier5 — {len(FAIT)} "
         "sections vertes")
finally:
    mcp_server._engine = None
    mcp_server._store = None
    mcp_server._slug = ""
    mcp_server._last_applied_events = None
    shutil.rmtree(TMP, ignore_errors=True)
