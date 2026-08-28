"""I-462 -- the agentivity guard: coderain.validator.scan_missing_origin flags
every managed-registry entry (characters/locations/factions/items/canon-events
+ threads.md) whose `origin` attr is absent or not one of player/narrator/
inferred. `Summarizer._apply_promotions` (coderain/summarizer.py) stamps this
attr on every promotion, new thread, and thread resolution the fold writes --
see docs/garde-agentivite-i462.md for the D-107 rule and the exact mechanism
(turn `role` is flattened to prose by `_turns_text` and never echoed back by
the fold's JSON reply, which is how a player-forced fact used to end up
indistinguishable from a spontaneous PNJ reveal).

Measured at I-462's opening: zero fields in the fold's output schema carried
any actor/provenance marker, so the guard had nothing to check. This harness
exercises the marking end-to-end (fold JSON -> _apply_promotions -> store)
plus the guard alone on hand-authored fixtures (D-109: no real campaign
material).
"""
import os, shutil, sys, tempfile

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain import validator as V
from coderain.memory import Entry, Library
from coderain.summarizer import Summarizer

root = os.path.join(tempfile.gettempdir(), "se_garde_agentivite_i462")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("Veil", "A masked court, full of secrets."))


class Cfg:
    memory = {}
    generation = {}


sm = Summarizer(Cfg(), store, llm=None)

# ---- 1) promotions: a player-forced fact keeps its stamp ----
sm._apply_promotions({"promotions": [
    {"kind": "character", "slug": "elira", "title": "Elira", "importance": 3,
     "detail": "Confessed to poisoning the well.", "origin": "player"},
]})
elira = next(e for e in store.entries("characters.md") if e.slug == "elira")
assert elira.attrs.get("origin") == "player", elira.attrs
print("1) a player-declared promotion keeps its origin stamp")

# ---- 2) promotions: a missing/garbage origin degrades to "inferred", never
#         dropped -- a partial fold must still advance (D-107 graceful
#         degradation, same philosophy as the rest of the module) ----
sm._apply_promotions({"promotions": [
    {"kind": "character", "slug": "kaelen", "title": "Kaelen", "importance": 3,
     "detail": "A grim knight."},  # no "origin" at all
    {"kind": "location", "slug": "ashford", "title": "Ashford", "importance": 2,
     "detail": "A river town.", "origin": "made-up-value"},
]})
kaelen = next(e for e in store.entries("characters.md") if e.slug == "kaelen")
ashford = next(e for e in store.entries("locations.md") if e.slug == "ashford")
assert kaelen.attrs.get("origin") == "inferred", kaelen.attrs
assert ashford.attrs.get("origin") == "inferred", ashford.attrs
print("2) missing/invalid origin degrades to 'inferred', promotion still lands")

# ---- 3) new threads and their resolution each carry their own origin key ----
sm._apply_promotions({"new_threads": [
    {"slug": "the-debt", "title": "The Debt", "importance": 4,
     "detail": "Owed to the patron.", "origin": "narrator"},
]})
debt = next(e for e in store.entries("threads.md") if e.slug == "the-debt")
assert debt.attrs.get("origin") == "narrator", debt.attrs
sm._apply_promotions({"resolved_threads": [
    {"slug": "the-debt", "origin": "player"},
]})
debt = next(e for e in store.entries("threads.md") if e.slug == "the-debt")
assert debt.attrs.get("status") == "resolved", debt.attrs
assert debt.attrs.get("resolved_origin") == "player", debt.attrs
# opening and closing a thread can have different actors -- both survive
assert debt.attrs.get("origin") == "narrator", debt.attrs
print("3) thread creation and resolution carry independent origin stamps")

# ---- 4) a bare resolved-thread slug (older/partial fold shape) still works,
#         and still stamps a valid origin ----
sm._apply_promotions({"new_threads": [
    {"slug": "old-shape", "title": "Old Shape", "detail": "x", "origin": "player"}]})
sm._apply_promotions({"resolved_threads": ["old-shape"]})
old = next(e for e in store.entries("threads.md") if e.slug == "old-shape")
assert old.attrs.get("resolved_origin") == "inferred", old.attrs
print("4) bare-string resolved_threads (back-compat) still stamps a valid origin")

# ---- 5) the guard itself: flags only entries with no valid origin ----
store.upsert_entry("factions.md", Entry(
    "The Veil", "the-veil", importance=3, attrs={}))  # hand-authored, no origin
store.upsert_entry("items.md", Entry(
    "Cursed Ring", "cursed-ring", importance=2, attrs={"origin": "narrator"}))
report = V.scan_missing_origin(store)
by_slug = {hit["slug"]: hit for hit in report}
assert "the-veil" in by_slug, by_slug
assert by_slug["the-veil"]["registry"] == "factions.md"
assert "cursed-ring" not in by_slug, by_slug
assert "elira" not in by_slug and "kaelen" not in by_slug and "ashford" not in by_slug
print("5) scan_missing_origin flags only entries lacking a valid origin")

# ---- 6) report shape is spoiler-safe: registry/slug only ----
for hit in report:
    assert set(hit) == {"registry", "slug"}, \
        f"report entry carries an extra field: {sorted(hit)}"
print("6) report shape is spoiler-safe (registry/slug only)")

print("ALL OK -- test-garde-agentivite-i462.py")
