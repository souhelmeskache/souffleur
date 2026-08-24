"""Rules-engine bridge tests: coderain calls dnd5e-engine (D-078/D-200) and
never re-implements a rule. Covers lazy loading, deterministic resolve_check,
a FULL deterministic combat driven through the MCP endpoints (two runs, same
seeds => byte-identical transcripts), IntentRejectedError passthrough, and the
read-only mirroring contract. modules/rpg.py stays untouched (coexistence v0).

Needs dnd5e-engine==0.3.0 installed (requirements.txt); skips loudly if absent.
"""
import asyncio
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 0) Laziness FIRST: importing the bridge package must NOT import the library.
import coderain.rules_engine as RE

assert "dnd5e_engine" not in sys.modules, \
    "coderain.rules_engine import must stay lazy"
print("0) importing coderain.rules_engine pulls no dnd5e_engine module")

try:
    import dnd5e_engine  # noqa: F401
except ImportError:
    print("SKIP: dnd5e-engine not installed (pip install -r requirements.txt)")
    sys.exit(0)

from coderain.rules_engine import get_bridge, intent_rejected_error

# 1) Blocked import: engine() must surface RulesEngineNotInstalled, cleanly.
_saved = sys.modules.pop("dnd5e_engine", None)


class _Blocker:
    def find_spec(self, name, path=None, target=None):
        if name == "dnd5e_engine":
            raise ImportError("blocked for test")
        return None


_blocker = _Blocker()
sys.meta_path.insert(0, _blocker)
RE._ENGINE = None
try:
    try:
        RE.engine()
        raise AssertionError("engine() should have failed while blocked")
    except RE.RulesEngineNotInstalled:
        pass
finally:
    sys.meta_path.remove(_blocker)
    if _saved is not None:
        sys.modules["dnd5e_engine"] = _saved
    RE._ENGINE = None
print("1) lazy load: no import at package import; clean error when missing")

# 2) resolve_check: same seed => identical result, engine-shaped output.
from coderain.rules_engine import resolve_check

SPEC = {"kind": "skill", "ability_scores": {"strength": 16},
        "proficient_skills": ("athletics",), "proficient_saves": (),
        "proficiency_bonus": 2, "skill": "athletics", "dc": 12}
a = resolve_check(SPEC, seed=7)
b = resolve_check(SPEC, seed=7)
assert a == b, (a, b)
assert set(a) >= {"natural_roll", "modifier", "roll_total", "dc", "success"}
assert a["roll_total"] == a["natural_roll"] + a["modifier"]
print(f"2) resolve_check deterministic under seed (nat={a['natural_roll']}, "
      f"mod={a['modifier']}, success={a['success']})")

# 3) FULL combat through the MCP server: two executions, same seeds =>
#    byte-identical transcripts (events + outcome). fastmcp in-memory client.
KAEL = {"entity_id": "pj:kael", "name": "Kael", "initiative": 15,
        "hp_current": 12, "hp_max": 12, "ac": 16, "attack_bonus": 5,
        "strength": 16, "dexterity": 14, "constitution": 14, "zone_id": "z1",
        "equipment": ["longsword"]}
GOBLIN = {"entity_id": "pnj:gob1", "entity_type": "Monster", "name": "Goblin",
          "initiative": 8, "hp_current": 7, "hp_max": 7, "ac": 15,
          "attack_bonus": 4, "damage_dice": "1d6+2", "damage_type": "slashing",
          "zone_id": "z1", "monster_template_slug": "goblin-warrior"}


