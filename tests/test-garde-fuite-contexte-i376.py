"""I-376 -- the context-leak guard: three doctrine interdicts on what reaches
the narrator (and, downstream, the player), checked against the REAL
`MemoryStore.assemble()` pipeline (coderain/memory.py, ~line 1364) rather than
a hand-built sample:

  1. Internal ids never appear as literal text -- an attribute like
     `node_id: xyz123` or `tension_id: abc789` on any indexed entry (player
     sheet, threads, active lore) must not survive into the assembled
     narrator context. `Entry.render()` (memory.py:307) dumps every attr
     verbatim -- correct for its OTHER job, writing an entry back to its
     Markdown file byte-for-byte (memory.py:447/454, `upsert_entry`'s
     round-trip) -- but assemble()'s narrator-facing sections go through the
     sibling `_context_render()` (memory.py, added by I-376), which drops
     internal-only attr keys (hidden/pinned/weight/triggers/.../origin) and
     any key shaped like an id (`*_id`, `*_uuid`, bare `id`).

  2. No explicit "hidden"/secret-status marker leaks into the sections a
     player's own sheet, open threads, or actively-triggered (non-hidden)
     lore render through -- same `_context_render()` filter, checked here on
     the `hidden` key specifically since that is the literal word D-82 (the
     secrets guard, I-159) says the narrator must never see spelled out
     OUTSIDE the one sanctioned "Secrets you know" channel.

  3. player.md's own body (the character sheet's prose/background) DOES
     reach the narrator -- verified as an assertion of INTENDED behavior, not
     a leak: it is the "You" section (memory.py:1379-1384), the one place the
     narrator learns who the protagonist is. No D-135-shaped rule in this
     repo forbids that (D-135, as it actually exists in
     coderain/converter/schemas.py, governs destiny-milestone tense in the
     character converter -- unrelated to assemble()). This test locks the
     ACTUAL guarantee instead: player.md's body is intentionally served
     verbatim, while its internal-only attrs (same node_id/hidden filter as
     everywhere else) are not.

Scope note on the "Secrets you know" section (hidden entries that activated,
memory.py's `hidden_hits`): that section deliberately keeps raw
`Entry.render()`, unfiltered, on purpose -- mcp_server.py's secret-splice /
leak-exposure guard (`_splice_secrets`, `_hidden_exposure`,
`_secrets_segment`, comment at mcp_server.py:1056) matches a hidden entry by
finding this EXACT rendered text inside the assembled context, byte for byte;
routing it through `_context_render()` instead was tried during I-376 and
broke that existing guard (tests/... test-director-camera-patch.py started
failing "secrets section not located exactly once" -- reverted). So this
guard does NOT check that section for a raw `hidden: true`/id text: a hidden
entry's full body (ids and all, if an author put one there) is expected
inside "Secrets you know" -- that is the one sanctioned channel (D-82), and a
separate, pre-existing guard already owns leak detection out of it.

Fixtures are 100% synthetic (D-109): no real campaign material.
"""
import os, shutil, sys, tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.memory import Entry, Library

root = os.path.join(tempfile.gettempdir(), "se_garde_fuite_contexte_i376")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("Veil", "A masked court, full of secrets."))

# ---- fixtures: one trap per interdict, plus one clean control ----

# 1) player.md: legitimate biography prose (must reach the narrator) PLUS an
#    internal id attr riding on the same entry (must NOT).
store.upsert_entry("player.md", Entry(
    "Protagonist", "player", importance=5,
    attrs={"stats": "strength 3, agility 2", "node_id": "PLAYERNODE-Q7F2"},
    body="BIOGRAPHY-FIXTURE-M4K9: raised in a monastery, secretly royal blood."))

# 2) threads.md: an open (non-hidden) thread carrying an internal id attr.
store.upsert_entry("threads.md", Entry(
    "The Debt", "the-debt", importance=3, attrs={
        "status": "open", "tension_id": "THREADTENSION-P3X8"},
    body="Owed to a patron whose name is not yet known."))

# 3) characters.md: a PINNED (always-active, non-hidden) character carrying
#    both an internal id attr and a literal "hidden: false" (the false case
#    must not print the word "hidden" either -- the filter is on the key,
#    not the value).
store.upsert_entry("characters.md", Entry(
    "The Guard Captain", "guard-captain", importance=4, attrs={
        "pinned": "true", "hidden": "false",
        "node_id": "CHARNODE-V9L1"},
    body="A stern watch captain who trusts no one easily."))

# 4) A genuinely HIDDEN entry with a distinctive slug/marker -- must activate
#    (trigger hit) so it lands in the "Secrets you know" section, the one
#    sanctioned, framed channel (D-82) -- never as a plain visible entry.
store.upsert_entry("characters.md", Entry(
    "The Patron", "the-patron", importance=5,
    attrs={"hidden": "true", "triggers": "patron",
           "node_id": "SECRETNODE-DO-NOT-CARE"},
    body="SECRET-FIXTURE-H8R3: the patron is the player's own father."))

# 5) clean control: an ordinary visible entry with no traps at all.
store.upsert_entry("locations.md", Entry(
    "The Old Bridge", "old-bridge", importance=3,
    body="A stone bridge over the ravine."))

