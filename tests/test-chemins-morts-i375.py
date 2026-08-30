"""I-375 -- element test for the fact engine's four never-exercised paths
(registre méta MRPG-I-375): inventory, HP, gold, XP all go through
`Engine.apply_envelope` (coderain/engine.py:582) -- validate, apply, log --
but none of the four had ever been exercised in real play. A path never
walked is a path broken until proven otherwise.

Covers, on a throwaway synthetic save (D-109, D-206 -- no real campaign
material):
  1) each of the four paths through the ONE official write point, state
     re-read after the fact and checked exact;
  2) the D-141 single-writer check: an out-of-band write to state.json that
     skips `apply_envelope` entirely -- does it get refused, or does it land
     in silence? Originally a constat only (it landed); I-94 closed the gap
     by routing `set_world_state` through `validator.guard_world_state`, so
     this now asserts the refusal holds (element coverage in
     tests/single-writer-guichet-i94_test.py).
  3) per-path latency of one typical-turn envelope, printed as the closing
     comment's measured numbers (I-190 -- never measured before this test).
"""
import os, sys, shutil, tempfile, time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Library

root = os.path.join(tempfile.gettempdir(), "se_chemins_morts_i375")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
slug = lib.saves.create("Chemins morts", mode="rpg",
                        premise="Synthetic proving ground, D-109/D-206.")
store = lib.store(slug)
assert store.mode() == "rpg" and store.rpg_enabled()

cfg = load_config()
cfg.generation["trinity_brain"] = False


class Prose:
    def stream(self, messages, **k):
        yield "Nothing narratively real happens here."


eng = Engine(cfg, store)
eng.llm = Prose()

latencies: dict[str, float] = {}


def timed(label: str, env: dict) -> list[str]:
    t0 = time.perf_counter()
    events = eng.apply_envelope(env, rpg_on=True)
    latencies[label] = (time.perf_counter() - t0) * 1000
    return events


# ---- 1a) inventory: acquire then lose an item through the official point ----
ev = timed("inventory_add", {"v": 1, "deltas": {
    "inventory_add": [{"slug": "rusty-key", "qty": 1}]}})
assert any("item: +rusty-key" in e for e in ev), ev
inv = store.rpg_state()["inventory"]
assert inv["rusty-key"]["qty"] == 1, inv
assert any(e.slug == "rusty-key" for e in store.entries("items.md"))

ev = timed("inventory_remove", {"v": 1, "deltas": {
    "inventory_remove": [{"slug": "rusty-key", "qty": 1}]}})
assert any("item: -rusty-key" in e for e in ev), ev
assert "rusty-key" not in store.rpg_state().get("inventory", {})
assert not any(e.slug == "rusty-key" for e in store.entries("items.md"))
print("1a) inventory: acquire/lose through apply_envelope, state re-read exact")

# ---- 1b) HP: take damage, then heal -- through the official point ----
hp0 = store.rpg_state()["player"]["hp"]
ev = timed("hp_damage", {"v": 1, "deltas": {"hp_delta": -7}})
assert any("hp: -7" in e for e in ev), ev
assert store.rpg_state()["player"]["hp"] == hp0 - 7

ev = timed("hp_heal", {"v": 1, "deltas": {"hp_delta": 4}})
assert any("hp: +4" in e for e in ev), ev
assert store.rpg_state()["player"]["hp"] == hp0 - 7 + 4
print("1b) hp: damage/heal through apply_envelope, state re-read exact")

# ---- 1c) gold: receive, then pay -- through the official point ----
ev = timed("gold_receive", {"v": 1, "deltas": {"gold_delta": 25}})
assert any("gold: +25 -> 25" in e or "gold: +25 → 25" in e for e in ev), ev
assert store.world_state()["player"]["gold"] == 25

ev = timed("gold_pay", {"v": 1, "deltas": {"gold_delta": -10}})
assert any("gold: -10" in e for e in ev), ev
assert store.world_state()["player"]["gold"] == 15
print("1c) gold: receive/pay through apply_envelope, state re-read exact")

# ---- 1d) XP: gain -- through the official point ----
xp0 = store.rpg_state()["player"]["xp"]
lvl0 = store.rpg_state()["player"]["level"]
ev = timed("xp_gain", {"v": 1, "deltas": {"xp_delta": 30}})
assert any("xp: +30" in e for e in ev), ev
rpg = store.rpg_state()
assert rpg["player"]["xp"] == xp0 + 30
assert rpg["player"]["level"] == lvl0        # 30 < 100 (xp_per_level default): no level-up yet
print("1d) xp: gain through apply_envelope, state re-read exact")

# ---- 2) D-141 single-writer check: an out-of-band write to state.json ----
# I-94 closed the gap this used to document: `MemoryStore.set_world_state`
# (coderain/memory.py) now routes every write through
# `validator.guard_world_state`, so a direct write bypassing
# Engine.apply_envelope entirely -- exactly what a hand-authored tool or a
# future code path could do -- can no longer land a value validate()'s own
# legality check would have refused (e.g. the "not enough gold" refusal at
# coderain/validator.py). Full element coverage of the gate lives in
# tests/single-writer-guichet-i94_test.py; this keeps the historical probe
# green rather than dropping it.
before = store.world_state()["player"]["gold"]
illegal_state = store.world_state()
illegal_state["player"]["gold"] = -999          # validator.validate would refuse this
store.set_world_state(illegal_state)             # bypasses apply_envelope entirely
after = store.world_state()["player"]["gold"]
single_writer_ok = (after != -999)                # True once the bypass no longer lands as-is
if single_writer_ok:
    print("2) single writer: OUI -- out-of-band write to state.json was "
          f"refused (gold clamped to {after}, not the illegal -999) -- I-94")
else:
    print("2) single writer: NON -- out-of-band write via "
          "MemoryStore.set_world_state landed silently "
          f"(gold now {after}) -- regression on I-94's guard")
# restore the pre-probe value either way so the rest of the suite isn't left
# mid-constat
illegal_state["player"]["gold"] = before
store.set_world_state(illegal_state)
assert single_writer_ok
assert store.world_state()["player"]["gold"] == before

# ---- 3) latency, one number per path (I-190) ----
print("3) apply_envelope latency per path (ms, single-run local measurement):")
for label in ("inventory_add", "inventory_remove", "hp_damage", "hp_heal",
             "gold_receive", "gold_pay", "xp_gain"):
    print(f"   {label:16s} {latencies[label]:7.3f} ms")

print("\nALL 4 PATHS EXERCISED -- inventory OK, hp OK, gold OK, xp OK; "
     "single writer: " + ("OUI" if single_writer_ok else "NON") + " (see #2 above)")
