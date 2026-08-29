import os, sys, shutil, tempfile, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.memory import Library, MemoryStore, Entry, parse_entries
from coderain.summarizer import Summarizer

root = os.path.join(tempfile.gettempdir(), "se_p2")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
slug = lib.create_story("Phase2", "You are a hedge-witch who owes a patron.")
store = lib.store(slug)

# ---- fake LLMs ----
SCENE_JSON = json.dumps({
    "scene_summary": "You met [[character:kaelen]] at [[location:ashford]].",
    "promotions": [{"kind": "character", "slug": "kaelen", "title": "Kaelen",
                    "aliases": ["the knight"], "importance": 4, "status": "wary",
                    "detail": "A grim knight who owes you a debt."}],
    "new_threads": [{"slug": "the-debt", "title": "The Debt", "importance": 4,
                     "detail": "You owe the patron a soul."}],
    "resolved_threads": [],
})
ARC_JSON = json.dumps({"arc": "So far: you met [[character:kaelen]] in a grim town."})

class FakeLLM:
    def complete(self, messages):
        sys_txt = messages[0]["content"]
        return SCENE_JSON if "scene_summary" in sys_txt else ARC_JSON

class BadLLM:
    def complete(self, messages):
        return "sorry, here is a paragraph and no JSON at all."

class Cfg:
    memory = {"medium_fold_after": 4, "medium_fold_size": 2,
              "long_fold_after": 2, "long_fold_size": 2}
    generation = {}

# ---- 1) folds: 10 turns -> scenes + promotions + arc ----
for i in range(5):
    store.append_turn("player", f"action {i}")
    store.append_turn("narrator", f"narration {i}")
sm = Summarizer(Cfg(), store, FakeLLM())
events = sm.maybe_fold()
scenes = store.entries("memory/scenes.md")
assert len(scenes) == 3, f"expected 3 scenes, got {len(scenes)}"
chars = store.entries("characters.md")
assert [c.slug for c in chars] == ["kaelen"], f"dedupe failed: {[c.slug for c in chars]}"
assert chars[0].attrs.get("status") == "wary"
threads = store.entries("threads.md")
assert any(t.slug == "the-debt" for t in threads), threads
assert "you met" in store.read("memory/arc.md").lower()
assert store.state()["folded_turns"] == 6 and store.state()["folded_scenes"] == 2
assert (store.dir / ".snapshots").exists(), "no snapshot made"
print("1) folds OK:", [e for e in events][:4], "... scenes:", len(scenes))

# ---- 2) upsert did NOT corrupt the commented skeleton example ----
assert "<!-- Example" in store.read("characters.md"), "skeleton comment clobbered"
# re-promote kaelen -> still single entry (dedupe via upsert)
sm._apply_promotions({"promotions": [{"kind": "character", "slug": "kaelen",
    "title": "Kaelen", "importance": 5, "detail": "Updated detail."}]})
chars = store.entries("characters.md")
assert len(chars) == 1 and chars[0].importance == 5, chars
print("2) comment-safe upsert + dedupe OK")

# ---- 3) graceful degradation on bad JSON ----
store2 = lib.store(lib.create_story("Bad", "premise"))
for i in range(5):
    store2.append_turn("player", f"a{i}"); store2.append_turn("narrator", f"n{i}")
sm_bad = Summarizer(Cfg(), store2, BadLLM())
ev = sm_bad.maybe_fold()
sc = store2.entries("memory/scenes.md")
assert len(sc) == 3 and "unavailable" in sc[0].body, sc
assert store2.state()["folded_turns"] == 6  # advanced despite bad output
print("3) degradation OK (stub summaries, counter advanced)")

# ---- 3b) I-204: arc fold advances folded_scenes ONLY with a readable trace ----
# 3 scenes + long_fold_after=2/size=2 above already ran an arc fold on store2's
# BadLLM (no real JSON) -> the counter must not have advanced for free.
assert store2.state()["folded_scenes"] == 2  # advanced (never loops forever)
assert "arc fold unavailable" in store2.read("memory/arc.md")
print("3b) arc fold degradation OK (readable trace, counter advanced)")

# ---- 4) index: resolve / find / dangling / duplicates ----
idx = store.index()
assert idx.resolve("kaelen").title == "Kaelen"
assert idx.find("knight")[0][1].slug == "kaelen", idx.find("knight")
# scene referenced [[location:ashford]] but ashford was never promoted -> dangling
assert "ashford" in idx.dangling_refs(), idx.dangling_refs()
# duplicate detection
store.write("locations.md", "# Locations\n\n## A {#dup}\nimportance: 2\n\nx\n\n"
                            "## B {#dup}\nimportance: 2\n\ny\n")
assert "dup" in store.index().duplicate_slugs
print("4) index OK (resolve/find/dangling/duplicates)")

# ---- 5) assemble: reference resolution + budget ----
msgs = store.assemble(history=[{"role": "player", "text": "I look around"}],
                      player_input="north")
sys_txt = msgs[0]["content"]
# kaelen not alias-mentioned, but referenced in scenes/arc -> resolved by name
assert "Referenced (by name)" in sys_txt and "Kaelen" in sys_txt, sys_txt
# tiny budget -> only priority-0 (Premise / You) survive; World dropped
store.write("world-bible.md", "# World bible\n\n" + ("W " * 500))
tight = store.assemble(history=[], player_input="x", budget_tokens=5)
assert "## World" not in tight[0]["content"], "budget did not drop low-priority"
assert "## Premise" in tight[0]["content"]
print("5) assemble OK (reference resolution + salience budget)")

# ---- 6) engine tool loop (agentic lookup) ----
from coderain.config import load_config
from coderain.engine import Engine
cfg = load_config()
# tests stub a single-brain engine; the user's live config toggle must not reroute
cfg.generation["trinity_brain"] = False
eng = Engine(cfg, store)
eng.use_tool = True
class ToolLLM:
    def complete_with_tools(self, messages, tools, dispatch, max_rounds=4):
        assert tools[0]["function"]["name"] == "lookup_memory"
        res = dispatch("lookup_memory", {"query": "kaelen"})
        return f"FINAL[knew_kaelen={'Kaelen' in res}]"
eng.llm = ToolLLM()
out = "".join(eng.turn("I ask about the knight"))
assert out == "FINAL[knew_kaelen=True]", out
assert store.turns()[-1]["text"] == out  # stored as narrator turn
print("6) tool loop OK:", out)

print("\nPHASE 2 TESTS PASSED")
