"""D-216 §3: persistent inter-combat state (the `persist` delta).

Covers: the author-side declaration (`persistent:` attr on an entry), persist
accepted when declared / refused when not, scalar + magnitude + type-stability
checks, survival across combat/scene boundaries (the value lives outside every
ephemeral pool), service to context with current value + mutation history,
history cap, undo reversibility, branch-replay determinism, and the closed
vocabulary guard for everything else. 100% synthetic fixtures (D-109).
"""
import os, sys, shutil, tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain import validator as V
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Library

root = os.path.join(tempfile.gettempdir(), "se_etat_persistant")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("Persist Range", "A synthetic proving ground."))

CHARS = """# Characters

## Alpha Warden  {#alpha-warden}
importance: 5
weight: critical
status: holding the crossing
persistent: hp, morale
hp: 120

Synthetic body: structural fixture only.

## Beta Shade  {#beta-shade}
importance: 4
hp: 50

Synthetic body: structural fixture only.
"""
store.write("characters.md", CHARS)

# ---- 1) declaration grammar: `persistent:` lists the mutable attributes ----
entries = {e.slug: e for e in store.entries("characters.md")}
assert entries["alpha-warden"].persistent_attrs() == ["hp", "morale"]
assert entries["beta-shade"].persistent_attrs() == []
print("1) declaration grammar: persistent: parsed; undeclared stays empty")

# ---- 2) accepted when declared: value + history land in state.json ----
clean, rejected = V.validate(
    {"v": 1, "deltas": {"persist": {"Alpha Warden": {"hp": 95}}}}, store)
assert not rejected, rejected
ev = V.apply_world(store, clean)
st = store.world_state()
rec = st["persistent"]["alpha-warden"]["hp"]
assert rec["value"] == 95
h0 = rec["history"][0]
assert h0["value"] == 95 and h0["who"] == "director" and h0["when"]
assert any(e.startswith("persist: alpha-warden.hp = 95") for e in ev)
print(f"2) persist applied: value 95, history stamped (who/{h0['who']}, "
      f"when '{h0['when']}')")

# ---- 3) refused when NOT declared: the closed vocabulary still guards ----
c3, r3 = V.validate({"v": 1, "deltas": {"persist": {
    "beta-shade": {"hp": 10},          # entry has NO persistent: line
    "alpha-warden": {"status": "x"},   # attr exists but is not declared
    "ghost-knight": {"hp": 10},        # no such entry at all
}}}, store)
assert not c3.get("deltas")
assert any(r["delta"].startswith("persist:beta-shade") and "declared" in r["reason"]
           for r in r3)
assert any(r["delta"] == "persist:alpha-warden.status" for r in r3)
assert any("no such entry" in r["reason"] for r in r3)
print("3) refusals: undeclared attr / undeclared entry attr / unknown slug")

# ---- 4) scalars only; kind stability vs baseline; magnitude clamp ----
c4a, r4a = V.validate({"v": 1, "deltas": {
    "persist": {"alpha-warden": {"morale": "steady"}}}}, store)
assert not r4a                      # morale has no value anywhere yet -> free
V.apply_world(store, c4a)
_, r4b = V.validate({"v": 1, "deltas": {
    "persist": {"alpha-warden": {"morale": 3}}}}, store)
assert any("type change" in r["reason"] for r in r4b)      # text -> number
_, r4c = V.validate({"v": 1, "deltas": {
    "persist": {"alpha-warden": {"hp": "wounded"}}}}, store)
assert any("type change" in r["reason"] for r in r4c)      # number -> text
c4d, _ = V.validate({"v": 1, "deltas": {
    "persist": {"alpha-warden": {"hp": 99999}}}}, store)
assert c4d["deltas"]["persist"]["alpha-warden"]["hp"] == V.NUM_CAP
_, r4e = V.validate({"v": 1, "deltas": {
    "persist": {"alpha-warden": {"morale": ["list"]}}}}, store)
assert any("scalar" in r["reason"] for r in r4e)
_, r4f = V.validate({"v": 1, "deltas": {
    "persist": {"alpha-warden": "nope"}}}, store)
assert any("must be {slug" in r["reason"] for r in r4f)
print("4) scalars only; type stability vs baseline/current; NUM_CAP clamp")

# ---- 5) survival across combat boundaries ----
from coderain.modules.rpg import apply as rpg_apply
rpg = store.rpg_state(); rpg["enabled"] = True; store.set_rpg_state(rpg)
env_c = {"v": 1,
         "check": {"stat": "strength", "dc": 12},
         "deltas": {"enemies": {"bridge-brute": {"hp_max": 30, "hp_delta": -12}},
                    "time_advance": {"days": 1, "phase": "night"},
                    "persist": {"alpha-warden": {"hp": 80}}}}
