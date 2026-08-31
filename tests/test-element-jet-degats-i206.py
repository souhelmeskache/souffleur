"""Test d'élément — le jet de dégâts (Issue #206, moule I-382).

Brique visée : `coderain.modules.rpg.roll_damage` (nouveau) + le chemin
`mcp_server.apply_envelope` → `deltas.hp_delta` (existant depuis I-375, guichet
D-141) — la CHAÎNE COMPLÈTE constatée absente au banc (run 20260831-202617,
craquement-2.md, tour 21) : le node scripte une attaque (fiche synthétique
« givre-hurleur » : degats '9 (1d8+3) slashing'), le toucher se résout
(roll_check), mais aucun outil ne résolvait le jet de dégâts ni n'appliquait
la perte de PV. `hp_delta` lui-même était déjà reconnu par le validateur
(tests/test-chemins-morts-i375.py) — le trou était en amont : rien ne
produisait ce delta à partir d'une formule de dés.

Rejoue le scénario du banc sur une fiche 100% synthétique (D-109/D-206,
aucun matériau de campagne réel) :
  1. toucher résolu (`roll_check`, mod du monstre vs CA du joueur) ;
  2. dégâts roulés (`roll_damage`, formule '1d8+3' de la fiche synthétique) ;
  3. `apply_envelope({"deltas": {"hp_delta": -total}})` — PV décrémentés,
     relus exacts sur l'état re-chargé.

Verdicts mécaniques (D-134) : égalité numérique / présence de sous-chaîne
dans les événements retournés — jamais une lecture de qualité.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.fixtures.element_mold import ElementMold, present
from coderain.memory import Library

import mcp_server

root = os.path.join(tempfile.gettempdir(), "se_element_jet_degats_i206")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
slug = lib.saves.create(
    "ElementJetDegats", mode="rpg",
    premise="Banc synthétique I-206, D-109/D-206 — aucun matériau réel.")
store = lib.store(slug)
assert store.mode() == "rpg" and store.rpg_enabled()

mcp_server._engine = None          # régime dégradé, comme test-schisme-position-i197
mcp_server._store = store
mcp_server._slug = slug
mcp_server._last_applied_events = None

# ---- fixture synthétique : la fiche « givre-hurleur » (ice-fiend factice) --
# Une seule ligne de degats — le format exact vu au banc, D-109/D-206.
FICHE_DEGATS = "9 (1d8+3) slashing"

with ElementMold("jet-degats", budget_seconds=5.0) as mold:
    rpg0 = store.rpg_state()
    hp0 = rpg0["player"]["hp"]

    # ---- 1. le toucher se résout (déjà outillé — roll_check) --------------
    touch = mcp_server.roll_check(stat="agility", dc=8)
    mold.check(
        "1-toucher-resolu",
        isinstance(touch, dict) and "total" in touch and "success" in touch,
        f"roll_check répond {touch!r}")

    # ---- 2. le jet de dégâts résout la formule de la fiche (I-206) --------
    degats = mcp_server.roll_damage(FICHE_DEGATS)
    mold.check(
        "2-degats-roules",
        isinstance(degats, dict) and degats.get("total", -1) >= 0
        and degats.get("dice") and degats.get("formula") == FICHE_DEGATS,
        f"roll_damage({FICHE_DEGATS!r}) -> {degats!r}")

    # déterminisme : même seed+nonce -> même jet (roll_check ci-dessus a déjà
    # consommé un nonce, donc on ne peut pas rejouer EXACTEMENT le même appel
    # MCP ; on vérifie le déterminisme au niveau de la fonction pure à la
    # place, sur un couple (seed, nonce) fixe indépendant de l'état du save).
    from coderain.modules import rpg as rpg_mod
    d1 = rpg_mod.roll_damage(FICHE_DEGATS, seed=123, nonce=7)
    d2 = rpg_mod.roll_damage(FICHE_DEGATS, seed=123, nonce=7)
    mold.check(
        "2b-degats-deterministes",
        d1 == d2,
        f"même seed+nonce -> même jet ({d1} == {d2})")

    # ---- 3. apply_envelope applique la perte de PV (guichet D-141) --------
    total = degats["total"]
    events = mcp_server.apply_envelope(
        __import__("json").dumps({"v": 1, "deltas": {"hp_delta": -total}}),
        rpg_on=True)
    mold.check(
        "3a-evenement-hp-journalise",
        present(" ".join(events), f"hp: -{total}"),
        f"événements: {events!r}")

    hp_attendu = max(0, hp0 - total)
    hp_relu = store.rpg_state()["player"]["hp"]
    mold.check(
        "3b-pv-decrementes-exacts",
        hp_relu == hp_attendu,
        f"PV avant={hp0}, dégâts={total}, attendu={hp_attendu}, relu={hp_relu}")

    # ---- 4. le validateur rejette toujours une formule brute non-résolue --
    # (le trou original du banc : proposer directement 'damage'/'formula' au
    # lieu d'un hp_delta déjà calculé reste refusé — la formule DOIT passer
    # par roll_damage d'abord, jamais un delta jeté cru au guichet.)
    from coderain import validator as validator_mod
    clean, rejected = validator_mod.validate(
        {"v": 1, "deltas": {"damage": FICHE_DEGATS}}, store)
    mold.check(
        "4-formule-brute-toujours-refusee",
        not clean.get("deltas") and any(r["delta"] == "damage" for r in rejected),
        f"rejected={rejected!r}")

assert mold.report(), "test-element-jet-degats-i206: au moins un verdict a échoué"
print("test-element-jet-degats-i206: OK — moule I-382, chaîne toucher→dégâts→PV, "
      "banc craquement-2.md tour 21 rejoué synthétiquement")
