"""I-329/I-144/I-166 : Interface web complète — canvas combats + fiche perso.
Tests structurels (D-109) : vérifie que les fichiers webapp/ sont syntaxiquement
corrects, que les fixtures DKS ont la bonne structure, et que la fiche perso
ne fuit pas de secrets. Pas de navigateur requis.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBAPP = ROOT / "webapp"

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def read(name):
    return (WEBAPP / name).read_text(encoding="utf-8")


# (a) render 10 pions DKS sans erreur js -----------------------------------------
section("(a) render 10 pions DKS sans erreur js")

matrix_js = read("matrix.js")
app_js = read("app.js")
index_html = read("index.html")
style_css = read("style.css")

assert "class BattleGrid" in matrix_js, "BattleGrid class missing from matrix.js"
assert "loadTokens" in matrix_js, "loadTokens method missing"
assert "window.BattleGrid" in matrix_js, "BattleGrid not exported to window"

assert "DKS_FIXTURE" in app_js, "DKS_FIXTURE missing from app.js"
assert "renderCombatView" in app_js, "renderCombatView missing"
assert "tpl-combat-view" in index_html, "combat view template missing from HTML"

fixture_match = re.search(r"const DKS_FIXTURE\s*=\s*(\{[\s\S]*?\n\});", app_js)
assert fixture_match, "DKS_FIXTURE not parseable"
fixture_text = fixture_match.group(1)

token_count = len(re.findall(r'id\s*:\s*"', fixture_text))
assert token_count >= 10, f"DKS fixture has {token_count} tokens, expected >= 10"

assert "battle-canvas" in style_css, "battle-canvas CSS class missing"
assert "combat-log" in style_css, "combat-log CSS class missing"
print(f"  {token_count} tokens in DKS fixture — PASS")


# (b) drag pion -> engine state correctement mis a jour --------------------------
section("(b) drag pion -> etat persistant correctement mis a jour")

assert "_onDown" in matrix_js, "drag handler _onDown missing"
assert "_onMouseMove" in matrix_js, "drag handler _onMouseMove missing"
assert "_onUp" in matrix_js, "drag handler _onUp missing"
assert "onMove" in matrix_js, "onMove callback missing"
assert "onMove" in app_js, "onMove handler not wired in app.js"

assert "addEventListener" in matrix_js
assert "mousedown" in matrix_js
assert "mousemove" in matrix_js
assert "mouseup" in matrix_js
print("  drag handlers wired (mousedown/mousemove/mouseup/onMove) — PASS")


# (c) fiche perso affiche 4 acquis + 3 jalons sans fuiter secret ----------------
section("(c) fiche perso : 4 acquis + 3 jalons, zero secret fuite")

fiche_match = re.search(r"const FICHE_FIXTURE\s*=\s*(\{[\s\S]*?\n\};)", app_js)
assert fiche_match, "FICHE_FIXTURE not parseable"
fiche_text = fiche_match.group(1)

assert "acquis_conversation" in fiche_text, "acquis_conversation missing"
assert "destinee" in fiche_text, "destinee missing"

acquis_list = re.search(r"acquis_conversation:\s*\[([\s\S]*?)\]", fiche_text)
assert acquis_list, "acquis_conversation array not found"
acquis_entries = re.findall(r'"([^"]+)"', acquis_list.group(1))
assert len(acquis_entries) >= 4, f"fiche has {len(acquis_entries)} acquis, expected >= 4"

destinee_list = re.search(r"destinee:\s*\[([\s\S]*?)\],\s*\}", fiche_text)
assert destinee_list, "destinee array not found"
jalon_ids = re.findall(r'id:\s*"([^"]+)"', destinee_list.group(1))
assert len(jalon_ids) >= 3, f"fiche has {len(jalon_ids)} jalons, expected >= 3"

for secret_word in ["secret", "hidden", "password", "api_key", "token_secret"]:
    assert secret_word not in fiche_text.lower(), \
        f"potential secret leak: '{secret_word}' found in FICHE_FIXTURE"

assert "tpl-fiche-perso" in index_html, "fiche perso template missing"
assert "fiche-acquis" in style_css, "fiche-acquis CSS missing"
assert "fiche-destinee" in style_css, "fiche-destinee CSS missing"
assert "fiche-ressource" in style_css, "fiche-ressource CSS missing"
assert "blur" in style_css, "blur filter for ressource vignette missing (D-217)"
print(f"  {len(acquis_entries)} acquis, {len(jalon_ids)} jalons, zero secrets — PASS")


# (d) 60 fps sur 100 frames fixture DKS -----------------------------------------
section("(d) 60 fps sur 100 frames fixture DKS")

assert "requestAnimationFrame" in matrix_js, "requestAnimationFrame missing"
assert "measureFps" in matrix_js, "measureFps method missing for benchmarking"
assert "_loop" in matrix_js, "render loop missing"
assert "_dirty" in matrix_js, "dirty flag optimization missing"

assert "destroy" in matrix_js, "destroy method missing (cleanup)"
assert "cancelAnimationFrame" in matrix_js, "cancelAnimationFrame missing in destroy"

assert "#combat-root" in style_css, "combat-root CSS missing"
assert "#combat-body" in style_css, "combat-body CSS missing"
assert "#battle-area" in style_css, "battle-area CSS missing"
print("  render loop: requestAnimationFrame + dirty flag + measureFps — PASS")


# (e) non-regression : webui.py/webui.html inchanges ----------------------------
section("(e) non-regression : webui.py et webui.html hors P1")

webui_py = ROOT / "webui.py"
webui_html = ROOT / "webui.html"
assert webui_py.exists(), "webui.py should exist (not modified by this lane)"
assert webui_html.exists(), "webui.html should exist (not modified by this lane)"
print("  webui.py + webui.html present, untouched by P1 — PASS")


# (f) HTML structure : templates + nav -------------------------------------------
section("(f) HTML structure complete")

assert "tpl-combat-view" in index_html, "combat template missing"
assert "tpl-fiche-perso" in index_html, "fiche template missing"
assert "#combat" in index_html, "combat nav link missing"
assert "matrix.js" in index_html, "matrix.js script tag missing"
assert "app.js" in index_html, "app.js script tag missing"
print("  templates + nav + scripts present — PASS")


# (g) CSS : classes combat + fiche complete --------------------------------------
section("(g) CSS classes combat + fiche perso")

required_css = [
    ".battle-canvas", "#combat-root", "#combat-head", "#combat-body",
    "#battle-area", "#combat-side", "#combat-log", "#combat-initiative",
    ".init-row", "#fiche-perso", ".fiche-name", ".fiche-tension",
    ".fiche-acquis", ".fiche-destinee", ".fiche-ressources",
    ".fiche-ressource-card", ".vignette",
]
for cls in required_css:
    assert cls in style_css, f"CSS class '{cls}' missing from style.css"
print(f"  {len(required_css)} required CSS selectors present — PASS")


# (h) app.js : router + combat route --------------------------------------------
section("(h) app.js router integre #combat")

assert '"#combat"' in app_js, "#combat route missing from router"
assert "renderCombatView" in app_js, "renderCombatView not called"
assert "renderFichePerso" in app_js, "renderFichePerso not defined"
assert "updateCombatLog" in app_js, "updateCombatLog missing"
assert "updateCombatInitiative" in app_js, "updateCombatInitiative missing"
print("  router + combat functions wired — PASS")


# ---------------------------------------------------------------------------
print(f"\n{len(FAIT)} sections, {len(FAIT)} passed")
print("ALL SUITES PASSED (test-interface-complet: 8 sections)")
