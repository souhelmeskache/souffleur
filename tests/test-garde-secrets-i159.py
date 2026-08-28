"""I-159 -- the secret guard: coderain.validator.scan_hidden_forced flags every
gated-registry entry that is BOTH `hidden: true` and forced always-in
(`pinned: true` or `weight: critical`) -- the one combination memory.py's
assemble() cannot hold back (always = e.pinned() or e.weight() == "critical"
tests BEFORE hidden(), so such an entry activates on every haystack, every
pass, every budget -- see docs/gabarit-autorat-secrets-i159.md).

Measured at I-159's opening: 0/20 hidden entries in the live campaign carried
either flag, so the guard had never actually bitten. This harness exercises
it on synthetic fixtures (D-109: no real campaign material) so the check
stays exercised regardless of what any given campaign happens to author.
"""
import os, shutil, sys, tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain import validator as V
from coderain.memory import Entry, Library

root = os.path.join(tempfile.gettempdir(), "se_garde_secrets_i159")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("Veil", "A masked court, full of secrets."))

# ---- fixtures: two violations, three clean cases ----
store.upsert_entry("characters.md", Entry(
    "The Patron", "the-patron", importance=5,
    attrs={"hidden": "true", "pinned": "true"},
    body="Secretly the player's own father."))
store.upsert_entry("locations.md", Entry(
    "The Ossuary", "the-ossuary", importance=4,
    attrs={"hidden": "true", "weight": "critical"},
    body="Where the bones are actually kept."))
store.upsert_entry("factions.md", Entry(
    "The Veil", "the-veil", importance=3, attrs={"pinned": "true"}))
store.upsert_entry("items.md", Entry(
    "Cursed Ring", "cursed-ring", importance=2, attrs={"hidden": "true"},
    body="Whispers at night."))
store.upsert_entry("canon-events.md", Entry(
    "The Coronation", "the-coronation", importance=3,
    attrs={"weight": "important"}))

report = V.scan_hidden_forced(store)

# ---- 1) exactly the two offending entries are flagged, nothing else ----
by_slug = {hit["slug"]: hit for hit in report}
assert set(by_slug) == {"the-patron", "the-ossuary"}, \
    f"expected exactly the-patron + the-ossuary, got {sorted(by_slug)}"
print("1) hidden+pinned and hidden+critical both flagged; clean cases are not")

# ---- 2) `why` names the correct flag(s), registry is correct ----
assert by_slug["the-patron"]["registry"] == "characters.md"
assert by_slug["the-patron"]["why"] == ["pinned"]
assert by_slug["the-ossuary"]["registry"] == "locations.md"
assert by_slug["the-ossuary"]["why"] == ["critical"]
print("2) why/registry match the authored combination")

# ---- 3) the report never carries title or body -- schema-shaped, spoiler-safe ----
for hit in report:
    assert set(hit) == {"registry", "slug", "why"}, \
        f"report entry carries an extra field: {sorted(hit)}"
    for v in hit.values():
        blob = v if isinstance(v, str) else " ".join(v)
        assert "father" not in blob and "bones" not in blob
print("3) report shape is spoiler-safe (registry/slug/why only)")

# ---- 4) both-flags case reports both, in the documented order ----
store.upsert_entry("items.md", Entry(
    "Doomsday Ledger", "doomsday-ledger", importance=5,
    attrs={"hidden": "true", "pinned": "true", "weight": "critical"},
    body="Names every conspirator."))
report2 = V.scan_hidden_forced(store)
ledger = next(h for h in report2 if h["slug"] == "doomsday-ledger")
assert ledger["why"] == ["pinned", "critical"]
print("4) an entry carrying both flags reports both")

# ---- 5) mcp_server._lore_warnings never names a slug in its player-facing text ----
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
import mcp_server
warnings = mcp_server._lore_warnings(store)
assert warnings, "expected at least one warning line given the fixtures above"
for line in warnings:
    for slug in ("the-patron", "the-ossuary", "doomsday-ledger"):
        assert slug not in line, f"warning line leaked a secret's slug: {line!r}"
print("5) mcp_server._lore_warnings counts violations without naming them")

print("ALL OK -- test-garde-secrets-i159.py")