cl, rj = V.validate(env_c, store)
assert not rj and cl["check"]["stat"] == "strength"
V.apply_world(store, cl); rpg_apply(store, cl, {})
rpg_end = store.rpg_state()
assert rpg_end["enemies"].get("bridge-brute", {}).get("hp") == 18
rpg_end["enemies"] = {}                       # combat ends: ephemerals purged
store.set_rpg_state(rpg_end)
st = store.world_state()
assert st["persistent"]["alpha-warden"]["hp"]["value"] == 80
assert st["time"]["day"] == 2 and st["time"]["phase"] == "night"   # clock moved
print("5) combat fought, enemies purged: persistent hp 80 survived, clock intact")

# ---- 6) served to context: baseline before first write, live value + history after
store_b = lib.store(lib.create_story("Baseline Serve", "A second fixture."))
store_b.write("characters.md", CHARS)
ctx_b = "\n".join(m["content"] for m in store_b.assemble([], "Alpha Warden"))
assert "- hp: 120" in ctx_b and "Persistent state" in ctx_b
assert "set to" not in ctx_b                  # never mutated: no history yet
ctx = "\n".join(m["content"] for m in store.assemble([], "Alpha Warden, Beta Shade"))
assert ctx.count("Persistent state") == 1     # only the DECLARING entry carries it
seg_beta = "## Beta Shade" + ctx.split("## Beta Shade", 1)[1]
seg_beta = seg_beta.split("\n## ", 1)[0]      # beta's own rendered slice
assert "Persistent state" not in seg_beta
assert "- hp: 80" in ctx and "set to 95" in ctx and "set to 80" in ctx
print("6) context serves baseline (120) then live value + history (95 -> 80)")

# ---- 7) history cap ----
for i in range(V.PERSIST_HISTORY_CAP + 5):
    cl, rj = V.validate({"v": 1, "deltas": {
        "persist": {"alpha-warden": {"morale": f"s{i}"}}}}, store)
    assert not rj
    V.apply_world(store, cl)
hist = store.world_state()["persistent"]["alpha-warden"]["morale"]["history"]
assert len(hist) == V.PERSIST_HISTORY_CAP
assert hist[-1]["value"] == f"s{V.PERSIST_HISTORY_CAP + 4}"
print(f"7) history capped at {V.PERSIST_HISTORY_CAP} mutations")

# ---- 8) undo rolls persistent back with the rest of the world ----
cfg = load_config()
cfg.generation["trinity_brain"] = False

class Prose:
    def stream(self, messages, **k):
        yield "Synthetic narration."

eng = Engine(cfg, store)
eng.llm = Prose()
"".join(eng.turn("the Alpha Warden holds the crossing"))
before = store.world_state()["persistent"]["alpha-warden"]["hp"]["value"]
eng.apply_envelope({"v": 1, "deltas": {"persist": {"alpha-warden": {"hp": 10}}}},
                   rpg_on=True)
assert store.world_state()["persistent"]["alpha-warden"]["hp"]["value"] == 10
assert eng.undo_last()
now = store.world_state()["persistent"]["alpha-warden"]["hp"]["value"]
assert now == before
print(f"8) undo restores persistent state ({before} back after a persist to 10)")

# ---- 9) branch replay rebuilds persistent deterministically ----
store_r = lib.store(lib.create_story("Replay Base", "A third fixture."))
store_r.write("characters.md", CHARS)
recs = [{"turn": 1, "env": {}},
        {"turn": 2, "env": {"v": 1, "deltas": {
            "persist": {"alpha-warden": {"hp": 66}}}}},
        {"turn": 3, "env": {"v": 1, "deltas": {
            "flag_set": {"gate_open": True}}}}]
n = V.replay_records(store_r, {}, recs)
assert n == 3
st = store_r.world_state()
assert st["persistent"]["alpha-warden"]["hp"]["value"] == 66
assert len(st["persistent"]["alpha-warden"]["hp"]["history"]) == 1
assert st["flags"]["gate_open"] is True
print("9) replay_records rebuilds persistent values + flags from the log")

# ---- 10) regression: everything else stays closed ----
c10, r10 = V.validate({"v": 1, "deltas": {
    "persist_typo": {"alpha-warden": {"hp": 1}}}}, store)
assert not c10.get("deltas") and r10 and "unknown delta" in r10[0]["reason"]
print("10) unknown delta names are still rejected (guard intact)")

print("\nPERSISTENT STATE TESTS PASSED")
