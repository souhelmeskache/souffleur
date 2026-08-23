"""Quad pipeline (Wave 1): Memory Manager (code-first) -> Logic Agent ->
Backend Validator (code) -> Narrator.

A stubbed multi-stage LLM drives the pipeline. Asserts: stages run in order (with
the opt-in Lore-keeper LLM pass ON); the Director PROPOSES an envelope and the
engine rolls the dice BEFORE the Writer runs (prose narrates real outcomes); world
deltas (time_advance) apply; the Lore-keeper's recall_turns tool is reachable; the
lore pass defaults OFF (code-first Memory Manager); the legacy "rpg" plan key still
works; and the single-brain path is untouched when trinity_brain is off.
"""
import os, sys, shutil, tempfile, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Library

root = os.path.join(tempfile.gettempdir(), "se_trinity")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)

# ---- 0) single-brain unchanged when the flag is off ----
cfg_off = load_config()
cfg_off.generation["trinity_brain"] = False
store0 = lib.store(lib.create_story("Off", "A scribe at a quiet desk."))
assert Engine(cfg_off, store0).trinity is None, "trinity built while disabled"
print("0) trinity disabled by default -> single-brain path")

# ---- Quad ON (lore pass explicitly enabled for the full-order case) ----
cfg = load_config()
cfg.generation["trinity_brain"] = True
cfg.raw["trinity"] = {"lorekeeper": {"llm_pass": True}}   # no pins; opt-in lore pass
store = lib.store(lib.create_story("Duel", "A duel in the plaza at dawn."))
st = store.rpg_state()
st["enabled"] = True
st["seed"] = 5
st["player"]["stats"]["strength"] = 3
store.set_rpg_state(st)
engine = Engine(cfg, store)
assert engine.trinity is not None
assert engine.trinity.lore_llm_pass is True

class QuadStub:
    def __init__(self):
        self.stages = []
        self.recall_called = False
        self.store = None

    def complete(self, messages, **k):                     # Director (emit_json)
        assert "LOGIC AGENT" in messages[0]["content"], messages[0]["content"][:80]
        self.stages.append("director")
        return json.dumps({
            "beat_plan": "You parry the thrust and riposte.",
            "must_stay_consistent": ["the duel is in the plaza"],
            "recall_queries": ["the earlier insult"],
            "envelope": {"v": 1,
                         "check": {"stat": "strength", "dc": 8},
                         "deltas": {"time_advance": {"phase": "dawn",
                                                     "weather": "cold mist"}}},
        })

    def complete_with_tools(self, messages, tools, dispatch, max_rounds=4):  # Lore-keeper
        assert "LORE-KEEPER" in messages[0]["content"]
        assert any(t["function"]["name"] == "recall_turns" for t in tools)
        self.stages.append("lore")
        dispatch("recall_turns", {"reference": "T1-2"})    # detail request
        self.recall_called = True
        return json.dumps({"vetted_facts": ["your rival broke an oath"], "patches": []})

    def stream(self, messages, **k):                       # Writer
        assert any("DIRECTOR'S PLAN" in m["content"] for m in messages), \
            "writer missing post-history plan"
        assert any("your rival broke an oath" in m["content"] for m in messages), \
            "writer missing vetted facts"
        # Mechanics resolve BEFORE prose in quad mode: the writer directive carries
        # the outcome and the roll is already on the sheet.
        assert any("RESOLVED MECHANICS" in m["content"] for m in messages), \
            "writer missing resolved-mechanics block"
        assert self.store.rpg_state().get("last_check"), \
            "check not resolved before the writer ran"
        self.stages.append("writer")
        for ch in ["You parry, ", "then riposte clean."]:
            yield ch

stub = QuadStub()
stub.store = store
engine.llm = stub
# The brain holds its own per-stage clients (each may point at a different model/API);
# with no per-stage override they all default to the base client — swap them for the stub.
engine.trinity.director_llm = stub
engine.trinity.lorekeeper_llm = stub
engine.trinity.writer_llm = stub

visible = "".join(engine.turn("parry and riposte"))
events = engine.maybe_fold()

# ---- 1) stages in order (validator is code — it leaves no LLM stage) ----
assert stub.stages == ["director", "lore", "writer"], stub.stages
print("1) stages ran in order:", stub.stages)

# ---- 2) writer prose streamed + stored (no sidecar leak) ----
assert visible == "You parry, then riposte clean.", repr(visible)
assert store.turns()[-1]["text"] == visible
assert "```rpg" not in visible
print("2) writer prose streamed and stored")

