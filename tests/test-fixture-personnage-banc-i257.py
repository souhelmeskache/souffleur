"""Test d'élément — fixture de banc `bench/fixtures/personnage-banc.py`
(Issue #257, prérequis du banc de nuit #201).

Avant cette fixture : le save du banc n'avait jamais de personnage —
`player.md` au gabarit vierge, `state.json` aux défauts du module (stats au
vocabulaire 5e générique, pas celui que lit le moteur), `items.md` vide
(constat #237/#102) — `derived_combat` refusait faute de `stats` lisibles et
`attack` n'avait ni arme ni cible équipée à jeter.

Ce test exerce le SCRIPT (`install()`), jamais une édition manuelle du save
(I-226, #120) : sur un save temporaire synthétique, jamais le save réel
(D-109 — zéro matériau de campagne dans ce dépôt).

Verdicts mécaniques (D-134) : égalité numérique / présence de sous-chaîne /
absence de clé `error`, jamais une lecture de qualité.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.memory import Entry, Library
from coderain.modules import rpg as rpg_mod

import mcp_server

# Import du script (nom de fichier à tiret : pas un module importable tel quel).
_spec = importlib.util.spec_from_file_location(
    "personnage_banc", ROOT / "bench" / "fixtures" / "personnage-banc.py")
personnage_banc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(personnage_banc)

ROOT_TMP = os.path.join(tempfile.gettempdir(), "test_fixture_personnage_banc_i257")


def _fresh_save(title: str) -> tuple[Library, str, Path]:
    """Un save de test frais (gabarit vierge), jamais le save réel."""
    root = os.path.join(ROOT_TMP, title)
    if os.path.exists(root):
        shutil.rmtree(root)
    lib = Library(root)
    slug = lib.saves.create(title, mode="rpg",
                            premise="Fixture de banc I-257 — save 100% "
                                    "synthétique, D-109.")
    store = lib.store(slug)
    return lib, slug, store.dir


# --- 1. installation sur un save vierge -------------------------------------
lib, slug, save_dir = _fresh_save("Fixture1")
res = personnage_banc.install(save_dir)
assert res["status"] == "installed", res

store = lib.store(slug)
player = personnage_banc._player_entry(store)
assert player.title == "Mika Thorne", player
assert player.attrs.get("status", "").strip(), "status ne doit plus être vide"
stats = store.rpg_state()["player"]["stats"]
assert stats == {
    "strength": 3, "agility": 1, "constitution": 2,
    "intelligence": 0, "knowledge": 0, "willpower": 1, "charisma": 0,
}, stats
# player.md ET state.json cohérents (#102) : mêmes stats des deux côtés.
assert player.stats() == stats, (player.stats(), stats)

items = {e.slug: e for e in store.entries("items.md")}
assert personnage_banc.WEAPON_SLUG in items and personnage_banc.ARMOR_SLUG in items
assert items[personnage_banc.WEAPON_SLUG].attrs.get("degats") == "1d8+2"
assert items[personnage_banc.ARMOR_SLUG].attrs.get("armure") == "14"

inv = store.rpg_state()["inventory"]
assert inv[personnage_banc.WEAPON_SLUG] == {"qty": 1, "equipped": True}, inv
assert inv[personnage_banc.ARMOR_SLUG] == {"qty": 1, "equipped": True}, inv

p = store.rpg_state()["player"]
assert p["hp"] == p["hp_max"] == 20, p  # PV cohérents avec hp_max

print("1/6 install sur save vierge : ok")

# --- 2. idempotence : rejoué, rien ne change ---------------------------------
res2 = personnage_banc.install(save_dir)
assert res2["status"] == "unchanged", res2
store2 = lib.store(slug)
assert store2.rpg_state()["player"]["stats"] == stats
print("2/6 idempotence : ok")

# --- 3. refus d'écraser un save non-vierge, sauf --force --------------------
lib3, slug3, save_dir3 = _fresh_save("Fixture3")
store3 = lib3.store(slug3)
entry3 = personnage_banc._player_entry(store3)
entry3.attrs["status"] = "personnage déjà joué par un humain"
store3.upsert_entry("player.md", entry3)

res3 = personnage_banc.install(save_dir3)
assert res3["status"] == "refused", res3
store3b = lib3.store(slug3)
assert store3b.entries("player.md")[0].attrs.get("status") == \
    "personnage déjà joué par un humain"   # inchangé

res3f = personnage_banc.install(save_dir3, force=True)
assert res3f["status"] == "installed", res3f
store3c = lib3.store(slug3)
assert store3c.entries("player.md")[0].title == "Mika Thorne"
print("3/6 refus sans --force, écrasement avec --force : ok")

# --- 4. preuve : derived_combat rend une CA et un bonus d'attaque -----------
lib4, slug4, save_dir4 = _fresh_save("Fixture4")
personnage_banc.install(save_dir4)
store4 = lib4.store(slug4)
combat = rpg_mod.player_combat(store4)
assert "error" not in combat, combat
assert combat["ac"] == 15, combat            # 14 (armure) + min(agility 1, dex_max 2)
assert combat["attack_bonus"] == 5, combat    # mod strength 3 + maîtrise niv.1 (+2)
print("4/6 derived_combat sans erreur (CA 15, bonus +5) : ok")

# --- 5. preuve : attack("player", <créature synthétique>) jette un dé -------
store4.upsert_entry("characters.md", Entry(
    title="Créature factice de test", slug="creature-factice-test",
    importance=2,
    attrs={"ca": "12", "pv": "9", "attaque_bonus": "+2", "degats": "1d6+1"},
    body="Créature synthétique de test (I-257), aucun lien avec un module."))
mcp_server._engine = None
mcp_server._store = store4
mcp_server._slug = slug4
mcp_server._last_applied_events = None
atk = mcp_server.attack(attacker="player", target="creature-factice-test")
assert "error" not in atk, atk
assert "roll" in atk and isinstance(atk["roll"], int), atk
print("5/6 attack() lance un dé (pas de refus) : ok")

# --- 6. preuve : ui_sheet affiche la section Combat --------------------------
sheet = rpg_mod.render_sheet_lines(store4.rpg_state(), combat=combat)
assert "— Combat —" in sheet, sheet
assert "indisponible" not in sheet, sheet
assert "AC     15" in sheet, sheet
print("6/6 render_sheet_lines affiche — Combat — : ok")

shutil.rmtree(ROOT_TMP, ignore_errors=True)
print("OK - test-fixture-personnage-banc-i257")
