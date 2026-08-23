"""The camera's selection stage — the Director's tranche over activation.

Covers:
  lore_include on assemble() — an activated entry not named (and not forced)
    is dropped BEFORE the budget competition; pinned/critical stay in.
  lore_candidates() — the documentaliste's report: same scan, same groups,
    same budget as assemble(); metadata only; hidden entries flagged.
  No-tranche parity — omitting lore_include must be byte-identical to naming
    every candidate (the tranche is opt-in, never a behavior change by itself).
"""
import os, sys, shutil, tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.memory import Entry, Library

root = os.path.join(tempfile.gettempdir(), "se_camera")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("Camera", "A selection test."))

store.upsert_entry("locations.md", Entry(
    "Ash Market", "ash-market", importance=3,
    attrs={"triggers": "market"}, body="Stalls of grey fruit."))
store.upsert_entry("characters.md", Entry(
    "The Tollman", "the-tollman", importance=3,
    attrs={"triggers": "tollman"}, body="Counts coins twice."))
store.upsert_entry("factions.md", Entry(
    "The Weathervane", "the-weathervane", importance=3,
    attrs={"pinned": "true"}, body="Turns with every wind."))

ACTION = "I cross the market and greet the tollman."


def sysmsg(text, **kw):
    return store.assemble([], text, **kw)[0]["content"]


# ---- 1. the tranche drops an activated entry that is not named ----
both = sysmsg(ACTION)
assert "Ash Market" in both and "The Tollman" in both
only_toll = sysmsg(ACTION, lore_include={"the-tollman"})
assert "The Tollman" in only_toll, "selected entry must stay"
assert "Ash Market" not in only_toll, "unselected entry must go"
assert "The Weathervane" in only_toll, "pinned entries are unfilterable"

# ---- 2. candidates report == what activation would serve ----
rows = store.lore_candidates([], ACTION)
by_slug = {r["slug"]: r for r in rows}
assert {"ash-market", "the-tollman", "the-weathervane"} <= set(by_slug), \
    f"candidates miss activated slugs: {sorted(by_slug)}"
assert by_slug["the-weathervane"]["forced"] is True
assert all(r["chars"] > 0 for r in rows)

# hidden entries activate into their own section; they must show up flagged
store.upsert_entry("characters.md", Entry(
    "The Ferryman", "the-ferryman", importance=3,
    attrs={"triggers": "ferry", "hidden": "true"}, body="Owes a debt."))
rows = store.lore_candidates([], "I hail the ferry at the landing.")
hidden_rows = [r for r in rows if r.get("hidden")]
assert [r["slug"] for r in hidden_rows] == ["the-ferryman"], \
    f"activated hidden entry must be reported flagged: {hidden_rows}"

# ---- 3. no-tranche parity: None == naming every visible candidate ----
plain = sysmsg("I cross the market.")
rows = store.lore_candidates([], "I cross the market.")
all_slugs = {r["slug"] for r in rows if not r.get("hidden")}
with_all = sysmsg("I cross the market.", lore_include=all_slugs)
assert plain == with_all, "naming every candidate must equal no tranche"

# ---- 4. the tranche does not touch the Secrets section ----
sec_plain = sysmsg("I hail the ferry.")
sec_tranched = sysmsg("I hail the ferry.", lore_include=set())
assert "The Ferryman" in sec_tranched, \
    "hidden entries are governed by the secrets dial, never by the tranche"
assert "The Ash Market" not in sec_tranched
print("camera_selection_test: OK — tranche, candidates report, parity, "
      "forced bypass, hidden flagging")
