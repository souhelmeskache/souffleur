"""Outils MCP — famille memoire et rappel (I-233, decoupe de mcp_server.py).

Point d'entree : `mcp_server.py`, qui importe ce module et reexporte ses
outils. Etat partage et helpers communs restent dans `mcp_server` (le module
commun) ; ce fichier y accede via `mcp_server.<nom>`, jamais de copie locale.
"""
from __future__ import annotations

import mcp_server

@mcp_server.mcp.tool()
def lookup_memory(query: str) -> str:
    """Search all story entries (characters, locations, factions, items, events,
    threads) by keyword. Hidden entries are masked (secrets stay safe)."""
    return mcp_server._require_store().lookup(query)


@mcp_server.mcp.tool()
def recall_turns(reference: str) -> str:
    """Fetch verbatim past turns by timeline ref, scene slug, or range ('T6-10').
    Use when you need exact earlier dialogue/narration, not just a summary."""
    return mcp_server._require_store().recall_turns(reference)


@mcp_server.mcp.tool()
def recall_entity(name: str) -> str:
    """Entity index: the full entry + every episode mentioning that character or
    location, with turn pointers for drill-down via recall_turns."""
    return mcp_server._require_store().recall_entity(name)


@mcp_server.mcp.tool()
def recall_quest(name: str) -> str:
    """Quest index: thread entry + live status + every episode that touched it."""
    return mcp_server._require_store().recall_quest(name)


@mcp_server.mcp.tool()
def retry_turn() -> dict:
    """Take back the last exchange and hand the player's action back, so the same
    action can be narrated again from the same state.

    This is the engine's own /retry: it drops the narration AND the player turn,
    rolls back that turn's mechanics, re-hides what it revealed and un-consumes
    the event rules it fired. Re-narrating without it stacks a second set of
    deltas on top of the first and leaves the discarded version in memory.

    Returns {"action": ...} — narrate that action again, then record_turn as usual.
    Use undo_last instead when the player should act differently rather than the
    same beat being retold."""
    eng = mcp_server._require_engine()
    store = mcp_server._require_store()
    turns = store.turns()
    mechanics_restored = True
    if turns and turns[-1]["role"] == "narrator" and len(turns) >= 2:
        if turns[-2]["role"] == "player":
            action = turns[-2]["text"]
            store.drop_last_turns(2)
        else:
            action = ""
            store.drop_last_turns(1)
            mechanics_restored = False
    elif turns and turns[-1]["role"] == "player":
        action = turns[-1]["text"]
        store.drop_last_turns(1)
    else:
        return {"error": "Nothing to retry yet."}
    mcp_server._stage_rollback()
    eng.restore_pre_turn_rpg()
    mcp_server._completed_turn = None
    mcp_server._pending_log_mark = None     # the engine truncated the log under the mark
    mcp_server._last_applied_events = None  # the retried envelope no longer applies
    mcp_server._arm_turn()          # the replayed turn needs its own snapshot
    n = len(store.turns())
    # The native loop re-probes the fold after a retry (play.py:363-365); the
    # turn count moved, so the answer can have changed.
    return {"action": action, "turns": n, "fold_due": mcp_server._fold_probe(n),
            "mechanics_restored": mechanics_restored}


@mcp_server.mcp.tool()
def fold_due() -> dict:
    """Is a memory fold due, and if so what does coderain want summarised?

    Returns {"due": false} when nothing is pending, otherwise
    {"due": true, "instruction": ..., "payload": ...} — coderain's own prompt and
    its own payload, verbatim. Hand both to a cheap subagent, take the JSON it
    returns, and pass it to fold_apply. Do not edit the instruction and do not
    write the summary yourself: the JSON shape it asks for is what fold_apply
    feeds back into the engine.

    Nothing is written by this call."""
    return mcp_server._run_fold(None, probe=True)


@mcp_server.mcp.tool()
def fold_apply(summary_json: str) -> dict:
    """Feed one fold answer back to coderain, which writes the scene (or the
    arc), updates the timeline, promotes durable facts into entries, and advances
    its fold counters.

    Returns what changed plus "next": another fold is due right away (a long
    session can owe several), so keep looping fold_due -> subagent -> fold_apply
    until "next" is null."""
    eng = mcp_server._require_engine()
    store = eng.summarizer.store
    before = (len(store.entries("memory/scenes.md")),
              len(store.read("memory/arc.md")))
    out = mcp_server._run_fold([summary_json], probe=False)
    after = (len(store.entries("memory/scenes.md")),
             len(store.read("memory/arc.md")))
    return {
        "scenes": after[0], "scenes_added": after[0] - before[0],
        "arc_chars": after[1], "arc_changed": after[1] != before[1],
        "events": out.get("events", []),
        "next": ({"instruction": out["instruction"], "payload": out["payload"]}
                 if out.get("due") else None),
    }


__all__ = ['lookup_memory', 'recall_turns', 'recall_entity', 'recall_quest', 'retry_turn', 'fold_due', 'fold_apply']
