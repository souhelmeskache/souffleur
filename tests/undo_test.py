"""Feature 2: undo / remove-last.

undo_last() drops the last exchange and rolls back that turn's RPG mechanics WITHOUT
calling the model (a stub asserts zero completions), and reports False when there's
nothing to undo.
"""
import os, sys, shutil, tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Library

cfg = load_config()
# tests stub a single-brain engine; the user's live config toggle must not reroute
cfg.generation["trinity_brain"] = False
root = os.path.join(tempfile.gettempdir(), "se_undo")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("Undo", "A tinker in a clockwork city."))
engine = Engine(cfg, store)

class NoCallLLM:
    """Any generation call is a test failure — undo must not hit the model."""
    def __init__(self): self.calls = 0
    def stream(self, *a, **k):
        self.calls += 1
        raise AssertionError("undo must not call the model (stream)")
        yield  # pragma: no cover
    def complete(self, *a, **k):
        self.calls += 1
        raise AssertionError("undo must not call the model (complete)")
engine.llm = NoCallLLM()

# ---- 1) nothing to undo on an empty transcript ----
result = engine.undo_last()
assert result["undone"] is False
print("1) empty transcript: undo_last() -> {undone: False}")

# ---- 2) a full exchange is removed, no model call ----
store.append_turn("player", "wind the great spring")
store.append_turn("narrator", "The spring groans and the city stutters awake.")
assert len(store.turns()) == 2
result = engine.undo_last()
assert result["undone"] is True
assert result["mechanics_restored"] is True
assert store.turns() == [], store.turns()
assert engine.llm.calls == 0, "undo touched the model"
print("2) full exchange removed without a model call")

# ---- 3) an orphan player turn (empty generation) is dropped ----
store.append_turn("player", "listen at the door")
result = engine.undo_last()
assert result["undone"] is True
assert store.turns() == []
print("3) orphan player turn dropped")

# ---- 4) RPG mechanics roll back to the pre-turn snapshot ----
store2 = lib.store(lib.create_story("UndoRPG", "A duelist counting coins."))
st = store2.rpg_state(); st["enabled"] = True; st["player"]["hp"] = 20
store2.set_rpg_state(st)
eng2 = Engine(cfg, store2)

class SidecarLLM:
    def stream(self, messages, **k):
        for ch in ['You take a blow.\n\n```rpg\n{"deltas":{"hp_delta":-5}}\n```']:
            yield ch
    def complete(self, *a, **k): return ""
eng2.llm = SidecarLLM()

list(eng2.turn("parry the thrust"))
eng2.maybe_fold()
assert store2.rpg_state()["player"]["hp"] == 15, store2.rpg_state()["player"]
result = eng2.undo_last()
assert result["undone"] is True
assert result["mechanics_restored"] is True
assert store2.rpg_state()["player"]["hp"] == 20, "RPG not rolled back on undo"
assert store2.turns() == []
print("4) RPG deltas rolled back on undo")

print("\nUNDO TESTS PASSED")
