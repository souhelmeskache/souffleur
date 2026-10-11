"""Issue #19 : `roll_check` (coderain/mcp/jets_combat.py) jetait un acteur
inconnu ou une stat inconnue à 0 sans jamais le dire — un `actor` autre que
"player"/"you" absent de characters.md avait des stats vides ({}), et une
`stat` absente de la fiche ET de `rpg.provisoire` (D-275) retombait sur 0,
silencieusement. Ce test (D-109/D-206, aucun matériau de campagne réel) :

  1. un acteur inconnu ("fantome") est refusé, nommant les valeurs admises ;
  2. une stat inconnue ("clairvoyance", ni sur la fiche ni provisoire) est
     refusée, nommant les stats de la fiche ;
  3. `actor="player"` avec une stat de la fiche passe comme avant (aucune
     régression) ;
  4. une stat posée en valeur provisoire (D-275, `bouchage_mod`) passe
     toujours, marquée `provisoire: true` ;
  5. `attack` et `derived_combat`/`player_combat` ne changent pas de
     comportement (hors périmètre de ce correctif) — vérifié par un appel de
     chacun qui se comporte exactement comme documenté ailleurs."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.memory import Entry, Library

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


root = os.path.join(tempfile.gettempdir(), "se_roll_check_refus_i19")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
slug = lib.saves.create(
    "RollCheckRefus", mode="rpg",
    premise="Banc synthétique I-19, D-109/D-206 — aucun matériau réel.")
store = lib.store(slug)
assert store.mode() == "rpg" and store.rpg_enabled()

store.upsert_entry("characters.md", Entry(
    title="Garde factice", slug="garde-factice", importance=2,
    attrs={"stats": "strength 2, agility 1", "pv": "9",
          "attaque_bonus": "+3", "degats": "1d6+1", "ca": "12"},
    body="PNJ synthétique de test."))
store.upsert_entry("items.md", Entry(
    title="Épée factice", slug="epee-factice", importance=2,
    attrs={"degats": "1d8+3", "stat": "strength", "status": "held by you"},
    body="Objet synthétique de test."))

mcp_server._engine = None          # régime dégradé, même patron que les autres bancs
mcp_server._store = store
mcp_server._slug = slug
mcp_server._last_applied_events = None


def _set_player(*, seed=11):
    rpg = store.rpg_state()
    p = rpg.setdefault("player", {})
    p["stats"] = {"strength": 3, "agility": 2}
    p["level"], p["hp"], p["hp_max"] = 5, 20, 20
    p["conditions"] = []
    rpg["inventory"] = {"epee-factice": {"qty": 1, "equipped": True}}
    rpg["enemies"] = {}
    rpg["seed"], rpg["rolls"] = seed, 0
    store.set_rpg_state(rpg)


_set_player()

section("1) acteur inconnu -> refus nommant les valeurs admises")
refus_acteur = mcp_server.roll_check(stat="strength", actor="fantome")
assert "error" in refus_acteur, f"attendu un refus -> {refus_acteur!r}"
assert "unknown actor" in refus_acteur["error"], refus_acteur
assert "player" in refus_acteur["error"], refus_acteur
assert "garde-factice" in refus_acteur["error"], refus_acteur
assert store.rpg_state().get("rolls") == 0, "aucun dé ne doit être consommé"
print(f"  OK : {refus_acteur['error']!r}")

section("2) stat inconnue (ni fiche ni provisoire) -> refus nommant les "
        "stats de la fiche")
refus_stat = mcp_server.roll_check(stat="clairvoyance", actor="player")
assert "error" in refus_stat, f"attendu un refus -> {refus_stat!r}"
assert "unknown stat" in refus_stat["error"], refus_stat
assert "strength" in refus_stat["error"] and "agility" in refus_stat["error"], \
    refus_stat
assert store.rpg_state().get("rolls") == 0, "aucun dé ne doit être consommé"
print(f"  OK : {refus_stat['error']!r}")

section("2b) même refus pour un PNJ connu, sur sa propre stat absente")
refus_stat_pnj = mcp_server.roll_check(stat="clairvoyance", actor="garde-factice")
assert "error" in refus_stat_pnj, f"attendu un refus -> {refus_stat_pnj!r}"
assert "unknown stat" in refus_stat_pnj["error"], refus_stat_pnj
assert "strength" in refus_stat_pnj["error"] and "agility" in refus_stat_pnj["error"], \
    refus_stat_pnj
print(f"  OK : {refus_stat_pnj['error']!r}")

section("3) actor=player, stat de la fiche -> passe comme avant")
jet_ok = mcp_server.roll_check(stat="strength", dc=10, actor="player")
assert "error" not in jet_ok, f"ne devrait pas être refusé -> {jet_ok!r}"
assert jet_ok["mod"] == 3, jet_ok
assert "provisoire" not in jet_ok, jet_ok
assert store.rpg_state().get("rolls") == 1
print(f"  OK : {jet_ok!r}")

section("4) stat posée en valeur provisoire (D-275) -> passe, marquée "
        "provisoire")
_set_player(seed=11)
trou_stat = {"type": "nombre", "champ": "clairvoyance", "fiche": "player",
            "contexte": "le joueur sonde l'obscurité, la stat manque"}
dossier = mcp_server.demander_bouchage(dict(trou_stat))
mcp_server.enregistrer_bouchage(
    dossier["id"], "4", "Stat de rang 5 alignée sur les autres de la fiche.")
jet_prov = mcp_server.roll_check(stat="clairvoyance", dc=10, actor="player")
assert "error" not in jet_prov, f"ne devrait pas être refusé -> {jet_prov!r}"
assert jet_prov["mod"] == 4, jet_prov
assert jet_prov.get("provisoire") is True, jet_prov
assert jet_prov.get("provisoire_ids") == ["player.clairvoyance"], jet_prov
print(f"  OK : {jet_prov!r}")

section("5) attack et derived_combat/player_combat inchangés (hors "
        "périmètre de ce correctif)")
_set_player(seed=11)
touche = mcp_server.attack(attacker="player", target="garde-factice")
assert "error" not in touche, f"attack ne devrait pas être refusé -> {touche!r}"
assert touche["attacker"] == "player" and touche["target"] == "garde-factice"
derive = mcp_server._load_rpg().player_combat(store)
assert "error" not in derive, f"player_combat inattendu -> {derive!r}"
print(f"  OK : attack -> {touche['hit']!r}, player_combat -> ac={derive.get('ac')!r}")

print(f"\nOK test-roll-check-refus-i19 — {len(FAIT)} sections vertes")
