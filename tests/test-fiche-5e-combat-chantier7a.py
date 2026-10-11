"""Chantier 7a (I-28 suite, D&D réel) : le personnage joué est une vraie
fiche 5e, et le moteur 5e sait le faire entrer en combat.

Décision Souhel : dans une partie D&D, la fiche porte les six SCORES 5e
(vocabulaire EXACT `strength/dexterity/constitution/intelligence/wisdom/
charisma`, détecté par `rpg.scores_mode`), jamais le vocabulaire générique
du socle (`agility`, ...). `classe`/`espece` sont des identifiants du
catalogue `dnd5e-engine` ; les objets équipés portent un `srd:` en plus des
champs génériques (`degats:`/`armure:`) que `derived_combat` lit déjà.

Ce test exerce la fixture de banc `bench/fixtures/personnage-banc.py`
(profil `guerrier-5e`, ajouté par ce chantier) et prouve, de bout en bout :

  1) `start_combat` accepte le joueur par son nom —
     `party=[{"entity_id": "player", "zone_id": "z1"}]` — construit par
     `coderain/mcp/jets_combat.py::_build_player_party_member` depuis la
     save (scores, CA/bonus d'attaque dérivés via `rpg.derived_combat`,
     niveau/classe/espèce, équipement par les `srd:` des objets équipés) ;
     aucune initiative fournie -> jetée (`"initiatives_rolled"` du retour).
  2) le joueur attaque par `submit_intent` avec son arme (`weapon_id`
     résolu via le `srd:` de l'objet équipé — ici `"longsword"`).
  3) `end_combat` réconcilie ses PV avec la save (mécanisme du chantier 6,
     exercé ici pour la première fois sur un membre construit par ce
     chantier) : les PV perdus en combat tactique reviennent dans
     `rpg_state()["player"]["hp"]`.

Fixtures 100% synthétiques (D-109), hors ligne. Needs dnd5e-engine
(requirements.txt) ; saute bruyamment si absent, même convention que
`test-mcp-fin-combat-reconciliation-i28-chantier6.py`.
"""
from __future__ import annotations

import asyncio
import importlib.util
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
    print("SKIP test-fiche-5e-combat-chantier7a : dnd5e-engine non installé "
         "(pip install -r requirements.txt)")
    sys.exit(0)

# Import du script de fixture (nom de fichier à tiret : pas un module
# importable tel quel) — même technique que
# test-fixture-personnage-banc-i257.py.
_spec = importlib.util.spec_from_file_location(
    "personnage_banc_7a", ROOT / "bench" / "fixtures" / "personnage-banc.py")
personnage_banc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(personnage_banc)

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


TMP = Path(tempfile.gettempdir()) / "se_fiche_5e_combat_chantier7a"
if TMP.exists():
    shutil.rmtree(TMP)