# ---- assemble the REAL narrator context (not a hand-built sample) ----
messages = store.assemble(
    [], "I approach the patron near the old bridge and ask about the debt.",
    budget_tokens=8000)
assert messages and messages[0].get("role") == "system", \
    "assemble() must produce a system message"
text = "\n".join(m.get("content", "") for m in messages)

# ---- split the assembled text into "Secrets" vs everything else, so the
#      scope note above is enforced structurally, not just documented ----
secrets_marker = "Secrets you know"
sec_idx = text.find(secrets_marker)
assert sec_idx != -1, "the hidden trigger must have activated the Secrets section"
before_secrets = text[:sec_idx]
# the Secrets section is appended once, near the end of the salience-ordered
# sections -- but to be robust to future reordering, isolate everything that
# is NOT inside the paragraph block starting at the marker up to the next
# "## " section title that isn't part of it. Simpler and just as safe here:
# the fixtures below never reuse the same marker text anywhere else, so a
# substring check against the WHOLE text minus the exact secrets block is
# equivalent for our purposes -- verified by finding the block explicitly.
secrets_block_end = text.find("\n\n\n", sec_idx)  # next top-level section gap
if secrets_block_end == -1:
    secrets_block_end = len(text)
secrets_block = text[sec_idx:secrets_block_end]
non_secret_text = before_secrets + text[secrets_block_end:]

# ---- 1) internal ids never appear as literal text OUTSIDE the Secrets block
for marker in ("PLAYERNODE-Q7F2", "THREADTENSION-P3X8", "CHARNODE-V9L1"):
    assert marker not in non_secret_text, \
        f"internal id leaked outside the Secrets section: {marker!r}"
    assert marker not in text or marker == "SECRETNODE-DO-NOT-CARE", \
        f"unexpected id leak: {marker!r}"
for key in ("node_id:", "tension_id:"):
    assert key not in non_secret_text, \
        f"raw internal-id attribute key leaked outside Secrets: {key!r}"
print("1) node_id/tension_id attrs never appear as literal text "
      "outside the Secrets section")

# ---- 2) no explicit hidden-status marker outside the Secrets section
assert "hidden: true" not in non_secret_text
assert "hidden: false" not in non_secret_text
assert "hidden:" not in non_secret_text
print("2) no explicit 'hidden:' marker leaks outside the Secrets section")

# ---- 3) player.md biography prose DOES reach the narrator (intended, "You"
#         section) -- while its own node_id attr still does not
assert "BIOGRAPHY-FIXTURE-M4K9" in text, \
    "player.md's body is meant to reach the narrator (the 'You' section)"
assert "PLAYERNODE-Q7F2" not in text, \
    "player.md's internal id attr must never reach the narrator"
print("3) player.md biography prose is served (intended); its internal id is not")

# ---- 4) the hidden entry's distinctive marker is confined to the Secrets
#         section, never in a plain/visible registry section
assert "SECRET-FIXTURE-H8R3" in secrets_block, \
    "the hidden entry's body should surface inside the sanctioned Secrets block"
assert "SECRET-FIXTURE-H8R3" not in non_secret_text, \
    "a hidden entry's body must never appear OUTSIDE the Secrets section"
print("4) hidden entry content is confined to the sanctioned Secrets section")

# ---- 5) the clean control entry renders normally, untouched by the filter
assert "The Old Bridge" in text or "old-bridge" in text.lower()
print("5) a plain entry with no traps still renders normally")

# ---- demonstrated failure mode (documented, not executed): before I-376's
#      `_context_render()` fix, `Entry.render()` (which dumps every attr
#      verbatim) was used directly at the player.md / open-threads / active
#      non-hidden-lore call sites in assemble() -- reverting just those call
#      sites to `e.render()` reproduces this exact leak (manually verified
#      during development: node_id/tension_id/"hidden: false" all appeared
#      in `non_secret_text`). Kept as a comment rather than a live git-diff
#      flip so this file stays a self-contained, always-green regression test.

# ---- 6) player-facing OUTPUT side (D-219/D-82 apply there too): the
#      narrator's rendered reply is free-form model prose, so this repo's
#      100%-offline test suite cannot call a real model to check what a
#      narrator "chooses" to say back -- but it CAN check the one
#      deterministic post-processing step every narrator reply goes through,
#      `coderain.sidecar.strip_sidecar`, on a simulated raw reply that
#      smuggles the same trap markers a leaking prompt could echo back.
from coderain import sidecar

raw_reply = (
    "The captain nods slowly.\n"
    "```rpg\n"
    '{"v":1,"deltas":{"flag_set":{"met_captain":true}}}\n'
    "```\n"
    "node_id: CHARNODE-V9L1 -- SECRET-FIXTURE-H8R3 hidden: true"
)
visible, block = sidecar.strip_sidecar(raw_reply)
assert "```rpg" not in visible and block, \
    "strip_sidecar must remove the mechanical sidecar block from player-visible prose"
# strip_sidecar's job is the sidecar block only, not scrubbing free prose --
# a narrator that CHOOSES to echo a marker is a prompt-fidelity failure the
# assemble()-side filter above prevents at the source. This asserts the
# postprocessing step does its documented job and nothing less.
print("6) strip_sidecar removes the mechanical block from the player-visible reply")

print("ALL OK -- test-garde-fuite-contexte-i376.py")
