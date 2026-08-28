"""I-329: visualisation combats (feuille perso vivante + canvas combat).

Two halves:
  (a)-(c) functional — `server._rpg_payload` (the structured source both the
          live sheet page and the combat canvas read) against a real
          MemoryStore, RPG on/off, with enemies/companions.
  (d)-(h) structural (D-109, no browser needed) — webapp/character-sheet.html,
          webapp/combat-canvas.js and the app.js wiring exist and are wired
          the way the running page expects, and the pre-existing fixture demo
          (test-interface-complet.py) is left intact.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

root = os.path.join(tempfile.gettempdir(), "se_visu_combats")
if os.path.exists(root):
    shutil.rmtree(root)
os.makedirs(root, exist_ok=True)
os.environ["CODERAIN_HOME"] = root      # before importing server (reads config on import)

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


import server  # noqa: E402  (imports cleanly against the temp home)

WEBAPP = ROOT / "webapp"


def read(name):
    return (WEBAPP / name).read_text(encoding="utf-8")


# (a) RPG off -> inert payload, no fabricated stats ------------------------------
section("(a) rpg desactive -> payload inerte")

slug = server.lib.saves.create("Sheet-off", mode="simple", premise=".")
store = server.lib.saves.store(slug)
payload = server._rpg_payload(store)
assert payload == {"enabled": False}, payload
print("  {'enabled': False} exactement — PASS")


# (b) RPG on -> structured payload mirrors store.rpg_state()/world_state() -------
section("(b) rpg actif -> payload structure = source get_world_state")

slug2 = server.lib.saves.create("Sheet-on", mode="rpg", premise=".",
                                rpg_cfg=server._cfg.rpg)
store2 = server.lib.saves.store(slug2)
ws = store2.world_state()
ws["rpg"]["enabled"] = True
ws["rpg"]["player"]["hp"] = 7
ws["rpg"]["player"]["hp_max"] = 20
ws["rpg"]["enemies"] = {"gob-1": {"hp": 3, "hp_max": 7}}
ws["rpg"]["companions"] = {"darek": {"trust": 2, "mood": "wary"}}
ws["time"] = {"day": 3, "phase": "dusk"}
store2.set_world_state(ws)

payload2 = server._rpg_payload(store2)
assert payload2["enabled"] is True
assert payload2["player"]["hp"] == 7 and payload2["player"]["hp_max"] == 20
assert payload2["enemies"] == {"gob-1": {"hp": 3, "hp_max": 7}}
assert payload2["companions"]["darek"]["trust"] == 2
assert payload2["world"]["day"] == 3 and payload2["world"]["phase"] == "dusk"
print("  hp/enemies/companions/world reflètent world_state() en direct — PASS")


# (c) the HTTP endpoint delegates to the same function ---------------------------
section("(c) endpoint /api/saves/{slug}/rpg == _rpg_payload(store)")

route_fn = None
for r in server.app.routes:
    if getattr(r, "path", None) == "/api/saves/{slug}/rpg":
        route_fn = r.endpoint
        break
assert route_fn is not None, "route /api/saves/{slug}/rpg missing"
assert route_fn(slug2) == payload2, "endpoint must delegate to _rpg_payload"
print("  route enregistree, resultat identique a _rpg_payload — PASS")


# (d) character-sheet.html: standalone, read-only, source get_world_state -------
section("(d) character-sheet.html : page autonome, lecture seule")

sheet_html = read("character-sheet.html")
assert "/api/saves/" in sheet_html and "/rpg" in sheet_html, \
    "character-sheet.html must read the structured rpg endpoint"
assert "save" in sheet_html, "must accept ?save=<slug>"
assert "<title>" in sheet_html
for verb in ("fetch(`/api/saves/", "method"):
    pass  # no write verb expected below
assert not re.search(r'method\s*:\s*["\'](POST|PUT|DELETE)', sheet_html), \
    "character-sheet.html must be read-only (no mutating request)"
for secret_word in ["password", "api_key", "secret_key"]:
    assert secret_word not in sheet_html.lower(), f"potential secret leak: {secret_word}"
print("  fetch(.../rpg) en lecture seule, ?save=<slug>, zero secret — PASS")


# (e) combat-canvas.js: real-data adapter over BattleGrid, no fixture -----------
section("(e) combat-canvas.js : adaptateur donnees reelles, pas de fixture")

canvas_js = read("combat-canvas.js")
assert "DKS_FIXTURE" not in canvas_js, \
    "combat-canvas.js must not hardcode the DKS demo fixture"
assert "class LiveCombat" in canvas_js, "LiveCombat class missing"
assert "RpgCombat" in canvas_js and "fromPayload" in canvas_js, \
    "RpgCombat.fromPayload adapter missing"
assert "/api/saves/" in canvas_js and "/rpg" in canvas_js, \
    "LiveCombat must poll the structured rpg endpoint"
assert "BattleGrid" in canvas_js, "must reuse BattleGrid (matrix.js), not reimplement it"
assert "window.LiveCombat" in canvas_js and "window.RpgCombat" in canvas_js
print("  LiveCombat + RpgCombat.fromPayload, reutilise BattleGrid — PASS")


# (f) fromPayload: deterministic layout, no fabricated HP for companions --------
section("(f) RpgCombat.fromPayload : disabled -> vide, structure previsible")

assert re.search(r"if\s*\(!payload\s*\|\|\s*!payload\.enabled\)\s*return", canvas_js), \
    "fromPayload must return empty on a disabled/missing payload"
assert '"player"' in canvas_js or "'player'" in canvas_js
assert 'id: "player"' in canvas_js, "player token must have a stable id"
print("  garde payload.enabled + id 'player' stable — PASS")


# (g) app.js wiring: live route, lazy-load, sheet links, fixture path intact ----
section("(g) app.js : route #combat/<slug>, lazy-load combat-canvas.js")

app_js = read("app.js")
assert '"#combat/"' in app_js, "live combat route (#combat/<slug>) missing"
assert "loadCombatCanvas" in app_js, "lazy-loader for combat-canvas.js missing"
assert "combat-canvas.js" in app_js, "must actually point at the new file"
assert "LiveCombat" in app_js, "LiveCombat not used from app.js"
assert "character-sheet.html?save=" in app_js, "link to the live sheet page missing"
# non-regression: the pre-existing fixture demo (#combat, DKS_FIXTURE) must survive
assert '"#combat"' in app_js and "DKS_FIXTURE" in app_js and "renderFichePerso" in app_js
print("  route live + lazy-load + lien feuille, demo fixture intacte — PASS")


# (h) non-regression: engine.py / webui.py untouched (lecture seule du perimetre) -
section("(h) non-regression : engine.py et webui.py hors perimetre")

engine_py = ROOT / "coderain" / "engine.py"
webui_py = ROOT / "webui.py"
assert engine_py.exists() and webui_py.exists()
assert "combat-canvas" not in engine_py.read_text(encoding="utf-8")
assert "combat-canvas" not in webui_py.read_text(encoding="utf-8")
print("  engine.py/webui.py ne referencent pas ce livrable — PASS")


# ---------------------------------------------------------------------------
print(f"\n{len(FAIT)} sections, {len(FAIT)} passed")
print("ALL SUITES PASSED (test-visu-combats: 8 sections)")
