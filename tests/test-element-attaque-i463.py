"""Test d'élément — le joueur n'avait ni CA ni bonus d'attaque, et aucun outil
ne résolvait une attaque de bout en bout (Issue #234 / I-463, D-274 §1-2,
moule I-382).

Briques visées : `coderain.modules.rpg.derived_combat`/`player_combat`
(nouveau — CA et bonus d'attaque DÉRIVÉS de la fiche, jamais stockés) et
l'outil `mcp_server.attack` (nouveau — lit les deux fiches, jette, applique
par le guichet D-141). Le trou constaté au banc (run 20260831-202617, tours
21-27) : le Director a simulé sept attaques par `resolve_check` avec une DEX
fabriquée et une CA inventée, puis a joué le monstre lui-même — chaque nombre
manquant était ESTIMÉ au lieu d'être REFUSÉ.

Fixtures 100 % synthétiques (D-109/D-206, aucun matériau de campagne réel) :
une épée factice, une cotte factice, un « rongeur-de-suie » factice. Dés
déterministes (seed + nonce) : les graines ci-dessous ont été sondées pour
produire la séquence de jets voulue par chaque état de fixture — même
discipline que `tests/test-element-jet-degats-i206.py`.

Verdicts mécaniques (D-134) : égalité numérique, présence de sous-chaîne —
jamais une lecture de qualité.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.fixtures.element_mold import ElementMold, present

from coderain.memory import Entry, Library
from coderain.modules import rpg as rpg_mod

import mcp_server

root = os.path.join(tempfile.gettempdir(), "se_element_attaque_i463")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
slug = lib.saves.create(
    "ElementAttaque", mode="rpg",
    premise="Banc synthétique I-463, D-109/D-206 — aucun matériau réel.")
store = lib.store(slug)
assert store.mode() == "rpg" and store.rpg_enabled()

# ---- fixtures Markdown : deux objets et un monstre, tous factices ---------
store.upsert_entry("items.md", Entry(
    title="Épée factice", slug="epee-factice", importance=2,
    attrs={"degats": "1d8+3", "stat": "strength", "status": "held by you"},
    body="Objet synthétique de test."))
store.upsert_entry("items.md", Entry(
    title="Cotte factice", slug="cotte-factice", importance=2,
    attrs={"armure": "16", "dex_max": "2", "status": "held by you"},
    body="Objet synthétique de test."))
store.upsert_entry("characters.md", Entry(
    title="Rongeur de suie", slug="rongeur-de-suie", importance=2,
    attrs={"ca": "13", "pv": "9", "attaque_bonus": "+4", "degats": "1d6+2"},
    body="Créature synthétique de test."))
# Une cible SANS classe d'armure : le refus de D-274 §1 doit tomber dessus.
store.upsert_entry("characters.md", Entry(
    title="Ombre sans fiche", slug="ombre-sans-fiche", importance=2,
    attrs={"pv": "5"},
    body="Créature synthétique de test, volontairement incomplète."))

mcp_server._engine = None          # régime dégradé, comme test-element-mort-i213
mcp_server._store = store
mcp_server._slug = slug
mcp_server._last_applied_events = None

PLAYER_STATS = {"strength": 3, "agility": 2}
ARME = {"epee-factice": {"qty": 1, "equipped": True}}
ARME_ET_COTTE = {"epee-factice": {"qty": 1, "equipped": True},
                 "cotte-factice": {"qty": 1, "equipped": True}}


def _set_player(*, stats=None, level=5, inventory=None, hp=20, seed=7,
                enemies=None):
    """Remet l'état du save dans un état de fixture connu (rolls à 0)."""
    rpg = store.rpg_state()
    p = rpg.setdefault("player", {})
    p["stats"] = dict(PLAYER_STATS if stats is None else stats)
    p["level"] = level
    p["hp"], p["hp_max"] = hp, max(hp, 20)
    p["conditions"] = []
    p["death_saves"] = {"successes": 0, "failures": 0}
    rpg["inventory"] = dict(ARME if inventory is None else inventory)
    rpg["enemies"] = dict(enemies or {})
    rpg["seed"], rpg["rolls"] = seed, 0
    store.set_rpg_state(rpg)
    return rpg