try:
    lib = Library(TMP / "app")
    slug = lib.saves.create(
        "Chantier7a-fiche5e", mode="rpg",
        premise="Fiche 5e réelle du joueur, D-109 — aucun matériau de "
                "campagne réel.")
    store = lib.store(slug)
    save_path = TMP / "app" / "saves" / slug

    res_install = personnage_banc.install(save_path, profil="guerrier-5e")
    assert res_install["status"] == "installed", res_install
    section(f"0) fixture 'guerrier-5e' installée -> {res_install['message']}")

    # Un adversaire non-SRD (record de module absent) : construit par le
    # même pont 'brute' que le chantier 6 (`encounter_member_from_record`).
    # CA posée à 1 : le coup d'épée du joueur touche toujours ; attaque_bonus
    # à 20 : la brute touche toujours le joueur (CA 16 dérivée, d20+20 >= 16
    # pour tout jet) — déterministe sans dépendre de la graine.
    store.upsert_entry("characters.md", Entry(
        title="Brute de banc (7a)", slug="brute-banc-7a", importance=2,
        attrs={"ca": "1", "pv": "20", "attaque_bonus": "20",
              "degats": "1d4+1"},
        body="Créature synthétique de test (D-109)."))

    store2 = lib.store(slug)  # ré-ouverture : lit la fixture fraîchement écrite
    mcp_server._engine = None       # régime dégradé — même convention que
                                     # test-mcp-fin-combat-reconciliation-i28-chantier6
    mcp_server._store = store2
    mcp_server._slug = slug
    mcp_server._last_applied_events = None
    # `load_save` ferait ceci lui-même (lecture des clés de `rpg.player.stats`
    # de la save) — reproduit ici, même convention que les tests qui court-
    # circuitent `load_save` (mcp_server._store assigné directement).
    mcp_server._rpg_cfg = dict(mcp_server._DEFAULT_RPG)
    mcp_server._rpg_cfg["stats"] = ["strength", "dexterity", "constitution",
                                    "intelligence", "wisdom", "charisma"]

    rpg0 = store2.rpg_state()
    rpg0["seed"], rpg0["rolls"] = 7, 0
    store2.set_rpg_state(rpg0)

    bridge = mcp_server.get_bridge()

    # ======================================================================
    # 1) start_combat accepte le joueur par son nom (thin reference)
    # ======================================================================
    combat = asyncio.run(mcp_server.start_combat(
        session_id="chantier7a-fiche5e", party=[
            {"entity_id": "player", "zone_id": "z1"}],
        encounter=[{"entity_id": "brute-banc-7a", "zone_id": "z1",
                   "initiative": 8, "hp_current": 20}],
        rng_seed=7, zones=["z1"]))
    assert "error" not in combat, combat
    handle = combat["handle_id"]
    assert combat["live"]["tracked_hp"]["player"] == 12, combat["live"]
    section("1a) start_combat({'entity_id': 'player', 'zone_id': 'z1'}) -> "
            "fiche 5e construite depuis la save (PV moteur = 12, hp_max de "
            "la fixture)")

    assert "player" in combat.get("initiatives_rolled", {}), combat
    section(f"1b) aucune initiative fournie -> jetée par le système "
            f"(initiatives_rolled={combat['initiatives_rolled']}), jamais "
            "une valeur inventée par l'appelant")

    # ======================================================================
    # 2) le joueur attaque avec son arme (srd: "longsword")
    # ======================================================================
    hp_brute_avant = combat["live"]["tracked_hp"]["brute-banc-7a"]
    for _ in range(6):
        live = bridge.live(handle)
        if live["ended"]:
            break
        if live["active_actor_id"] == "player":
            asyncio.run(mcp_server.submit_intent(
                handle, "player",
                {"intent_type": "attack", "target_id": "brute-banc-7a",
                 "weapon_id": "longsword"}))
        else:
            asyncio.run(mcp_server.monster_turn(handle))

    live_fin = bridge.live(handle)
    hp_brute_apres = live_fin["tracked_hp"]["brute-banc-7a"]
    hp_joueur_apres = live_fin["tracked_hp"]["player"]
    assert hp_brute_apres < hp_brute_avant, (
        f"l'épée longue (srd 'longsword', CA brute posée à 1 : coup "
        f"garanti) doit avoir blessé la brute -> avant={hp_brute_avant}, "
        f"après={hp_brute_apres}")
    assert hp_joueur_apres < 12, (
        f"la brute (attaque_bonus 20, CA joueur 16 : coup garanti) doit "
        f"avoir blessé le joueur -> {hp_joueur_apres}")
    section(f"2) submit_intent(attack, weapon_id='longsword') + riposte de "
            f"la brute : PV brute {hp_brute_avant} -> {hp_brute_apres}, PV "
            f"joueur 12 -> {hp_joueur_apres} (moteur 5e, live())")

    # ======================================================================
    # 3) end_combat réconcilie les PV du joueur avec la save (chantier 6)
    # ======================================================================
    fin = asyncio.run(mcp_server.end_combat(handle))
    assert "outcome" in fin and "events" in fin, fin
    recon = fin["reconciled"]
    assert recon is not None, fin
    assert recon["player"] == {"hp_before": 12, "hp_after": hp_joueur_apres}, recon
    save_apres = store2.rpg_state()["player"]["hp"]
    assert save_apres == hp_joueur_apres, (
        f"la save devrait porter les PV du moteur ({hp_joueur_apres}), pas "
        f"les 12 PV stale d'avant combat -> {save_apres}")
    section(f"3) end_combat -> reconciled['player'] = {recon['player']} ; "
            f"rpg_state()['player']['hp'] = {save_apres} (mécanisme du "
            "chantier 6, exercé sur une fiche construite par ce chantier)")

    print(f"\nOK test-fiche-5e-combat-chantier7a — {len(FAIT)} sections vertes")
finally:
    mcp_server._engine = None
    mcp_server._store = None
    mcp_server._slug = ""
    mcp_server._last_applied_events = None
    shutil.rmtree(TMP, ignore_errors=True)
