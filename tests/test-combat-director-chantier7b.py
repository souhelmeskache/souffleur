"""Chantier 7b (I-28 suite) : le Director, relancé neuf à chaque tour, joue
un combat tactique de bout en bout — moteur 5e sur le chemin principal,
Director (Claude Code branché par MCP) qui mène le combat.

Avant ce chantier : le combat tactique vivait dans un registre EN MÉMOIRE
du pont (`coderain/mcp/jets_combat.py::_combat_rosters`) — rien n'écrivait
le `handle_id` dans la save, un second `start_combat` n'était pas refusé, et
la photo du Director (`photo_director`) ne savait pas qu'un combat était
ouvert. Ce test prouve, sur une save synthétique 100% D-109 au vocabulaire
5e exact (profil de banc `guerrier-5e`, position + partition projetée) :

  1. tour 1 : `start_combat` ouvre le combat ; la photo du Director porte
     une section « Combat en cours » (handle, round, acteur courant,
     initiative, PV, morts) ; `get_world_state()` sert la même chose sous
     `combat_ouvert`.
  2. tour 2 : `submit_intent` du joueur puis `monster_turn` jusqu'au retour
     du joueur ; la photo suit les PV mis à jour ; `attack` est refusé
     (renvoie à `submit_intent`) ; un second `start_combat` est refusé (un
     seul combat à la fois).
  3. tour 3 : `end_combat` — la section disparaît de la photo, la save
     porte les PV réconciliés, `attack` redevient permis.
  4. cas de péremption : une entrée `combat` présente dans la save mais que
     le pont ne connaît plus (handle inventé, jamais ouvert par ce process)
     — la photo et `get_world_state` le disent en une ligne, et
     `start_combat` l'efface, ouvre le nouveau combat, et avertit.

Needs dnd5e-engine (requirements.txt) ; saute bruyamment si absent, même
convention que les autres tests de combat du dépôt.
"""
from __future__ import annotations

import asyncio
import importlib.util
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
    print("SKIP test-combat-director-chantier7b : dnd5e-engine non installé "
         "(pip install -r requirements.txt)")
    sys.exit(0)

from coderain.converter import projection
from coderain.converter.emit import write_partition
from coderain.converter.schemas import Manifest, Node, Partition
from coderain.memory import Entry, Library

import mcp_server

# Import du script de fixture (nom de fichier à tiret : pas un module
# importable tel quel) — même technique que test-fiche-5e-combat-chantier7a.
_spec = importlib.util.spec_from_file_location(
    "personnage_banc_7b", ROOT / "bench" / "fixtures" / "personnage-banc.py")
personnage_banc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(personnage_banc)

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def _manifest():
    return Manifest(titre="module factice chantier 7b", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"],
                    hash_source="8" * 64,
                    date_conversion="2026-10-11T00:00:00+00:00",
                    version_convertisseur="test")


def _build_partition() -> Partition:
    p = Partition(_manifest())
    p.nodes.append(Node(
        "para-01", "scene", "La salle des gardes",
        "Une brute synthétique de banc vous barre la route.",
        "scenario", anchors=[(0, 40)],
        objectif_md="Passer, par la force ou la ruse."))
    p.aventure = None
    return p


BRUTE_SLUG = "brute-banc-7b"
BRUTE_NOM = "Brute de banc (chantier 7b)"

TMP = Path(tempfile.gettempdir()) / "se_combat_director_chantier7b"
if TMP.exists():
    shutil.rmtree(TMP)
partition_dir = TMP / "partition"
write_partition(_build_partition(), partition_dir)

mcp_server._engine = None       # pas d'Engine chargé — le pont MCP seul
mcp_server._last_applied_events = None

