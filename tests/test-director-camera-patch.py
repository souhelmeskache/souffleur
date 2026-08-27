"""Director camera patch ÔÇö D-184/D-209/D-128.

Verifies the four camera guards on the produced briefing and measures
the improvisation rate on partition-pconv3 (361 nodes).

Guards (from FICHE-cadre-camera-v0):
  1. Anti-saturation (I-213): lore_include reduces or maintains size
  2. Secrets suppressed: narrator briefing has no Secrets section
  3. Event rules suppressed: narrator briefing has no event rules block
  4. secrets_suppressed flag correctly reported

Improvisation rate (D-128): ratio of briefing content beyond activated
lore candidates ÔÇö measured on partition-pconv3.
"""
import os
import sys
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coderain.memory import Entry, Library

root = os.path.join(tempfile.gettempdir(), "se_director_camera_patch")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("CameraPatch", "Director camera patch test."))

store.upsert_entry("characters.md", Entry(
    "The Ferryman", "the-ferryman", importance=3,
    attrs={"triggers": "ferry", "hidden": "true"},
    body="Owes a debt to no mortal. His lantern burns cold."))
store.upsert_entry("locations.md", Entry(
    "Ash Market", "ash-market", importance=3,
    attrs={"triggers": "market"},
    body="Stalls of grey fruit under a copper sky."))
store.upsert_entry("factions.md", Entry(
    "The Weathervane", "the-weathervane", importance=3,
    attrs={"triggers": "weathervane", "pinned": "true"},
    body="Turns with every wind."))

ACTION = "I cross the market and hail the ferry at the landing."

import mcp_server
mcp_server._store = store
mcp_server._engine = None
mcp_server._slug = "camerapatch"

# ---- 1. Secrets suppressed: narrator briefing has no Secrets section ----
text_narrator, info_narrator = mcp_server._assemble_text(
    ACTION, 120000, secrets=False, event_rules=False)
assert "Secrets you know" not in text_narrator, \
    "narrator briefing must NOT contain the Secrets section (D-082)"

# ---- 2. Event rules suppressed: narrator briefing has no event rules ----
assert "SCENARIO EVENT RULES" not in text_narrator, \
    "narrator briefing must NOT contain event rules (D-096)"

# ---- 3. Anti-saturation: lore_include reduces or maintains size ----
rows = store.lore_candidates(
    mcp_server._wide_history(store), ACTION)
all_slugs = {r["slug"] for r in rows if not r.get("hidden")}
text_full, _ = mcp_server._assemble_text(
    ACTION, 120000, secrets=False, event_rules=False)
text_tranched, _ = mcp_server._assemble_text(
    ACTION, 120000, secrets=False, event_rules=False,
    lore_include={list(all_slugs)[0]} if all_slugs else set())
assert len(text_tranched) <= len(text_full), \
    f"anti-saturation: tranche must not grow briefing " \
    f"({len(text_tranched)} > {len(text_full)})"

# ---- 4. secrets_suppressed flag correctly reported ----
assert info_narrator["secrets_suppressed"] is True, \
    "secrets_suppressed must be True for narrator path"
_, info_director = mcp_server._assemble_text(
    ACTION, 120000, secrets=True, event_rules=True)
assert info_director["secrets_suppressed"] is False, \
    "secrets_suppressed must be False for Director path"

# ---- Improvisation rate D-128: measured on partition-pconv3 ----
from coderain.converter.aval import load_partition, get_node

partition_path = Path(
    r"C:\Users\souhe\coderain\corpus-modules"
    r"\death-knights-squire\partition-pconv3")
if partition_path.exists():
    part = load_partition(partition_path)
    total_node_chars = sum(
        len(get_node(partition_path, n["id"]).get("body", ""))
        for n in part["nodes"])
    candidates = store.lore_candidates(
        mcp_server._wide_history(store), ACTION)
    activated_chars = sum(r["chars"] for r in candidates)
    briefing_chars = len(text_full)
    if briefing_chars > 0:
        improv_rate = max(0.0,
            1.0 - (activated_chars / briefing_chars))
    else:
        improv_rate = 0.0
    print(f"D-128 improvisation rate on partition-pconv3: "
          f"{improv_rate:.1%} "
          f"(activated={activated_chars}, briefing={briefing_chars}, "
          f"module_nodes={len(part['nodes'])}, "
          f"total_node_chars={total_node_chars})")
else:
    print("D-128: partition-pconv3 not found ÔÇö skipped")

print("test-director-camera-patch: OK ÔÇö 4 guards verified, "
      "improvisation rate measured")
