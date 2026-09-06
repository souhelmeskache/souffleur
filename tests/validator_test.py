"""Wave 1: Backend Validator + world state + chronology.

Covers: envelope schema (unknown keys, wave-3 keys, bad types, versioning), trust
per-turn cap, time_advance day cap + scene_break + monotonic clock, flag type
stability, apply_world (clock/flags/location), lazy world-state migration for old
saves, the events log, full-state undo (world deltas roll back), the validator
re-ask flow, and the summarizer's monotonic fallback guard.
"""
import os, sys, shutil, tempfile, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain import validator as V
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Library

root = os.path.join(tempfile.gettempdir(), "se_validator")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("Vale", "A misty vale."))

# ---- 1) schema: unknown / wave-3 / bad types are rejected, valid parts kept ----
env = {"v": 1,
       "check": {"stat": "agility", "dc": 10},
       "deltas": {"hp_delta": -3,
                  "xp_delta": "lots",                 # bad type
                  "gold_delta": 5,                    # valid since wave 3
                  "quest_update": {"q": "active"},    # unknown thread
                  "mystery_key": 1,                   # unknown
                  "status_add": ["bleeding", ""]},
       "extra_top": True}                             # unknown envelope key
clean, rejected = V.validate(env, store)
reasons = {r["delta"]: r["reason"] for r in rejected}
assert clean["check"]["stat"] == "agility"
assert clean["deltas"]["hp_delta"] == -3
assert clean["deltas"]["status_add"] == ["bleeding"]
assert clean["deltas"]["gold_delta"] == 5             # W3: now a real delta
assert "xp_delta" in reasons and "integer" in reasons["xp_delta"]
assert "quest_update:q" in reasons and "no such thread" in reasons["quest_update:q"]
assert "mystery_key" in reasons and "unknown" in reasons["mystery_key"]
assert "extra_top" in reasons
print("1) schema pass: valid kept, unknown/bad-type rejected with reasons")

# ---- 2) versioning: missing v = v1; wrong v rejects everything ----
c2, r2 = V.validate({"deltas": {"hp_delta": -1}}, store)     # no "v" (legacy)
assert c2["deltas"]["hp_delta"] == -1 and not r2
c3, r3 = V.validate({"v": 2, "deltas": {"hp_delta": -1}}, store)
assert not c3 and r3 and "version" in r3[0]["reason"]
assert not V.validate("nope", store)[0]
print("2) missing v = v1; unsupported version rejected wholesale")

# ---- 3) trust cap: per-turn deltas clamp to ±TRUST_CAP ----
c4, _ = V.validate({"deltas": {"trust": {"Mara": 40, "kel": -2, "bad": "x"}}}, store)
assert c4["deltas"]["trust"]["mara"] == V.TRUST_CAP
assert c4["deltas"]["trust"]["kel"] == -2
assert "bad" not in c4["deltas"]["trust"]
print("3) trust clamped to per-turn cap; non-integer deltas rejected")

# ---- 4) time: day cap 1 (30 on scene_break); negative days rejected ----
c5, _ = V.validate({"deltas": {"time_advance": {"days": 7, "phase": "night"}}}, store)
assert c5["deltas"]["time_advance"]["days"] == V.DAY_CAP
c6, _ = V.validate({"scene_break": True,
                    "deltas": {"time_advance": {"days": 7}}}, store)
assert c6["deltas"]["time_advance"]["days"] == 7
c7, r7 = V.validate({"deltas": {"time_advance": {"days": -2}}}, store)
assert "time_advance" not in c7.get("deltas", {}) and r7
print("4) day cap enforced (scene_break lifts it); clock never runs back")

# ---- 5) flag type stability ----
state = store.world_state()
state["flags"]["dragon_alive"] = True
store.set_world_state(state)
c8, r8 = V.validate({"deltas": {"flag_set": {"dragon_alive": "maybe",
                                             "new_flag": 3}}}, store)
assert c8["deltas"]["flag_set"] == {"new_flag": 3}
assert any("type change" in r["reason"] for r in r8)
print("5) flags keep their type once set; new flags accepted")

# ---- 6) apply_world: clock/flags/location + events ----
# D-282 (Issue #311) : `store` porte ICI aucune partition — `location` est
# désormais REFUSÉ à validate() (texte libre hors partition, D-282 règle 1 ;
# voir tests/test-guichet-position-d282-i311.py pour la couverture complète
# node id/lieu enregistré/monde vide). `apply_world` lui-même reste testé
# directement sur un `clean` construit à la main : il n'a jamais validé quoi
# que ce soit (split déjà en place, `location_refusal_events` porte le refus).
env9 = {"v": 1, "deltas": {"time_advance": {"days": 1, "phase": "evening",
                                            "weather": "rain"},
                           "flag_set": {"bridge_out": True},
                           "location": "Blackwood Tavern"}}