with ElementMold("attaque-i463", budget_seconds=10.0) as mold:
    # ---- A. la dérivation : CA et bonus d'attaque sortent de la fiche -----
    _set_player()
    nu = mcp_server._load_rpg().player_combat(store)
    # CA sans armure = 10 + mod DEX(agility=2) = 12 ; bonus = FOR(3) + maîtrise
    # niveau 5 (+3) = 6, l'épée factice attaquant au `stat: strength`.
    mold.check(
        "A1-derivation-sans-armure",
        nu.get("ac") == 12 and nu.get("attack_bonus") == 6
        and (nu.get("weapon") or {}).get("slug") == "epee-factice",
        f"derivation nue -> {nu!r}")

    _set_player(inventory=ARME_ET_COTTE)
    vetu = mcp_server._load_rpg().player_combat(store)
    # Armure équipée : CA = 16 (`armure:`) + min(mod DEX 2, `dex_max` 2) = 18.
    mold.check(
        "A2-derivation-avec-armure",
        vetu.get("ac") == 18 and (vetu.get("armor") or {}).get("slug")
        == "cotte-factice",
        f"derivation vêtue -> {vetu!r}")

    # Mod manquant -> REFUS explicite, jamais un 0 par défaut.
    sans_dex = rpg_mod.derived_combat({"stats": {"strength": 3}, "level": 1},
                                      ARME, {})
    mold.check(
        "A3-mod-manquant-refuse",
        "error" in sans_dex and present(sans_dex["error"], "agility"),
        f"derived_combat sans agility -> {sans_dex!r}")

    # Rien n'est stocké : la CA n'apparaît nulle part dans state.json.
    _set_player(inventory=ARME_ET_COTTE)
    brut = store.read("state.json")
    mold.check(
        "A4-rien-de-stocke-en-dur",
        '"ac"' not in brut and '"attack_bonus"' not in brut,
        "state.json ne porte ni ac ni attack_bonus (dérivés à la lecture)")

    # Exposée en lecture (get_world_state) — dérivée, pas persistée.
    ws = mcp_server.get_world_state()
    mold.check(
        "A5-expose-en-lecture",
        isinstance(ws.get("combat"), dict) and ws["combat"].get("ac") == 18,
        f"get_world_state()['combat'] -> {ws.get('combat')!r}")

    # ---- B. l'outil attack : touche, dégâts, application par le guichet ---
    # seed 7 : d20 nonce 1 = 19 -> 19+6 = 25 >= CA 13, touche.
    _set_player(seed=7)
    touche = mcp_server.attack(attacker="player", target="rongeur-de-suie")
    mold.check(
        "B1-touche-deterministe",
        touche.get("hit") is True and touche.get("roll") == 19
        and touche.get("total") == 25 and touche.get("target_ac") == 13,
        f"attack (seed 7) -> {touche!r}")

    degats = (touche.get("damage") or {}).get("total")
    hp_relu = (store.rpg_state().get("enemies") or {}).get("rongeur-de-suie")
    attendu = max(0, 9 - int(degats or 0))
    mold.check(
        "B2-degats-appliques-par-le-guichet",
        (attendu == 0 and hp_relu is None)
        or (hp_relu is not None and hp_relu.get("hp") == attendu
            and hp_relu.get("hp_max") == 9),
        f"dégâts={degats}, PV attendus={attendu}, relu={hp_relu!r}")
    mold.check(
        "B3-evenement-journalise",
        present(" ".join((touche.get("applied") or {}).get("events") or []),
                "rongeur-de-suie"),
        f"applied -> {(touche.get('applied') or {})!r}")

    # seed 10 : d20 nonce 1 = 4 -> 4+6 = 10 < 13, raté : rien n'est appliqué.
    _set_player(seed=10)
    rate = mcp_server.attack(attacker="player", target="rongeur-de-suie")
    mold.check(
        "B4-rate-deterministe",
        rate.get("hit") is False and rate.get("damage") is None
        and rate.get("applied") is None
        and not (store.rpg_state().get("enemies") or {}),
        f"attack (seed 10) -> {rate!r}")

    # ---- C. le nonce avance d'un cran par jet (pas de rejeu du même dé) ---
    _set_player(seed=7)
    mcp_server.attack(attacker="player", target="rongeur-de-suie")
    apres_touche = store.rpg_state().get("rolls")
    _set_player(seed=10)
    mcp_server.attack(attacker="player", target="rongeur-de-suie")
    apres_rate = store.rpg_state().get("rolls")
    mold.check(
        "C1-nonce-un-cran-par-jet",
        apres_touche == 2 and apres_rate == 1,
        f"rolls après touche={apres_touche} (toucher+dégâts), "
        f"après raté={apres_rate} (toucher seul)")

    # ---- D. un nombre absent est un REFUS (D-274 §1) ----------------------
    _set_player(seed=7)
    sans_ca = mcp_server.attack(attacker="player", target="ombre-sans-fiche")
    mold.check(
        "D1-refus-ca-absente",
        present(str(sans_ca.get("error", "")), "missing ca")
        and store.rpg_state().get("rolls") == 0,
        f"attack sur cible sans ca -> {sans_ca!r} (aucun dé consommé)")

    # Aucune arme équipée -> aucun dé de dégâts : refus, pas un d6 inventé.
    _set_player(seed=7, inventory={})
    sans_des = mcp_server.attack(attacker="player", target="rongeur-de-suie")
    mold.check(
        "D2-refus-des-absents",
        present(str(sans_des.get("error", "")), "missing degats"),
        f"attack sans arme équipée -> {sans_des!r}")

    inconnu = mcp_server.attack(attacker="player", target="pas-de-fiche-du-tout")
    mold.check(
        "D3-refus-combattant-inconnu",
        present(str(inconnu.get("error", "")), "unknown combatant"),
        f"attack sur slug inconnu -> {inconnu!r}")

    # ---- E. la cible joueur : downed atteint à 0 PV (D-271) ---------------
    # seed 7 : d20 nonce 1 = 19 -> 19 + 4 (attaque_bonus du monstre) = 23 >=
    # CA 12 du joueur nu ; dégâts 1d6+2 >= 3 sur 3 PV -> 0 PV, downed.
    _set_player(seed=7, hp=3)
    subie = mcp_server.attack(attacker="rongeur-de-suie", target="player")
    p_apres = store.rpg_state().get("player") or {}
    mold.check(
        "E1-joueur-touche-tombe-a-terre",
        subie.get("hit") is True and p_apres.get("hp") == 0
        and "downed" in (p_apres.get("conditions") or []),
        f"attack monstre->joueur -> {subie!r} ; joueur={p_apres!r}")
    mold.check(
        "E2-pv-clampes-par-le-guichet",
        p_apres.get("hp") >= 0
        and "downed" in ((subie.get("applied") or {}).get("conditions") or []),
        f"applied -> {(subie.get('applied') or {})!r}")

assert mold.report(), "test-element-attaque-i463: au moins un verdict a échoué"
print("test-element-attaque-i463: OK — moule I-382, CA/bonus dérivés + attack "
      "de bout en bout, refus sur nombre absent (D-274 §1-2)")
