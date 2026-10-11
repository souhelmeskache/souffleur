"""Chantier 6 (I-28, Souffleur) : `end_combat` réconcilie la save.

Défaut mesuré au chantier 5 (`test-mcp-double-voie-des-i12-chantier5.py`,
dés fixés) : après un `attack()` natif (voie `coderain/modules/rpg.py`), le
gobelin a 16 PV dans `store.rpg_state()["enemies"]` ; un combat tactique
(`start_combat`/`submit_intent`/`monster_turn`) le ramène à 10 dans
`live()["tracked_hp"]` ; après `end_combat`, la save disait ENCORE 16, et
l'`attack()` suivant repartait de 16. Cause : `end_combat`
(`coderain/mcp/jets_combat.py`) clôturait le combat sans rien écrire dans
l'état joué — le pont `engine_bridge.py` reste lui-même sans accès à la
save (Grep `rpg_state` sous `coderain/rules_engine/` : zéro résultat,
inchangé par ce chantier).

Fixtures 100% synthétiques (D-109), hors ligne. Quatre scénarios, chacun
son propre combat (store partagé, état RPG réinitialisé entre deux) :

  1) cas I-28 lui-même : `attack` natif -> combat tactique -> `end_combat`
     -> la save porte les PV du moteur ; l'`attack` suivant repart de ces
     PV (jamais des PV stale d'avant combat).
  2) un ennemi déjà connu de la save, achevé en combat tactique, sort de
     `rpg_state()["enemies"]` comme après un `attack` mortel
     (`defeated: true`).
  3) un ennemi encore inconnu de la save y entre avec ses PV de fin ET son
     hp_max (jamais deviné — lu sur la spec résolue de l'encounter).
  4) les PV du joueur perdus en combat tactique reviennent dans
     `rpg_state()["player"]["hp"]` ; à 0, le `downed` de D-271 s'applique
     de lui-même (guichet `apply_envelope`, jamais réimplémenté ici).
  (2) et (3) partagent un seul combat, avec en prime un second membre de
  party qui n'est pas le joueur : il sort dans `skipped`, rien n'est écrit
  pour lui (cas 5 de la consigne).
  6) sans save chargée (`mcp_server._store` nul), `end_combat` clôt comme
     avant et rend `reconciled: null`, sans exception.

Needs dnd5e-engine (requirements.txt) ; saute bruyamment si absent, même
convention que `test_rules_engine.py`/`test-mcp-double-voie-des-i12-chantier5.py`.
"""
from __future__ import annotations

import asyncio
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
    print("SKIP test-mcp-fin-combat-reconciliation-i28-chantier6 : "
         "dnd5e-engine non installé (pip install -r requirements.txt)")
    sys.exit(0)

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


TMP = Path(tempfile.gettempdir()) / "se_fin_combat_reconciliation_i28_chantier6"
if TMP.exists():
    shutil.rmtree(TMP)