# ---- 3) dice engine-rolled from the Director's proposed envelope ----
lc = store.rpg_state()["last_check"]
assert lc is not None and lc["stat"] == "strength", lc
assert lc["mod"] == 3, lc                        # player strength, rolled by engine
assert 1 <= lc["roll"] <= 20
assert any(e.startswith("check:") for e in events), events
print("3) Director proposed; engine rolled the dice:", lc["roll"], "+", lc["mod"])

# ---- 4) world deltas applied + logged ----
t = store.world_state()["time"]
assert t.get("phase") == "dawn" and t.get("weather") == "cold mist", t
assert any(e.startswith("time →") for e in events), events
log = (store.dir / "memory" / "events.jsonl")
assert log.exists() and json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["env"]["check"]
print("4) time_advance applied; envelope in events.jsonl")

# ---- 5) lore-keeper reached the recall_turns tool ----
assert stub.recall_called, "recall_turns was never dispatched"
print("5) lore-keeper invoked recall_turns")

# ---- 6) lore pass defaults OFF (code-first Memory Manager) ----
cfg6 = load_config()
cfg6.generation["trinity_brain"] = True
cfg6.raw["trinity"] = {}
store6 = lib.store(lib.create_story("Fast", "A quiet errand."))
# rpg mode so the Logic Agent engages (a legacy rpg-off save counts as Simple
# mode since Wave 3 and would skip the director entirely — tested in wave3).
st6 = store6.rpg_state(); st6["enabled"] = True
store6.set_rpg_state(st6)
eng6 = Engine(cfg6, store6)
assert eng6.trinity.lore_llm_pass is False

class NoLoreStub(QuadStub):
    def complete_with_tools(self, *a, **k):
        raise AssertionError("lore-keeper LLM pass ran while off")

    def stream(self, messages, **k):
        self.stages.append("writer")
        yield "A quiet turn."

stub6 = NoLoreStub()
stub6.store = store6
eng6.llm = stub6
eng6.trinity.director_llm = stub6
eng6.trinity.lorekeeper_llm = stub6
eng6.trinity.writer_llm = stub6
out6 = "".join(eng6.turn("walk on"))
assert stub6.stages == ["director", "writer"], stub6.stages
assert out6 == "A quiet turn."
print("6) lore pass off by default -> director+writer only (2 LLM calls)")

# ---- 7) legacy 'rpg' plan key still validates + applies ----
store7 = lib.store(lib.create_story("Legacy", "An old contract."))
st7 = store7.rpg_state(); st7["enabled"] = True; st7["seed"] = 9
store7.set_rpg_state(st7)
eng7 = Engine(cfg6, store7)

class LegacyStub(NoLoreStub):
    def complete(self, messages, **k):
        self.stages.append("director")
        return json.dumps({"beat_plan": "b",
                           "rpg": {"check": {"stat": "agility", "dc": 6}}})

stub7 = LegacyStub()
stub7.store = store7
eng7.llm = stub7
eng7.trinity.director_llm = stub7
eng7.trinity.writer_llm = stub7
"".join(eng7.turn("slip past"))
assert store7.rpg_state()["last_check"]["stat"] == "agility"
print("7) legacy 'rpg' plan key accepted as the envelope")

# ---- 8) per-stage model/API overrides build distinct clients ----
# I-270: the 'openrouter' profile used to exist only in machine-local
# config.yaml (gitignored), so fresh clones hit SystemExit here. The test now
# declares the profile itself (hermetic, offline) instead of depending on the
# machine; a real local profile, if present, is left untouched (setdefault).
cfg2 = load_config()
cfg2.generation["trinity_brain"] = True
cfg2.raw["profiles"].setdefault("openrouter", {
    "base_url": "https://openrouter.example/v1",
    "model": "openrouter/some-model",
})
cfg2.raw["trinity"] = {
    "writer": {"profile": "openrouter", "model": "some/writer-model"},
    "director": {"model": "director-only-model"},   # model-only -> keep active profile
    # lorekeeper omitted -> inherits the base client
}
eng3 = Engine(cfg2, lib.store(lib.create_story("Split", "a split-brain test")))
tb = eng3.trinity
assert tb.writer_llm is not tb.director_llm
assert tb.writer_llm.profile.base_url == cfg2.raw["profiles"]["openrouter"]["base_url"]
assert tb.writer_llm.profile.model == "some/writer-model"
assert tb.director_llm.profile.model == "director-only-model"
assert tb.director_llm.profile.base_url == cfg2.profile.base_url      # inherited active
assert tb.lorekeeper_llm is eng3.llm                                  # unset -> base
print("8) per-stage overrides build distinct clients; unset inherits base")

print("\nQUAD (TRINITY) TESTS PASSED")