async def mcp_combat():
    from fastmcp import Client
    from mcp_server import mcp as server
    transcript: list = []
    async with Client(server) as c:
        started = await c.call_tool(
            "start_combat",
            {"session_id": "test-rules-engine", "party": [KAEL],
             "encounter": [GOBLIN], "rng_seed": 1337, "zones": ["z1"]})
        state = started.data
        handle = state["handle_id"]
        transcript.append(state["events"])
        for _ in range(60):
            live = state.get("live") or await _live(c, handle)
            actor = live["active_actor_id"]
            if live["ended"]:
                break
            try:
                if actor and actor.startswith("pj:"):
                    res = await c.call_tool(
                        "submit_intent",
                        {"handle_id": handle, "actor_id": actor,
                         "intent": {"intent_type": "attack",
                                    "target_id": "pnj:gob1",
                                    "weapon_id": "longsword"}})
                else:
                    res = await c.call_tool("monster_turn",
                                            {"handle_id": handle})
                state = res.data
                transcript.append(state["events"])
            except Exception as e:  # noqa: BLE001 — refus moteur = événement à part
                transcript.append([f"REJECTED:{type(e).__name__}:{e}"])
                break
        ended = await c.call_tool("end_combat", {"handle_id": handle})
        transcript.append(ended.data["outcome"])
    return transcript


async def _live(client, handle):
    r = await client.call_tool("narration_events", {"handle_id": handle})
    return r.data["live"]


run_a = asyncio.run(mcp_combat())
run_b = asyncio.run(mcp_combat())
ja, jb = json.dumps(run_a, sort_keys=True), json.dumps(run_b, sort_keys=True)
assert ja == jb, "two seeded runs diverged!"
outcomes = run_a[-1]
n_events = sum(len(chunk) for chunk in run_a[:-1])
assert isinstance(outcomes, dict) and "ended_reason" in outcomes
print(f"3) MCP combat x2 identical ({len(ja)} bytes, {n_events} events, "
      f"ended_reason={outcomes['ended_reason']}, "
      f"{len(outcomes.get('deaths', []))} death(s))")

# 4) Bridge-level mirroring: state lives in the engine, mirror is read-only.
bridge = get_bridge()


async def mirror_probe():
    st = await bridge.start_combat(session_id="mirror-probe", party=[KAEL],
                                   encounter=[GOBLIN], rng_seed=1337,
                                   zones=["z1"])
    h = st["handle_id"]
    before = bridge.live(h)
    assert before["active_actor_id"] == "pj:kael"
    assert bridge.drain_events(h) == []          # start already served the queue
    await bridge.submit_intent(h, "pj:kael",
                               {"intent_type": "pass"})
    after = bridge.live(h)
    assert after["active_actor_id"] != "pj:kael"  # turn moved on
    await bridge.end_combat(h)                    # close so the handle expires
    return h


h = asyncio.run(mirror_probe())
try:
    bridge.live(h)
    raise AssertionError("live() on an ended/removed handle must fail")
except ValueError:
    pass
print("4) mirror is read-only view over engine-held state; stale handle fails")

# 5) IntentRejectedError crosses the bridge AS the engine's own class.
IRE = intent_rejected_error()
assert IRE.__module__.startswith("dnd5e_engine")


async def rejection_probe():
    st = await bridge.start_combat(session_id="reject-probe", party=[KAEL],
                                   encounter=[GOBLIN], rng_seed=5, zones=["z1"])
    h = st["handle_id"]
    try:
        # Kael acts first (fixed initiative 15 vs 8): asking the ENGINE to
        # advance the monster NOW must be rejected by the engine itself,
        # not by this bridge.
        try:
            await bridge.monster_turn(h)
            raise AssertionError("expected IntentRejectedError from the engine")
        except IRE as e:
            return str(e)
        finally:
            await bridge.end_combat(h)
    except Exception:
        await bridge.end_combat(h)
        raise


msg = asyncio.run(rejection_probe())
print(f"5) IntentRejectedError passthrough intact ({msg.split(':')[0]})")

# 6) Coexistence v0: modules/rpg.py untouched by this integration.
rpg_src = Path(__file__).resolve().parents[1] / "coderain" / "modules" / "rpg.py"
text = rpg_src.read_text(encoding="utf-8")
assert "rules_engine" not in text and "dnd5e" not in text.lower()
print("6) modules/rpg.py carries no rules_engine coupling (coexistence v0)")

print("\nRULES-ENGINE TESTS PASSED")
