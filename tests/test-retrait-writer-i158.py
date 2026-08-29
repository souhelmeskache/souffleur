"""Issue #108 (I-158 measure) -- director-pipeline Writer retrait guard: the
Writer's own copy of the assembled context must never carry Director-only
material -- event_rules_block (SCENARIO EVENT RULES) or the "Secrets you
know" section. Before this fix that held only for event_rules, and only by
accident of Python scope (`event_rules_block` concatenated into
`director_msgs`, a local copy of `trinity.py::_direct`, never reinjected into
`messages`) -- no contract, no test, a refactor could break it silently. This
is now DECLARED (`TrinityBrain._writer_context`) and tested here, symmetric to
the director-de-table guard (mcp_server.py's `assemble_context_to_file`
defaults `event_rules=False, secrets=False`, tested in
test-garde-secrets-i159.py).
"""
import os, sys, shutil, tempfile, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Entry, Library

root = os.path.join(tempfile.gettempdir(), "se_retrait_writer_i158")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
save = lib.saves.create("Ossuary", mode="rpg",
                        premise="A heist beneath a warden's ossuary.")
store = lib.store(save)
st = store.rpg_state(); st["seed"] = 4
store.set_rpg_state(st)

# A once-only event rule (Director-only, D-260/Wave 4) ...
store.upsert_entry("events.md", Entry(
    "When the ossuary door opens", "ossuary-alarm", importance=4,
    attrs={"once": "true"},
    body="A silent alarm summons the wardens within three turns."))
# ... and a hidden+pinned secret (I-159: the one combination that always
# activates, forcing the "Secrets you know" section into the assembled
# context on every turn regardless of haystack match).
store.upsert_entry("characters.md", Entry(
    "The Warden", "the-warden", importance=5,
    attrs={"hidden": "true", "pinned": "true"},
    body="The warden secretly owes the thieves guild a fortune."))

cfg = load_config()
cfg.generation["trinity_brain"] = True
cfg.raw["trinity"] = {}
eng = Engine(cfg, store)


class GuardStub:
    def complete(self, messages, **k):
        # sanity: the Director must actually receive both -- otherwise this
        # test would pass for the wrong reason (nothing to leak).
        joined = " ".join(m["content"] for m in messages)
        assert "ossuary-alarm" in joined and "silent alarm" in joined, \
            "director missing event rules -- fixture broken"
        assert "Secrets you know" in joined and "thieves guild" in joined, \
            "director missing secrets -- fixture broken"
        return json.dumps({"beat_plan": "The door creaks open.",
                           "envelope": {"v": 1,
                                        "deltas": {"event_fired": ["ossuary-alarm"]}}})

    def stream(self, messages, **k):
        # "SCENARIO EVENT RULES" also names the concept generically in
        # writer-rules.md's documentation of `event_fired` (templates.py) --
        # so the guard checks the RULE'S OWN content (slug + body), same as
        # wave4_test.py §1, not the header phrase alone.
        joined = " ".join(m["content"] for m in messages)
        assert "ossuary-alarm" not in joined and "silent alarm" not in joined, \
            "event rule content leaked to the writer!"
        assert "Secrets you know" not in joined, \
            "secrets section leaked to the writer!"
        assert "thieves guild" not in joined, \
            "secret body leaked to the writer!"
        yield "The vault exhales stale air."


stub = GuardStub()
eng.llm = stub
eng.trinity.director_llm = stub
eng.trinity.writer_llm = stub
out = "".join(eng.turn("ask the warden about the door, then open it"))
assert out == "The vault exhales stale air."
print("1) Writer excludes BOTH event_rules_block and the secrets section")

# ---- 2) Simple mode bypass (skip_logic, no envelope) gets the same retrait ----
save2 = lib.saves.create("Ossuary Fast", mode="simple",
                         premise="A doorstep, nothing more.")
store2 = lib.store(save2)
store2.upsert_entry("characters.md", Entry(
    "The Warden", "the-warden", importance=5,
    attrs={"hidden": "true", "pinned": "true"},
    body="The warden secretly owes the thieves guild a fortune."))
cfg2 = load_config()
cfg2.generation["trinity_brain"] = True
cfg2.raw["trinity"] = {}
eng2 = Engine(cfg2, store2)


class SimpleGuardStub:
    def stream(self, messages, **k):
        joined = " ".join(m["content"] for m in messages)
        assert "Secrets you know" not in joined and "thieves guild" not in joined, \
            "secrets section leaked to the writer in simple-mode bypass!"
        yield "A quiet knock."


eng2.llm = SimpleGuardStub()
eng2.trinity.writer_llm = eng2.llm
out2 = "".join(eng2.turn("knock on the door"))
assert out2 == "A quiet knock."
print("2) simple-mode bypass (skip_logic, no envelope) excludes secrets too")

print("\nALL OK -- test-retrait-writer-i158.py")