try:
    lib = Library(TMP / "app")
    slug = lib.saves.create(
        "Chantier6-I28", mode="rpg",
        premise="Réconciliation PV end_combat, D-109 — aucun matériau de "
                "campagne réel.")
    store = lib.store(slug)
    assert store.mode() == "rpg" and store.rpg_enabled()

    mcp_server._engine = None       # régime dégradé — même convention que
                                     # test-mcp-double-voie-des-i12-chantier5
    mcp_server._store = store
    mcp_server._slug = slug
    mcp_server._last_applied_events = None

    bridge = mcp_server.get_bridge()

    # ======================================================================
    # Scénario 1 — le cas d'I-28 lui-même, patron EXACT du chantier 5
    # ======================================================================
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
    rpg["player"]["conditions"] = []
    rpg["inventory"] = {"epee-factice": {"qty": 1, "equipped": True}}
    rpg["enemies"] = {}
    rpg["seed"], rpg["rolls"] = 7, 0
    store.set_rpg_state(rpg)

    r_attack1 = mcp_server.attack(attacker="player", target="gobelin-test")
    assert "error" not in r_attack1, r_attack1
    assert r_attack1["hit"] is True, \
        f"CA posée à 1 : le toucher doit être garanti -> {r_attack1}"
    hp_monstre_1 = store.rpg_state()["enemies"]["gobelin-test"]["hp"]
    section(f"1a) attack(player -> gobelin-test) natif, toucher garanti -> "
           f"PV save = {hp_monstre_1}")

    PLAYER_SPEC = {"entity_id": "pj:player", "name": "Player",
                  "initiative": 20, "hp_current": 20, "hp_max": 20,
                  "ac": 12, "attack_bonus": 5, "strength": 16,
                  "dexterity": 14, "constitution": 14, "zone_id": "z1",
                  "equipment": ["longsword"]}
    combat1 = asyncio.run(mcp_server.start_combat(
        session_id="chantier6-i28-1", party=[PLAYER_SPEC],
        encounter=[{"entity_id": "gobelin-test", "zone_id": "z1",
                   "initiative": 8, "hp_current": hp_monstre_1}],
        rng_seed=7, zones=["z1"]))
    assert "error" not in combat1, combat1
    handle1 = combat1["handle_id"]
    assert combat1["live"]["tracked_hp"]["gobelin-test"] == hp_monstre_1

    asyncio.run(mcp_server.submit_intent(
        handle1, "pj:player",
        {"intent_type": "attack", "target_id": "gobelin-test",
         "weapon_id": "longsword"}))
    r_monster = asyncio.run(mcp_server.monster_turn(handle1))
    hp_engine_final = r_monster["live"]["tracked_hp"]["gobelin-test"]
    assert hp_engine_final < hp_monstre_1, \
        (f"le combat tactique doit avoir retiré des PV supplémentaires -> "
         f"avant={hp_monstre_1}, après={hp_engine_final}")
    section(f"1b) combat tactique : PV gobelin {hp_monstre_1} -> "
           f"{hp_engine_final} (moteur 5e, live())")

    fin1 = asyncio.run(mcp_server.end_combat(handle1))
    assert "outcome" in fin1 and "events" in fin1, fin1
    recon1 = fin1["reconciled"]
    assert recon1 is not None, fin1
    assert recon1["enemies"]["gobelin-test"] == {
        "hp_before": hp_monstre_1, "hp_after": hp_engine_final,
        "defeated": False}, recon1
    save_apres_1 = store.rpg_state()["enemies"]["gobelin-test"]["hp"]
    assert save_apres_1 == hp_engine_final, (
        f"I-28 : la save devrait porter les PV du moteur ({hp_engine_final}) "
        f"et non les PV stale d'avant combat ({hp_monstre_1}) -> {save_apres_1}")
    section(f"1c) end_combat -> reconciled['enemies']['gobelin-test'] = "
           f"{recon1['enemies']['gobelin-test']} ; save = {save_apres_1} "
           "(AVANT ce correctif, mesuré au chantier 5 : la save restait "
           f"bloquée à {hp_monstre_1})")

    r_attack2 = mcp_server.attack(attacker="player", target="gobelin-test")
    assert "error" not in r_attack2, r_attack2
    if r_attack2["hit"]:
        attendu = max(0, hp_engine_final - r_attack2["damage"]["total"])
        e = store.rpg_state()["enemies"].get("gobelin-test")
        if attendu <= 0:
            assert e is None, (e, attendu)
        else:
            assert e["hp"] == attendu, (e, attendu)
    section("1d) l'attack natif suivant repart des PV réconciliés, pas des "
           "PV stale d'avant combat")

    # ======================================================================
    # Scénarios 2+3+5 — ennemi connu achevé (defeated), ennemi inconnu qui
    # entre avec son hp_max, membre de party qui n'est pas le joueur (skipped)
    # ======================================================================
    store.upsert_entry("characters.md", Entry(
        title="Ennemi connu (banc)", slug="ennemi-connu-banc", importance=2,
        attrs={"ca": "1", "pv": "40", "attaque_bonus": "0",
              "degats": "1d4+1"},
        body="Créature synthétique de test (D-109)."))
    store.upsert_entry("characters.md", Entry(
        title="Ennemi inconnu (banc)", slug="ennemi-inconnu-banc",
        importance=2,
        attrs={"ca": "1", "pv": "30", "attaque_bonus": "0",
              "degats": "1d4+1"},
        body="Créature synthétique de test (D-109)."))

    rpg = store.rpg_state()
    rpg["player"]["hp"], rpg["player"]["hp_max"] = 20, 20
    rpg["player"]["conditions"] = []
    # ennemi-connu-banc est déjà DANS la save (hp très bas, écrira
    # 0 PV == tué dès le premier coup du combat tactique) ; ennemi-inconnu-
    # banc N'Y EST PAS — c'est tout l'objet du cas 3.
    rpg["enemies"] = {"ennemi-connu-banc": {"hp": 3, "hp_max": 40}}
    rpg["seed"], rpg["rolls"] = 11, 0
    store.set_rpg_state(rpg)

    PLAYER_SPEC_2 = {"entity_id": "pj:player", "name": "Player",
                     "initiative": 20, "hp_current": 20, "hp_max": 20,
                     # CA à 30 : les ennemis (attaque_bonus=0) ne peuvent
                     # JAMAIS toucher le joueur ni son compagnon (d20+0 max
                     # 20 < 30) — ce scénario ne teste pas les PV du joueur
                     # (cas 4, scénario séparé plus bas).
                     "ac": 30, "attack_bonus": 15, "strength": 16,
                     "dexterity": 14, "constitution": 14, "zone_id": "z1",
                     "equipment": ["longsword"]}
    COMPAGNON_SPEC = {"entity_id": "pj:ami", "name": "Compagnon",
                      "initiative": 15, "hp_current": 10, "hp_max": 10,
                      "ac": 30, "attack_bonus": 0, "strength": 10,
                      "dexterity": 10, "constitution": 10, "zone_id": "z1",
                      "equipment": []}
    combat2 = asyncio.run(mcp_server.start_combat(
        session_id="chantier6-i28-2", party=[PLAYER_SPEC_2, COMPAGNON_SPEC],
        encounter=[
            {"entity_id": "ennemi-connu-banc", "zone_id": "z1",
             "initiative": 10, "hp_current": 3},
            {"entity_id": "ennemi-inconnu-banc", "zone_id": "z1",
             "initiative": 5, "hp_current": 30},
        ],
        rng_seed=11, zones=["z1"]))
    assert "error" not in combat2, combat2
    handle2 = combat2["handle_id"]

    for _ in range(8):
        live = bridge.live(handle2)
        if live["ended"]:
            break
        actif = live["active_actor_id"]
        if actif == "pj:player":
            # cible l'ennemi connu en premier (l'achève, hp=3 contre des
            # dégâts d'épée longue >= 4), puis l'inconnu — jamais les deux
            # dans le même tour.
            cible = ("ennemi-connu-banc"
                    if (live["tracked_hp"].get("ennemi-connu-banc", 0) > 0
                        and "ennemi-connu-banc" not in live["dead_ids"])
                    else "ennemi-inconnu-banc")
            asyncio.run(mcp_server.submit_intent(
                handle2, "pj:player",
                {"intent_type": "attack", "target_id": cible,
                 "weapon_id": "longsword"}))
        elif actif == "pj:ami":
            asyncio.run(mcp_server.submit_intent(
                handle2, "pj:ami", {"intent_type": "pass"}))
        else:
            asyncio.run(mcp_server.monster_turn(handle2))

    live2 = bridge.live(handle2)
    assert "ennemi-connu-banc" in live2["dead_ids"], live2
    assert 0 < live2["tracked_hp"]["ennemi-inconnu-banc"] < 30, live2
    section(f"2/3) combat tactique : ennemi connu tué "
           f"(dead_ids={live2['dead_ids']}), ennemi inconnu endommagé "
           f"({live2['tracked_hp']['ennemi-inconnu-banc']}/30)")

    fin2 = asyncio.run(mcp_server.end_combat(handle2))
    recon2 = fin2["reconciled"]
    assert recon2 is not None, fin2

    # cas 2 : l'ennemi connu, achevé, sort de rpg_state()["enemies"].
    assert recon2["enemies"]["ennemi-connu-banc"]["defeated"] is True, recon2
    assert recon2["enemies"]["ennemi-connu-banc"]["hp_after"] == 0, recon2
    assert "ennemi-connu-banc" not in (store.rpg_state().get("enemies") or {}), \
        store.rpg_state().get("enemies")
    section("2) end_combat -> ennemi connu achevé = defeated:true, sorti de "
           "rpg_state()['enemies'] (comme après un attack mortel)")

    # cas 3 : l'ennemi inconnu entre avec ses PV de fin ET son hp_max.
    hp_final_inconnu = live2["tracked_hp"]["ennemi-inconnu-banc"]
    assert recon2["enemies"]["ennemi-inconnu-banc"] == {
        "hp_before": 30, "hp_after": hp_final_inconnu,
        "defeated": False}, recon2
    e_inconnu_save = store.rpg_state()["enemies"]["ennemi-inconnu-banc"]
    assert e_inconnu_save == {"hp": hp_final_inconnu, "hp_max": 30}, \
        e_inconnu_save
    section(f"3) end_combat -> ennemi inconnu entre dans la save avec PV="
           f"{hp_final_inconnu} et hp_max=30 (jamais deviné, lu sur la "
           "spec résolue de l'encounter)")

    # cas 5 : le compagnon (party, pas le joueur) est skipped, rien d'écrit.
    assert recon2["skipped"] == ["pj:ami"], recon2
    section("5) end_combat -> le compagnon (party, pas le joueur) revient "
           "sous 'skipped', rien n'est écrit pour lui")

    # ======================================================================
    # Scénario 4 — PV du joueur perdus en combat tactique -> rpg_state() ;
    # à 0, downed (guichet apply_envelope, pas réimplémenté ici)
    # ======================================================================
    rpg = store.rpg_state()
    rpg["player"]["hp"], rpg["player"]["hp_max"] = 10, 20
    rpg["player"]["conditions"] = []
    rpg["enemies"] = {}
    rpg["seed"], rpg["rolls"] = 1, 0
    store.set_rpg_state(rpg)

    store.upsert_entry("characters.md", Entry(
        title="Brute (banc)", slug="brute-banc", importance=2,
        attrs={"ca": "20", "pv": "50", "attaque_bonus": "20",
              "degats": "4d6+10"},
        body="Créature synthétique de test (D-109)."))

    PLAYER_SPEC_4 = {"entity_id": "pj:player", "name": "Player",
                     "initiative": 1, "hp_current": 10, "hp_max": 10,
                     # CA à 1, attaque_bonus de la brute à 20 (fiche
                     # ci-dessus) : d20+20 >= 1 TOUJOURS — toucher garanti
                     # quel que soit le jet, même convention que (1a).
                     "ac": 1, "attack_bonus": 1, "strength": 16,
                     "dexterity": 10, "constitution": 10, "zone_id": "z1",
                     "equipment": []}
    combat4 = asyncio.run(mcp_server.start_combat(
        session_id="chantier6-i28-4", party=[PLAYER_SPEC_4],
        encounter=[{"entity_id": "brute-banc", "zone_id": "z1",
                   "initiative": 20, "hp_current": 50}],
        rng_seed=1, zones=["z1"]))
    assert "error" not in combat4, combat4
    handle4 = combat4["handle_id"]

    # Graine et chiffres choisis au banc (sondage hors dépôt, jamais commis) :
    # CA du joueur posée à 1 et attaque_bonus de la brute à 20 rendent le
    # toucher garanti PAR ARITHMÉTIQUE (min d20+20=21 >= CA 1), donc
    # reproductible pour toute graine — rng_seed=1 fixé ici comme ailleurs
    # dans ce fichier. Le joueur passe son tour, la brute agit : 6 cycles
    # suffisent largement à un coup, qui seul ramène ses 10 PV à 0 (dégâts
    # minimum 4d6+10 = 14 > 10).
    for _ in range(6):
        live4 = bridge.live(handle4)
        if live4["ended"]:
            break
        if live4["active_actor_id"] == "pj:player":
            asyncio.run(mcp_server.submit_intent(
                handle4, "pj:player", {"intent_type": "pass"}))
        else:
            asyncio.run(mcp_server.monster_turn(handle4))

    live4 = bridge.live(handle4)
    hp_joueur_moteur = live4["tracked_hp"]["pj:player"]
    assert hp_joueur_moteur <= 0, \
        f"la brute devait avoir touché le joueur -> {live4}"
    section(f"4a) combat tactique : PV joueur 10 -> {hp_joueur_moteur} "
           "(côté moteur, live())")

    fin4 = asyncio.run(mcp_server.end_combat(handle4))
    recon4 = fin4["reconciled"]
    assert recon4 is not None, fin4
    assert recon4["player"]["hp_before"] == 10, recon4
    assert recon4["player"]["hp_after"] == 0, recon4
    rpg_apres_4 = store.rpg_state()
    assert rpg_apres_4["player"]["hp"] == 0, rpg_apres_4["player"]
    assert "downed" in rpg_apres_4["player"]["conditions"], \
        rpg_apres_4["player"]
    section("4b) end_combat -> rpg_state()['player']['hp'] == 0, "
           "'downed' posé par le guichet apply_envelope (D-271), pas "
           "réimplémenté ici")

    # ======================================================================
    # Scénario 6 — sans save chargée : reconciled est nul, pas d'exception
    # ======================================================================
    mcp_server._store = None
    PLAYER_SPEC_6 = {"entity_id": "pj:player", "name": "Player",
                     "initiative": 10, "hp_current": 10, "hp_max": 10,
                     "ac": 15, "attack_bonus": 3, "strength": 10,
                     "dexterity": 10, "constitution": 10, "zone_id": "z1",
                     "equipment": []}
    MONSTRE_6 = {"entity_id": "mob-sans-save", "entity_type": "Monster",
                 "name": "Mob", "initiative": 5, "hp_current": 5,
                 "hp_max": 5, "ac": 10, "attack_bonus": 2,
                 "damage_dice": "1d4", "damage_type": "bludgeoning",
                 "zone_id": "z1", "monster_template_slug": "goblin-warrior"}
    combat6 = asyncio.run(mcp_server.start_combat(
        session_id="chantier6-i28-6", party=[PLAYER_SPEC_6],
        encounter=[MONSTRE_6], rng_seed=1, zones=["z1"]))
    assert "error" not in combat6, combat6
    fin6 = asyncio.run(mcp_server.end_combat(combat6["handle_id"]))
    assert "outcome" in fin6, fin6
    assert fin6["reconciled"] is None, fin6
    section("6) sans save chargée (_store nul) : end_combat clôt sans "
           "erreur, reconciled est null")

    print(f"\nOK test-mcp-fin-combat-reconciliation-i28-chantier6 — "
         f"{len(FAIT)} sections vertes")
finally:
    mcp_server._engine = None
    mcp_server._store = None
    mcp_server._slug = ""
    mcp_server._last_applied_events = None
    shutil.rmtree(TMP, ignore_errors=True)