c9, r9 = V.validate(env9, store)
assert any(r["delta"] == "location" for r in r9), r9
assert "location" not in c9.get("deltas", {}), c9
ev = V.apply_world(store, {"deltas": {
    "time_advance": {"days": 1, "phase": "evening", "weather": "rain"},
    "flag_set": {"bridge_out": True},
    "location": "blackwood-tavern"}})
st = store.world_state()
assert st["time"]["day"] == 2 and st["time"]["weather"] == "rain"
assert st["flags"]["bridge_out"] is True
assert st["player"]["location"] == "blackwood-tavern"          # slugified
assert any(e.startswith("time →") for e in ev)
assert any(e.startswith("location →") for e in ev)
assert "rain" in store.clock_str()
print("6) location refusée hors partition (D-282) ; apply_world lui-même "
     "toujours pur (clock+weather+flag+location committed; clock_str "
     "shows weather)")

# ---- 7) lazy migration: an old-shape state.json gains the W1 keys on read ----
old = lib.store(lib.create_story("Old", "An old save."))
old.write("state.json", json.dumps({"time": {"day": 3, "phase": "noon"}}))
w = old.world_state()
assert w["time"]["day"] == 3 and w["time"]["weather"] == ""
assert w["player"] == {"location": "", "gold": 0}
assert w["quests"] == {} and w["flags"] == {}
print("7) pre-W1 state.json migrates lazily (existing values untouched)")

# ---- 8) engine.apply_envelope: events log + loud drops; undo restores world ----
cfg = load_config()
cfg.generation["trinity_brain"] = False

class Prose:
    def stream(self, messages, **k):
        yield "The rain thickens."

eng = Engine(cfg, store)
eng.llm = Prose()
before_day = store.world_state()["time"]["day"]
"".join(eng.turn("walk into the storm"))                     # snapshots state
events = eng.apply_envelope({"v": 1,
                             "deltas": {"time_advance": {"days": 1},
                                        "mana_burn": 10}}, rpg_on=False)
assert any("dropped mana_burn" in e for e in events), events
assert store.world_state()["time"]["day"] == before_day + 1
log = store.dir / "memory" / "events.jsonl"
assert log.exists()
rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
assert rec["env"]["deltas"]["time_advance"]["days"] == 1
assert "mana_burn" not in rec["env"]["deltas"]               # only CLEAN is logged
assert eng.undo_last()
assert store.world_state()["time"]["day"] == before_day      # world rolled back
print("8) apply_envelope logs clean env + drops loudly; undo restores the world")

# ---- 9) quad re-ask: rejected deltas go back to the Director once ----
cfgq = load_config()
cfgq.generation["trinity_brain"] = True
cfgq.raw["trinity"] = {}
storeq = lib.store(lib.create_story("Fix", "A correction."))
stq = storeq.rpg_state(); stq["enabled"] = True   # rpg mode -> director engages
storeq.set_rpg_state(stq)
engq = Engine(cfgq, storeq)

class ReaskStub:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, **k):
        self.calls += 1
        if self.calls == 1:      # Director: proposes an invalid delta
            return json.dumps({"beat_plan": "b",
                               "envelope": {"v": 1,
                                            "deltas": {"time_advance": {"days": -5},
                                                       "flag_set": {"met_king": True}}}})
        # corrective re-ask: fixed envelope
        assert any("REJECTED deltas" in m["content"] for m in messages)
        return json.dumps({"v": 1, "deltas": {"flag_set": {"met_king": True}}})

    def stream(self, messages, **k):
        yield "You bow before the king."

stubq = ReaskStub()
engq.llm = stubq
engq.trinity.director_llm = stubq
engq.trinity.writer_llm = stubq
"".join(engq.turn("approach the throne"))
assert stubq.calls == 2, stubq.calls
assert storeq.world_state()["flags"].get("met_king") is True
print("9) validator re-ask: director corrected once, clean envelope applied")

# ---- 10) summarizer fallback never rewinds the clock ----
from coderain.summarizer import Summarizer
sumr = Summarizer(cfg, store, eng.llm)
day_now = store.world_state()["time"]["day"]
assert sumr._apply_time({"time": {"day": day_now - 1}}) == []      # rewind ignored
assert store.world_state()["time"]["day"] == day_now
sumr._apply_time({"time": {"day": day_now + 2}})                   # forward applies
assert store.world_state()["time"]["day"] == day_now + 2
print("10) fold-time clock is monotonic fallback only")

print("\nVALIDATOR TESTS PASSED")
