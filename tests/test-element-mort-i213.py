"""Test d'élément — l'état downed n'avait ni jet de sauvegarde, ni
stabilisation, ni mort actable (Issue #213, moule I-382).

Briques visées : `coderain.modules.rpg.death_save` (nouveau) +
`coderain.validator.validate`/`known_skills`/`skill_trained` (I-213
corollaire 3) + le pont MCP `death_save`/`roll_check`/`validate_envelope`/
`apply_envelope` (`mcp_server.py`) — le trou constaté au banc (run
20260831-202617, tours 27-28, cf. corps de l'Issue #213) : un personnage à
0 PV `downed` n'avait aucun chemin outillé vers un jet de sauvegarde, une
stabilisation ou une mort actée, et le champ `skill` d'un `check` acceptait
n'importe quelle étiquette (`death_save` compris) sans jamais être validé.

Fiche 100 % synthétique (D-109/D-206, aucun matériau de campagne réel).
Dés déterministes (seed+nonce) : les graines ci-dessous ont été sondées à la
main pour produire la séquence de jets voulue par chaque état de fixture
(cf. commentaire sur chaque graine) — même discipline que
`tests/test-element-jet-degats-i206.py`.

Verdicts mécaniques (D-134) : égalité/présence de sous-chaîne, jamais une
lecture de qualité.
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

from coderain.memory import Entry, Library

import mcp_server

root = os.path.join(tempfile.gettempdir(), "se_element_mort_i213")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
slug = lib.saves.create(
    "ElementMort", mode="rpg",
    premise="Banc synthétique I-213, D-109/D-206 — aucun matériau réel.")
store = lib.store(slug)
assert store.mode() == "rpg" and store.rpg_enabled()

# Fiche synthétique : le joueur connaît "discrétion" (accentué) — le repère
# exact employé au banc réel (corps de l'Issue #213).
store.upsert_entry("player.md", Entry(
    title="You", slug="player", importance=5,
    attrs={"skills": "discrétion (agility)"},
    body="**Visual:** Fixture synthétique.\n**Voice:** N/A."))

mcp_server._engine = None          # régime dégradé, comme test-element-jet-degats-i206
mcp_server._store = store
mcp_server._slug = slug
mcp_server._last_applied_events = None


def _set_player(**over):
    rpg = store.rpg_state()
    p = rpg.setdefault("player", {})
    p["hp"] = 0
    p["hp_max"] = max(p.get("hp_max", 10), 10)
    p["conditions"] = ["downed"]
    p["death_saves"] = {"successes": 0, "failures": 0}
    p.update(over)
    rpg["rolls"] = 0
    store.set_rpg_state(rpg)


with ElementMold("mort-i213", budget_seconds=5.0) as mold:
    # ---- (a) 3 échecs -> dead (seed 19: rolls 6,3,7 — aucun 1/20) ---------
    _set_player()
    st = store.rpg_state(); st["seed"] = 19; store.set_rpg_state(st)
    r1 = mcp_server.death_save()
    r2 = mcp_server.death_save()
    r3 = mcp_server.death_save()
    mold.check(
        "a-trois-echecs-dead",
        r3.get("transition") == "dead" and "dead" in r3.get("conditions", [])
        and r1.get("transition") is None and r2.get("transition") is None,
        f"{r1!r} / {r2!r} / {r3!r}")

    # ---- (b) 3 réussites -> stabilized (seed 23: rolls 15,15,12) ----------
    _set_player()
    st = store.rpg_state(); st["seed"] = 23; store.set_rpg_state(st)
    s1 = mcp_server.death_save()
    s2 = mcp_server.death_save()
    s3 = mcp_server.death_save()
    mold.check(
        "b-trois-reussites-stabilized",
        s3.get("transition") == "stabilized"
        and "stabilized" in s3.get("conditions", [])
        and "downed" in s3.get("conditions", [])   # reste downed (inconscient)
        and s3.get("hp") == 0,
        f"{s1!r} / {s2!r} / {s3!r}")

    # ---- (c) 20 naturel -> 1 PV, downed retiré (seed 61: roll 20) --------
    _set_player()
    st = store.rpg_state(); st["seed"] = 61; store.set_rpg_state(st)
    nat20 = mcp_server.death_save()
    mold.check(
        "c-nat20-revit",
        nat20.get("transition") == "revived" and nat20.get("hp") == 1
        and "downed" not in nat20.get("conditions", []),
        f"{nat20!r}")

    # ---- nat 1 -> deux échecs d'un coup (seed 5: roll 1) ------------------
    _set_player()
    st = store.rpg_state(); st["seed"] = 5; store.set_rpg_state(st)
    nat1 = mcp_server.death_save()
    mold.check(
        "c-nat1-deux-echecs",
        nat1.get("death_saves", {}).get("failures") == 2
        and nat1.get("transition") is None,
        f"{nat1!r}")

    # ---- (d) dégât à 0 PV = échec automatique (pas de mort actée ici) -----
    _set_player()
    events = mcp_server.apply_envelope('{"deltas": {"hp_delta": -5}}')
    ds = store.rpg_state()["player"]["death_saves"]
    mold.check(
        "d-degat-a-zero-echec",
        ds["failures"] == 1 and present(" ".join(events), "death save:", "automatic failure"),
        f"events={events!r} death_saves={ds!r}")

    # coup critique -> deux échecs d'un coup
    _set_player()
    mcp_server.apply_envelope('{"deltas": {"hp_delta": -5, "hp_delta_crit": true}}')
    ds_crit = store.rpg_state()["player"]["death_saves"]
    mold.check("d-degat-critique-deux-echecs", ds_crit["failures"] == 2, f"{ds_crit!r}")

    # ---- (e) mutation rejetée une fois `dead` ------------------------------
    rpg = store.rpg_state()
    rpg["player"]["conditions"] = ["dead"]
    store.set_rpg_state(rpg)
    verdict = mcp_server.validate_envelope('{"deltas": {"hp_delta": 5}}')
    mold.check(
        "e-mutation-apres-mort-rejetee",
        not verdict["clean"].get("deltas")
        and any("dead" in r["reason"] for r in verdict["rejected"]),
        f"{verdict!r}")

    # ---- (f) skill hors liste ('death_save') rejeté avec la liste valide --
    _set_player()
    v_bad = mcp_server.validate_envelope(
        '{"check": {"stat": "agility", "skill": "death_save"}}')
    mold.check(
        "f-skill-hors-liste-rejete",
        not v_bad["clean"].get("check")
        and any("unknown skill" in r["reason"] and "perception" in r["reason"]
                for r in v_bad["rejected"]),
        f"{v_bad!r}")

    # compétence composée non reconnue ('perception/écoute')
    v_compound = mcp_server.validate_envelope(
        '{"check": {"stat": "agility", "skill": "perception/écoute"}}')
    mold.check(
        "f-skill-composee-rejetee",
        not v_compound["clean"].get("check"),
        f"{v_compound!r}")

    # ---- (g) skill connue (canon) mais non maîtrisée -> résolue, trained=False
    rc_untrained = mcp_server.roll_check(stat="agility", skill="perception")
    mold.check(
        "g-skill-connue-non-maitrisee",
        "error" not in rc_untrained and rc_untrained.get("trained") is False,
        f"{rc_untrained!r}")

    # ---- (h) 'Discrétion' == 'discretion' (sans casse ni accents) ---------
    rc_accent = mcp_server.roll_check(stat="agility", skill="Discrétion")
    rc_no_accent = mcp_server.roll_check(stat="agility", skill="discretion")
    mold.check(
        "h-accent-fold-discretion",
        rc_accent.get("trained") is True and rc_no_accent.get("trained") is True,
        f"{rc_accent!r} / {rc_no_accent!r}")

    v_bench = mcp_server.validate_envelope(
        '{"check": {"stat": "agility", "skill": "discrétion"}}')
    mold.check(
        "h-banc-discretion-acceptee",
        bool(v_bench["clean"].get("check")), f"{v_bench!r}")
    v_bench2 = mcp_server.validate_envelope(
        '{"check": {"stat": "willpower", "skill": "perception"}}')
    mold.check(
        "h-banc-perception-acceptee",
        bool(v_bench2["clean"].get("check")), f"{v_bench2!r}")

assert mold.report(), "au moins un verdict a echoue"
print("\nMORT-I213 ELEMENT TEST PASSED")
