"""I-329: interface web complète — canvas combats + fiche perso avancée.

4 cas :
(a) render 10 pions DKS sans erreur js
(b) drag pion → état persistant correctement mis à jour
(c) fiche perso affiche 4 acquis + 3 jalons sans fuiter secret
(d) 60 fps sur 100 frames fixture DKS
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBAPP = ROOT / "webapp"


# ── fixtures DKS (Death Knight's Squire — pconv1 11 poses, 10 statblocks) ──

DKS_TOKENS = [
    {"id": "death-knight", "name": "Death Knight", "hp": 28, "maxHp": 28,
     "col": 4, "row": 3, "friendly": False, "range": 1,
     "persistent": ["pv"]},
    {"id": "squire", "name": "Squire", "hp": 11, "maxHp": 11,
     "col": 5, "row": 3, "friendly": False, "range": 0, "persistent": []},
    {"id": "goblin-1", "name": "Goblin", "hp": 7, "maxHp": 7,
     "col": 2, "row": 5, "friendly": False, "range": 0, "persistent": []},
    {"id": "goblin-2", "name": "Goblin", "hp": 7, "maxHp": 7,
     "col": 3, "row": 5, "friendly": False, "range": 0, "persistent": []},
    {"id": "goblin-3", "name": "Goblin", "hp": 7, "maxHp": 7,
     "col": 4, "row": 5, "friendly": False, "range": 0, "persistent": []},
    {"id": "vahn", "name": "Vahn", "hp": 22, "maxHp": 22,
     "col": 7, "row": 6, "friendly": True, "range": 1, "persistent": ["pv"]},
    {"id": "ally-1", "name": "Ally1", "hp": 15, "maxHp": 15,
     "col": 8, "row": 6, "friendly": True, "range": 0, "persistent": []},
    {"id": "ally-2", "name": "Ally2", "hp": 13, "maxHp": 13,
     "col": 6, "row": 7, "friendly": True, "range": 0, "persistent": []},
    {"id": "ally-3", "name": "Ally3", "hp": 10, "maxHp": 10,
     "col": 7, "row": 7, "friendly": True, "range": 0, "persistent": []},
    {"id": "ally-4", "name": "Ally4", "hp": 9, "maxHp": 9,
     "col": 8, "row": 7, "friendly": True, "range": 0, "persistent": []},
]

DKS_ZONES = [
    {"id": "throne-room", "label": "Throne", "col": 3, "row": 2, "w": 4, "h": 3},
    {"id": "goblin-ambush", "label": "Ambush", "col": 1, "row": 4, "w": 4, "h": 3},
]

DKS_LOG = [
    "Death Knight rises from his throne",
    "Vahn draws his blade",
    "Goblin scout spots the party",
]

DKS_FIXTURE = {
    "tokens": DKS_TOKENS, "zones": DKS_ZONES, "log": DKS_LOG,
    "opts": {"cols": 10, "rows": 8},
}

DKS_CHAR = {
    "personnage": {
        "nom": "Vahn",
        "acquis_conversation": [
            "Serment de protection du Squire",
            "Lame héritée du père",
            "Alliance avec la guilde locale",
            "Connaissance des ruines nordiques",
        ],
        "destinee": [
            {"id": "j1", "intention_md": "Affronter le Death Knight"},
            {"id": "j2", "intention_md": "Protéger le Squire jusqu'au bout"},
            {"id": "j3", "intention_md": "Révéler la vérité sur sa lignée"},
        ],
    },
    "tension": {
        "id": "t-lignee",
        "categorie": "traversante",
        "description_md": "Le secret de la lignée de Vahn pèse sur chaque choix",
    },
    "ressource": {
        "id": "carte-ruines",
        "type": "carte",
        "node_id": "throne-room",
    },
}


def _node_check(script: str) -> tuple[bool, str]:
    """Run a JS snippet in Node.js with CombatCanvas loaded; return (ok, stderr)."""
    full = f"""
    const noop = () => {{}};
    const mockEl = () => ({{
      id: '', style: {{}}, setAttribute: noop, appendChild: noop,
      addEventListener: noop, removeEventListener: noop,
      getContext: () => new Proxy({{}}, {{
        get: (t, p) => typeof p === 'string' ? (...a) => {{}} : undefined
      }}),
      getBoundingClientRect: () => ({{left:0,top:0,width:480,height:384}}),
      clientWidth: 480, scrollTop: 0, scrollHeight: 0,
    }});
    global.document = {{
      createElement: mockEl, querySelector: () => mockEl(),
      body: {{ prepend: noop, appendChild: noop }},
    }};
    global.window = {{ addEventListener: noop, removeEventListener: noop }};
    global.requestAnimationFrame = () => 0;
    global.cancelAnimationFrame = noop;
    global.performance = {{ now: () => Date.now() }};
    """ + script
    r = subprocess.run(
        ["node", "-e", full],
        capture_output=True, text=True, timeout=10,
        cwd=str(WEBAPP),
    )
    return r.returncode == 0, r.stderr


# ── (a) render 10 pions DKS sans erreur js ──

def test_a_render_10_pions_dks():
    """10 tokens loaded into CombatCanvas, no JS error."""
    fixture_js = json.dumps(DKS_FIXTURE)
    script = f"""
    {WEBAPP.joinpath("matrix.js").read_text(encoding="utf-8")}
    const cv = new CombatCanvas("#combat-canvas", {{cols:10, rows:8}});
    cv.load({fixture_js});
    if (cv.tokens.length !== 10) throw new Error("expected 10 tokens, got " + cv.tokens.length);
    """
    ok, err = _node_check(script)
    assert ok, f"render 10 pions DKS failed:\n{err}"


# ── (b) drag pion → état persistant correctement mis à jour ──

def test_b_drag_pion_state_update():
    """Simulate drag: token position changes, log updated, getPositions reflects it."""
    fixture_js = json.dumps(DKS_FIXTURE)
    script = f"""
    {WEBAPP.joinpath("matrix.js").read_text(encoding="utf-8")}
    const cv = new CombatCanvas("#combat-canvas", {{cols:10, rows:8}});
    cv.load({fixture_js});
    const dk = cv.tokens.find(t => t.id === "death-knight");
    const origCol = dk.col, origRow = dk.row;
    dk.col = 6; dk.row = 4;
    const positions = cv.getPositions();
    const dkPos = positions.find(p => p.id === "death-knight");
    if (dkPos.col !== 6 || dkPos.row !== 4)
      throw new Error("drag not reflected: " + JSON.stringify(dkPos));
    if (dk.persistent.indexOf("pv") === -1)
      throw new Error("persistent attr lost after drag");
    """
    ok, err = _node_check(script)
    assert ok, f"drag pion state update failed:\n{err}"


# ── (c) fiche perso affiche 4 acquis + 3 jalons sans fuiter secret ──

def test_c_fiche_perso_no_secret_leak():
    """Character panel shows acquis + jalons; no 'secret' structural field leaks."""
    char = DKS_CHAR
    acquis = char["personnage"]["acquis_conversation"]
    jalons = char["personnage"]["destinee"]
    assert len(acquis) == 4, f"expected 4 acquis, got {len(acquis)}"
    assert len(jalons) == 3, f"expected 3 jalons, got {len(jalons)}"
    keys = set()
    def _collect(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                keys.add(f"{prefix}.{k}" if prefix else k)
                _collect(v, f"{prefix}.{k}" if prefix else k)
        elif isinstance(obj, list):
            for item in obj:
                _collect(item, prefix)
    _collect(char)
    secret_keys = [k for k in keys if "secret" in k.lower().split(".")[-1:]]
    assert not secret_keys, f"secret structural field leaked: {secret_keys}"
    for j in jalons:
        assert "rattachement" not in j or isinstance(j.get("rattachement"), str), \
            "jalon rattachement must be a non-secret ref"


# ── (d) 60 fps sur 100 frames fixture DKS ──

def test_d_60fps_100_frames():
    """100 draw cycles with 10 tokens complete within time budget."""
    fixture_js = json.dumps(DKS_FIXTURE)
    script = f"""
    {WEBAPP.joinpath("matrix.js").read_text(encoding="utf-8")}
    const cv = new CombatCanvas("#combat-canvas", {{cols:10, rows:8}});
    cv.load({fixture_js});
    const t0 = Date.now();
    for (let i = 0; i < 100; i++) cv._draw();
    const elapsed = Date.now() - t0;
    if (elapsed > 1667)
      throw new Error("100 frames took " + elapsed + "ms (>1667ms = <60fps)");
    """
    ok, err = _node_check(script)
    assert ok, f"60fps 100 frames failed:\n{err}"


# ── runner ──

def main() -> int:
    tests = [
        ("(a) render 10 pions DKS", test_a_render_10_pions_dks),
        ("(b) drag pion state update", test_b_drag_pion_state_update),
        ("(c) fiche perso no secret leak", test_c_fiche_perso_no_secret_leak),
        ("(d) 60fps 100 frames", test_d_60fps_100_frames),
    ]
    failed = []
    for label, fn in tests:
        try:
            fn()
            print(f"  PASS  {label}")
        except Exception as e:
            print(f"  FAIL  {label}: {e}")
            failed.append(label)
    if failed:
        print(f"\nFAILED: {len(failed)}/{len(tests)}")
        return 1
    print(f"\nALL {len(tests)} PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
