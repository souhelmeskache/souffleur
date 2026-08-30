"""I-94 -- element test for the D-141 single-writer hardening.

I-375's chemins-morts test (tests/test-chemins-morts-i375.py) documented, as a
constat, that `MemoryStore.set_world_state` (coderain/memory.py) let an
out-of-band write reach state.json with an illegal value (negative gold) that
`validate()`'s legality check (coderain/validator.py, "not enough gold") would
have refused had it gone through Engine.apply_envelope. This test closes that
gap: `set_world_state` now routes every write through
`validator.guard_world_state`, so the illegal value can no longer land no
matter which code path reaches state.json.

Covers, on a throwaway synthetic save (D-109 -- no real campaign material):
  1) a direct, out-of-band write to state.json with an illegal value (negative
     gold) is refused: the guard strips it before it lands;
  2) a write through the guichet (Engine.apply_envelope) still lands exactly.
"""
import os, sys, shutil, tempfile

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Library

root = os.path.join(tempfile.gettempdir(), "se_single_writer_i94")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
slug = lib.saves.create("Guichet unique", mode="rpg",
                        premise="Synthetic proving ground, D-109.")
store = lib.store(slug)
assert store.mode() == "rpg" and store.rpg_enabled()

cfg = load_config()
cfg.generation["trinity_brain"] = False


class Prose:
    def stream(self, messages, **k):
        yield "Nothing narratively real happens here."


eng = Engine(cfg, store)
eng.llm = Prose()

# ---- 1) a direct write that skips apply_envelope entirely, with an illegal
#         value validate() would have refused (gold < 0) ----
state = store.world_state()
state.setdefault("player", {})["gold"] = 20
store.set_world_state(state)                      # legal direct write: unaffected
assert store.world_state()["player"]["gold"] == 20

illegal_state = store.world_state()
illegal_state["player"]["gold"] = -999            # apply_world/validate would refuse this
store.set_world_state(illegal_state)              # bypasses Engine.apply_envelope entirely
after = store.world_state()["player"]["gold"]
assert after == 0, (
    "single-writer guard regression: an out-of-band write to state.json via "
    f"MemoryStore.set_world_state landed gold={after} instead of being "
    "clamped -- see coderain/validator.py:guard_world_state and "
    "coderain/memory.py:set_world_state")
print("1) direct off-guichet write with illegal gold: refused (clamped to 0)")

# ---- 2) a write through the guichet still lands, exact ----
ev = eng.apply_envelope({"v": 1, "deltas": {"gold_delta": 25}}, rpg_on=True)
assert any("gold: +25" in e for e in ev), ev
assert store.world_state()["player"]["gold"] == 25
print("2) write through apply_envelope: lands, re-read exact")

print("\nSINGLE WRITER GUARD HOLDS -- direct write refused, guichet write exact")