try:
    # --- fixture : une save RPG 5e, position valide, personnage guerrier-5e
    app_dir = TMP / "app"
    lib = Library(app_dir)
    slug = lib.saves.create("Test chantier 7b", premise="Une salle des gardes.",
                            mode="rpg")
    (lib.saves.dir(slug) / "module.json").write_text(
        json.dumps({"partition": str(partition_dir)}), encoding="utf-8")
    projection.derive(partition_dir, app_dir, slug, corpus_dir=TMP / "corpus")

    res_install = personnage_banc.install(lib.saves.dir(slug), profil="guerrier-5e")
    assert res_install["status"] == "installed", res_install

    store = lib.store(slug)  # ré-ouverture : lit la fixture fraîchement écrite

    # Un adversaire non-SRD (record de module absent), résolu par slug
    # (`_resolve_encounter_member`) — CA posée à 1 : le coup d'épée longue du
    # joueur touche toujours ; PV hauts (50) : survit largement aux deux
    # coups que ce test lui porte, jamais une mort qui romprait le
    # déroulement prévu des trois tours.
    store.upsert_entry("characters.md", Entry(
        title=BRUTE_NOM, slug=BRUTE_SLUG, importance=2,
        attrs={"ca": "1", "pv": "50", "attaque_bonus": "0",
              "degats": "1d4+1"},
        body="Créature synthétique de test (D-109)."))

    mcp_server._store = store
    mcp_server._slug = slug
    mcp_server._last_applied_events = None
    # `load_save` ferait ceci lui-même (vocabulaire 5e exact de la fiche) —
    # reproduit ici, même convention que test-fiche-5e-combat-chantier7a.
    mcp_server._rpg_cfg = dict(mcp_server._DEFAULT_RPG)
    mcp_server._rpg_cfg["stats"] = ["strength", "dexterity", "constitution",
                                    "intelligence", "wisdom", "charisma"]

    rpg0 = store.rpg_state()
    rpg0["seed"], rpg0["rolls"] = 7, 0
    store.set_rpg_state(rpg0)

    # Position valide (I-219) + partition projetée — condition d'eligible()
    # pour le chemin position, donc pour photo_director.
    state0 = store.world_state()
    state0.setdefault("player", {})["location"] = "para-01"
    store.set_world_state(state0)
    assert mcp_server.assembleur_position.eligible(store, store.world_state()), \
        "la save devrait être éligible au chemin position (photo_director)"

    bridge = mcp_server.get_bridge()
    NOM_JOUEUR = "Rhodri Ashvale"

    # ======================================================================
    # Tour 1 — start_combat ouvre le combat ; la photo le porte
    # ======================================================================
    combat = asyncio.run(mcp_server.start_combat(
        session_id="chantier7b-tour1",
        party=[{"entity_id": "player", "zone_id": "z1", "initiative": 20}],
        encounter=[{"entity_id": BRUTE_SLUG, "zone_id": "z1",
                   "initiative": 5, "hp_current": 50}],
        rng_seed=7, zones=["z1"]))
    assert "error" not in combat, combat
    handle = combat["handle_id"]
    assert combat["live"]["active_actor_id"] == "player", combat["live"]
    section(f"1a) start_combat -> handle={handle!r}, c'est le tour du "
           "joueur (initiative 20 > 5)")

    photo1 = mcp_server.photo_director("J'engage le combat contre la brute.")
    texte1 = Path(photo1["path"]).read_text(encoding="utf-8")
    assert "## Combat en cours" in texte1, \
        f"section « Combat en cours » absente -> {texte1[:6000]!r}"
    assert f"Handle : {handle}" in texte1, texte1
    assert "Round : 1" in texte1, texte1
    assert (f"Tour : {NOM_JOUEUR} (player) — c'est le tour du personnage "
           "joué.") in texte1, texte1
    assert f"Ordre d'initiative : {NOM_JOUEUR} (player), {BRUTE_NOM} " \
          f"({BRUTE_SLUG})" in texte1, texte1
    assert f"- {NOM_JOUEUR} (player) : 12 PV — aucun état" in texte1, texte1
    assert f"- {BRUTE_NOM} ({BRUTE_SLUG}) : 50 PV — aucun état" in texte1, texte1
    assert "Morts : (aucun)" in texte1, texte1
    section("1b) photo_director : « Combat en cours » porte handle, round, "
           "tour du joueur, initiative, PV, aucun mort")

    monde1 = mcp_server.get_world_state()
    co1 = monde1.get("combat_ouvert")
    assert co1 is not None, monde1
    assert co1["handle_id"] == handle and co1["stale"] is False, co1
    assert co1["round"] == 1 and co1["is_player_turn"] is True, co1
    assert co1["active_actor"] == {"entity_id": "player", "name": NOM_JOUEUR}, co1
    assert co1["hp"] == {"player": 12, BRUTE_SLUG: 50}, co1
    assert co1["dead"] == [], co1
    section("1c) get_world_state()['combat_ouvert'] sert le même état")

    # ======================================================================
    # Tour 2 — submit_intent + monster_turn ; attack et start_combat refusés
    # ======================================================================
    asyncio.run(mcp_server.submit_intent(
        handle, "player",
        {"intent_type": "attack", "target_id": BRUTE_SLUG,
         "weapon_id": "longsword"}))
    live_apres_joueur = bridge.live(handle)
    hp_brute_apres = live_apres_joueur["tracked_hp"][BRUTE_SLUG]
    assert hp_brute_apres < 50, \
        f"CA posée à 1 : le coup d'épée longue doit toucher -> {live_apres_joueur}"

    while bridge.live(handle)["active_actor_id"] != "player" \
            and not bridge.live(handle)["ended"]:
        asyncio.run(mcp_server.monster_turn(handle))
    live2 = bridge.live(handle)
    assert live2["active_actor_id"] == "player" and not live2["ended"], live2
    hp_joueur_apres = live2["tracked_hp"]["player"]
    section(f"2a) submit_intent(attack) + monster_turn jusqu'au retour du "
           f"joueur : PV brute 50 -> {hp_brute_apres}, PV joueur 12 -> "
           f"{hp_joueur_apres}, round={live2['round_number']}")

    photo2 = mcp_server.photo_director("Je presse mon avantage.")
    texte2 = Path(photo2["path"]).read_text(encoding="utf-8")
    assert "## Combat en cours" in texte2, texte2[:6000]
    assert f"Round : {live2['round_number']}" in texte2, texte2
    assert f"- {NOM_JOUEUR} (player) : {hp_joueur_apres} PV" in texte2, texte2
    assert f"- {BRUTE_NOM} ({BRUTE_SLUG}) : {hp_brute_apres} PV" in texte2, texte2
    section("2b) photo_director : la section « Combat en cours » suit les "
           "PV mis à jour par le moteur")

    refus_attack = mcp_server.attack(attacker="player", target=BRUTE_SLUG)
    assert "error" in refus_attack, refus_attack
    assert "submit_intent" in refus_attack["error"], refus_attack
    section(f"2c) attack refusé pendant le combat ouvert, renvoie à "
           f"submit_intent -> {refus_attack['error']!r}")

    refus_second = asyncio.run(mcp_server.start_combat(
        session_id="chantier7b-second-refuse",
        party=[{"entity_id": "player", "zone_id": "z1"}],
        encounter=[{"entity_id": BRUTE_SLUG, "zone_id": "z1",
                   "initiative": 5, "hp_current": hp_brute_apres}],
        rng_seed=1, zones=["z1"]))
    assert "error" in refus_second, refus_second
    assert "handle_id" not in refus_second, \
        "un second start_combat refusé ne doit ouvrir aucun combat"
    assert handle in refus_second["error"] or "déjà ouvert" in refus_second["error"], \
        refus_second
    section(f"2d) un second start_combat est refusé (un seul combat à la "
           f"fois) -> {refus_second['error']!r}")

    # ======================================================================
    # Tour 3 — end_combat : la section disparaît, PV réconciliés, attack OK
    # ======================================================================
    fin = asyncio.run(mcp_server.end_combat(handle))
    assert "outcome" in fin and fin.get("reconciled") is not None, fin
    recon = fin["reconciled"]
    assert recon["player"] == {"hp_before": 12, "hp_after": hp_joueur_apres}, recon
    assert recon["enemies"][BRUTE_SLUG]["hp_after"] == hp_brute_apres, recon
    section(f"3a) end_combat -> reconciled = {recon}")

    assert "combat" not in store.rpg_state(), \
        "end_combat devrait effacer l'entrée 'combat' de la save"
    save_brute = store.rpg_state()["enemies"][BRUTE_SLUG]["hp"]
    save_joueur = store.rpg_state()["player"]["hp"]
    assert save_brute == hp_brute_apres and save_joueur == hp_joueur_apres, \
        (save_brute, save_joueur, hp_brute_apres, hp_joueur_apres)
    section("3b) la save porte les PV réconciliés, l'entrée 'combat' est "
           "effacée")

    photo3 = mcp_server.photo_director("Je reprends mon souffle.")
    texte3 = Path(photo3["path"]).read_text(encoding="utf-8")
    assert "Combat en cours" not in texte3, \
        f"la section devrait disparaître une fois le combat clos -> {texte3[:6000]!r}"
    monde3 = mcp_server.get_world_state()
    assert "combat_ouvert" not in monde3, monde3
    section("3c) photo_director et get_world_state : plus de combat une "
           "fois end_combat appelé")

    permis_attack = mcp_server.attack(attacker="player", target=BRUTE_SLUG)
    assert "error" not in permis_attack, permis_attack
    section(f"3d) attack redevient permis après end_combat -> "
           f"{permis_attack['hit']=}")

    # ======================================================================
    # Cas de péremption — entrée 'combat' présente, pont qui ne la connaît
    # plus (jamais ouverte par ce process : handle inventé)
    # ======================================================================
    HANDLE_PERIME = "handle-perime-banc-7b-jamais-ouvert"
    rpg_perime = store.rpg_state()
    rpg_perime["combat"] = {
        "handle_id": HANDLE_PERIME, "session_id": "chantier7b-perime",
        "party": ["player"], "enemy_hp_max": {BRUTE_SLUG: 50},
        "combatants": [{"entity_id": "player", "name": NOM_JOUEUR},
                      {"entity_id": BRUTE_SLUG, "name": BRUTE_NOM}],
        "player_entity_id": "player",
    }
    store.set_rpg_state(rpg_perime)

    monde_perime = mcp_server.get_world_state()
    co_perime = monde_perime.get("combat_ouvert")
    assert co_perime == {"handle_id": HANDLE_PERIME,
                         "session_id": "chantier7b-perime",
                         "stale": True}, co_perime
    section(f"4a) get_world_state()['combat_ouvert'] dit le combat périmé "
           f"en une ligne -> {co_perime}")

    photo4 = mcp_server.photo_director("Je regarde autour de moi, méfiant.")
    texte4 = Path(photo4["path"]).read_text(encoding="utf-8")
    assert "Combat périmé" in texte4 and HANDLE_PERIME in texte4, \
        f"la photo devrait dire le combat périmé en une ligne -> {texte4[:6000]!r}"
    assert "Round :" not in texte4, \
        f"un combat périmé ne porte aucun champ dynamique deviné -> {texte4[:6000]!r}"
    section("4b) photo_director : « Combat périmé » en une ligne, aucun "
           "champ dynamique deviné")

    hp_brute_avant_reprise = store.rpg_state()["enemies"][BRUTE_SLUG]["hp"]
    reprise = asyncio.run(mcp_server.start_combat(
        session_id="chantier7b-reprise",
        party=[{"entity_id": "player", "zone_id": "z1", "initiative": 20}],
        encounter=[{"entity_id": BRUTE_SLUG, "zone_id": "z1",
                   "initiative": 5, "hp_current": hp_brute_avant_reprise}],
        rng_seed=3, zones=["z1"]))
    assert "error" not in reprise, reprise
    handle_reprise = reprise["handle_id"]
    assert handle_reprise != HANDLE_PERIME, reprise
    assert any("périmé" in w for w in reprise.get("warnings") or []), \
        f"start_combat devrait avertir de l'entrée périmée effacée -> {reprise}"
    assert store.rpg_state()["combat"]["handle_id"] == handle_reprise, \
        store.rpg_state().get("combat")
    section(f"4c) start_combat efface l'entrée périmée, ouvre un nouveau "
           f"combat (handle={handle_reprise!r}) et avertit -> "
           f"{reprise['warnings']}")

    asyncio.run(mcp_server.end_combat(handle_reprise))  # nettoyage, hygiène

    print(f"\nOK test-combat-director-chantier7b — {len(FAIT)} sections vertes")
finally:
    mcp_server._engine = None
    mcp_server._store = None
    mcp_server._slug = ""
    mcp_server._last_applied_events = None
    shutil.rmtree(TMP, ignore_errors=True)
