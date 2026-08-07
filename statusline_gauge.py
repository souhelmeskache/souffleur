"""Claude Code status line — prints a line for the terminal AND pushes the
context-window gauge to the player's browser screen (meta-rpg MRPG-I-144).

Why: the MCP process serves the conversation but cannot see it, so it has no way
to know how full the context window is. Claude Code does, and hands it to the
status line. This script forwards it to the web screen, so the player never has
to look at the terminal to know when to start a fresh conversation.

Wire it in .claude/settings.json:

    "statusLine": {
      "type": "command",
      "command": "python C:\\\\Users\\\\souhe\\\\coderain\\\\statusline_gauge.py",
      "refreshInterval": 5
    }

refreshInterval matters: the event-driven triggers go quiet while the session
blocks on ui_wait, which is precisely when the player is reading and deciding.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT_FILE = ROOT / ".turn" / "ui_port"

# Two landmarks, both percentages of the context window — so they hold whatever
# the window is (200K, or 1M with the [1m] suffix).
#   ~40%  intelligence starts degrading, slowly. Tolerable in a game, where the
#         engine holds the state and the rules hold the behaviour.
#   ~70%  Claude Code compacts on its own. We stop well before that: the choice
#         to relaunch has to stay the player's.
SEUIL_ATTENTION = 40
SEUIL_ALERTE = 60


def main() -> None:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:  # noqa: BLE001
        data = {}

    cw = data.get("context_window") or {}
    pct = cw.get("used_percentage")
    pct = float(pct) if isinstance(pct, (int, float)) else None
    taille = cw.get("context_window_size") or 200000
    entree = cw.get("total_input_tokens") or 0
    modele = ((data.get("model") or {}).get("display_name")) or "?"
    cout = (data.get("cost") or {}).get("total_cost_usd")

    # 1. push to the browser — best effort, never block the status line
    port = None
    try:
        port = int(PORT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pass
    if port and pct is not None:
        charge = json.dumps({
            "pct": round(pct, 1),
            "tokens": int(entree),
            "size": int(taille),
            "model": modele,
            "cost": cout,
            "seuils": [SEUIL_ATTENTION, SEUIL_ALERTE],
        }).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/gauge", data=charge,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=1).close()
        except Exception:  # noqa: BLE001 — screen closed, wrong port, whatever
            pass

    # 2. the terminal line
    if pct is None:
        print(f"[{modele}] contexte : —")
        return
    plein = int(pct / 10)
    barre = "#" * plein + "." * (10 - plein)
    etat = ("RELANCE" if pct >= SEUIL_ALERTE
            else "attention" if pct >= SEUIL_ATTENTION else "ok")
    ligne = f"[{modele}] {barre} {pct:.0f}% ({entree:,}/{taille:,}) {etat}"
    if isinstance(cout, (int, float)):
        ligne += f" | ${cout:.2f}"
    print(ligne.replace(",", " "))


if __name__ == "__main__":
    main()
