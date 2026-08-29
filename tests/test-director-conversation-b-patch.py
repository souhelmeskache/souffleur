"""Director conversation B patch — D-219/D-220 (Issue #15/#81).

Verifies the patch inserted into DIRECTOR_SYS (coderain/modules/trinity.py):
  1. The protocol block (4 windows, D-219) reaches the Director prompt, for
     both the world and rpg envelope schema tails.
  2. `%`-formatting of DIRECTOR_SYS still works (the inserted text must not
     contain a stray `%` that collides with the `DIRECTOR_SYS % schema_tail`
     substitution).
  3. Structural separation holds: the Writer never receives DIRECTOR_SYS (so
     the negotiable/non-negotiable vocabulary the Director is told never to
     write can't leak to the Writer through the system prompt itself — same
     guard shape as the event-rules Director-only test in wave4_test.py).
  4. End-to-end turn: a stubbed Director sees the block, a stubbed Writer
     never does.
"""
import os
import sys
import shutil
import tempfile
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Entry, Library
from coderain.modules.trinity import DIRECTOR_SYS, _ENV_WORLD, _ENV_RPG

MARKER = "CONVERSATION D'ACCORD"
NEGOTIABLE = "négociable"
NON_NEGOTIABLE = "non-négociable"

# ---- 1) & 2) static: block present, %-formatting survives both schema tails ----
for tail, label in ((_ENV_WORLD, "world"), (_ENV_RPG, "rpg")):
    sys_prompt = DIRECTOR_SYS % tail
    assert MARKER in sys_prompt, f"D-219 block missing from DIRECTOR_SYS ({label})"
    assert NEGOTIABLE in sys_prompt and NON_NEGOTIABLE in sys_prompt, \
        f"négociable/non-négociable vocabulary missing ({label})"
    assert "D-219" in sys_prompt and "D-220" in sys_prompt
print("1&2) D-219 block present in DIRECTOR_SYS; %-formatting intact "
      "(world + rpg schema tails)")

# ---- 3) & 4) end-to-end: Director sees the block, Writer never does ----
root = os.path.join(tempfile.gettempdir(), "se_director_conversation_b_patch")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
save = lib.saves.create("Accord", mode="simple", premise="A quiet arrival.")
store = lib.store(save)

cfg = load_config()
cfg.generation["trinity_brain"] = True
cfg.raw["trinity"] = {}
eng = Engine(cfg, store)


class Stub:
    def complete(self, messages, **k):
        joined = " ".join(m["content"] for m in messages)
        assert MARKER in joined, "director prompt missing the D-219 block"
        return json.dumps({"beat_plan": "The traveler is welcomed at the gate.",
                            "must_stay_consistent": [], "recall_queries": []})

    def stream(self, messages, **k):
        joined = " ".join(m["content"] for m in messages)
        assert MARKER not in joined, "D-219 block leaked into the writer prompt!"
        assert NEGOTIABLE not in joined and NON_NEGOTIABLE not in joined, \
            "négociable/non-négociable vocabulary leaked into the writer prompt!"
        yield "The gate opens without a word."


stub = Stub()
eng.llm = stub
eng.trinity.director_llm = stub
eng.trinity.writer_llm = stub
out = "".join(eng.turn("approach the gate"))
assert out == "The gate opens without a word."
print("3&4) end-to-end turn: director-only injection confirmed, "
      "writer prompt clean")

print("test-director-conversation-b-patch: OK")
