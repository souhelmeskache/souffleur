"""Outils MCP — famille save et installation (I-233, decoupe de mcp_server.py).

Point d'entree : `mcp_server.py`, qui importe ce module et reexporte ses
outils. Etat partage et helpers communs restent dans `mcp_server` (le module
commun) ; ce fichier y accede via `mcp_server.<nom>`, jamais de copie locale.
"""
from __future__ import annotations

import mcp_server

@mcp_server.mcp.tool()
def list_saves() -> list[dict]:
    """List available saved games (slug, title, last played)."""
    try:
        return mcp_server._library().saves.list()
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)}]


@mcp_server.mcp.tool()
def load_save(slug: str) -> dict:
    """Load a save by slug (folder name under saves/). Must be called before
    any other tool that reads game state.

    Also builds the full engine, which is what makes reveals and quest
    outcomes reach canon-events.md and what makes undo_last possible.

    Refuses a save another live session already holds (I-188, Issue #115):
    an open session is a live engine that can write to its save at any
    moment, so a second session loading the same save would silently
    overwrite the first and keep writing from an already-stale state. A
    lock file at `<save>/.lock.json` (see coderain.save_lock) makes that
    collision fail loudly instead. An orphan lock — its process killed
    without a clean shutdown — is reclaimed automatically rather than
    blocking the save forever."""
    mcp_server._pending_log_mark = None     # a mark from another save is meaningless here
    mcp_server._last_applied_events = None  # idem — R1 signal from another save
    lib = mcp_server._library()
    if not (mcp_server._saves_root / slug).exists():
        return {"error": f"Save not found: {slug}",
                "available": [s.get("slug") for s in lib.saves.list()]}

    save_dir = mcp_server._saves_root / slug
    held = mcp_server.save_lock.held_by_other_live_process(save_dir)
    if held is not None:
        opened = held.get("opened")
        age = f"{(mcp_server.time.time() - opened) / 60:.0f} min" if opened else "?"
        return {"error": f"Save '{slug}' verrouillé — déjà chargé par une "
                          f"autre session ouverte (pid {held.get('pid')} sur "
                          f"{held.get('host')}, depuis {age}). Ferme cette "
                          "session avant de recharger ce save, ou choisis-en "
                          "un autre — deux moteurs vivants sur le même save "
                          "divergent en silence (I-188).",
                "locked_by": held}

    if mcp_server._slug and mcp_server._slug != slug:
        # Switching save within the same session: this process's own lock
        # on the previous save is now stale, release it before moving on.
        mcp_server.save_lock.release(mcp_server._saves_root / mcp_server._slug, mcp_server._slug)

    mcp_server._store = lib.saves.open(slug)  # session-open snapshot (I-148/ESC-4)
    mcp_server._slug = slug
    mcp_server.save_lock.acquire(save_dir, slug)
    mcp_server._load_rpg()          # install ranked skills before anything can roll

    # D&D-style saves carry their own stat names; the validator rejects a check
    # on an unknown stat, so the real keys have to replace the defaults.
    rpg = mcp_server._store.rpg_state()
    player_stats = (rpg.get("player") or {}).get("stats") if rpg else None
    stats = list(player_stats) if isinstance(player_stats, dict) and player_stats \
        else None
    mcp_server._rpg_cfg = dict(mcp_server._DEFAULT_RPG)
    if stats:
        mcp_server._rpg_cfg["stats"] = stats

    engine_error = None
    try:
        from coderain.config import load_config
        from coderain.engine import Engine
        mcp_server._cfg = mcp_server.load_config()
        if stats:
            mcp_server._cfg.rpg = dict(mcp_server._cfg.rpg or {})
            mcp_server._cfg.rpg["stats"] = stats
        mcp_server._engine = Engine(mcp_server._cfg, mcp_server._store)
        # Engine.turn() would call a paid endpoint; nothing here ever does. The
        # engine is used for its deterministic half only.
        mcp_server._engine.trinity = None
    except Exception as e:  # noqa: BLE001
        mcp_server._engine, engine_error = None, f"{type(e).__name__}: {e}"

    # Arm the session's FIRST turn. Without this, the first retry of a session
    # has no snapshot to restore and silently under-undoes.
    mcp_server._completed_turn = None
    mcp_server._arm_turn()

    turns = len(mcp_server._store.turns())
    warnings = mcp_server._lore_warnings(mcp_server._store)
    return {
        "loaded": mcp_server._store.title, "slug": slug,
        "turns": turns,
        "scenes": len(mcp_server._store.entries("memory/scenes.md")),
        "stats": stats or list(mcp_server._rpg_cfg.get("stats") or []),
        "engine": mcp_server._engine is not None,
        "engine_error": engine_error,
        "lore_warning": bool(warnings),
        "lore_warnings": warnings,
    }


@mcp_server.mcp.tool()
def save_snapshot(new_title: str = "") -> dict:
    """Duplicate the current save under a new name — a manual restore point.

    Saves live outside any version control, so this is the only way back after a
    session goes wrong in a way undo_last cannot reach. Cheap: it is a folder copy."""
    if not mcp_server._slug:
        return {"error": "No save loaded."}
    try:
        new_slug = mcp_server._library().saves.duplicate(mcp_server._slug, new_title or None)
        return {"copied_from": mcp_server._slug, "slug": new_slug,
                "title": mcp_server._library().saves.meta(new_slug).get("title", new_slug)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp_server.mcp.tool()
def save_branch(turn_n: int) -> dict:
    """Fork the current save into a new one rewound to turn N — the engine's own
    branch: it replays the validated envelope log, so dice land the same way.
    Returns the new slug plus any warnings the engine raised."""
    if not mcp_server._slug:
        return {"error": "No save loaded."}
    try:
        new_slug, warnings = mcp_server._library().saves.branch(
            mcp_server._slug, int(turn_n), (mcp_server._cfg.rpg if mcp_server._cfg else None))
        return {"slug": new_slug, "from_turn": int(turn_n),
                "warnings": list(warnings)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp_server.mcp.tool()
def undo_last() -> dict:
    """Undo the last exchange: drops the player turn and the narration, rolls
    back that turn's mechanics, re-hides what it revealed, un-consumes the event
    rules it fired. Use it when a turn came out wrong — re-narrating over a bad
    turn leaves the bad one in the transcript and in the engine's memory."""
    eng = mcp_server._require_engine()
    before = len(mcp_server._require_store().turns())
    mcp_server._stage_rollback()
    result = eng.undo_last()
    # The snapshot is consumed by the restore; the next turn needs a fresh one.
    # The ledger mark goes too: the engine truncated the log under it. Same for
    # the R1 signal — the undone turn's envelope no longer applies to anything.
    mcp_server._completed_turn = None
    mcp_server._pending_log_mark = None
    mcp_server._last_applied_events = None
    mcp_server._arm_turn()
    return {"undone": result["undone"],
            "mechanics_restored": result["mechanics_restored"],
            "turns_before": before,
            "turns_after": len(mcp_server._require_store().turns())}


@mcp_server.mcp.tool()
def import_card(file_path: str) -> dict:
    """Import a SillyTavern character card (PNG/JSON/.charx).
    Returns the parsed card data (name, description, personality, scenario, etc.)."""
    from coderain.cards import parse_card
    p = mcp_server.Path(file_path)
    if not p.exists():
        return {"error": f"File not found: {file_path}"}
    try:
        return parse_card(p.read_bytes(), p.name)
    except Exception as e:
        return {"error": str(e)}


# ── P4 conversion bridge — pont-MCP variant (Issue #173) ──────────
# convert_module (converter/convert.py) already takes llm_main/llm_recheck as
# injection — segmentation.segment (segmentation.py:52), buckets.classify
# (buckets.py:47) and semantic.convert_unit/convert_batch (semantic.py:198,
# :223) all reach the model through emit_json_ex(llm, ...). _ShimLLM/_NeedLLM
# (defined in mcp_server, for the fold) plug in unmodified: no new shim, no
# rewritten stage logic.
#
# Unlike the fold (at most one call per fold_apply), a conversion is several
# calls deep — one per segmentation chunk, one for bucketing, one per semantic
# batch/unit. Rather than track a cursor across calls, p4_convert_step REPLAYS
# convert_module from the top on every call, with the session's growing
# answers list: convert_module's call order is deterministic for a fixed
# source_text, so every earlier stage is served its already-known answer from
# the list and only the first missing call raises _NeedLLM. Nothing is
# written to out_dir until the run reaches the end without raising — a
# half-answered conversion never leaves a partial partition on disk.

@mcp_server.mcp.tool()
def p4_convert_step(source_text: str, titre: str, structures: list[str],
                    corpus_source: str, target_version: str, out_dir: str,
                    answers: list[str] | None = None) -> dict:
    """Drive a P4 free-prose conversion (SPEC-P4 §3, `converter/convert.py`)
    step by step through the session instead of the API — the pont-MCP
    variant of `cmd_convert`'s LLM route, same patron as fold_due/fold_apply
    but for a multi-call sequence.

    Call with answers=[] first. A {"due": true, "instruction": ...,
    "payload": ...} result is coderain's own prompt/payload for the next
    stage (segmentation, bucketing, or one semantic batch/unit), verbatim —
    hand both to a cheap subagent, take the JSON text it returns, append it
    to `answers` (do not edit it) and call again. Every earlier answer
    replays; only the next missing stage is asked. Keep looping until "due"
    is false: that result carries the written partition's report (same shape
    as `convert_module`'s, plus counts).

    Zero network call anywhere in this path: convert_module never sees a
    real LLM client, only this shim."""
    answers = list(answers or [])
    shim = mcp_server._ShimLLM(answers)
    try:
        partition, report = mcp_server.convert_module(
            source_text, titre, list(structures), corpus_source,
            target_version, shim, mcp_server.Path(out_dir), llm_recheck=None)
    except mcp_server._NeedLLM as need:
        return {"due": True, "step": len(answers),
                "instruction": need.system, "payload": need.payload}
    return {"due": False, "report": report,
            "nodes": len(partition.nodes), "records": len(partition.records),
            "tables": len(partition.tables), "secrets": len(partition.secrets)}


__all__ = ['list_saves', 'load_save', 'save_snapshot', 'save_branch', 'undo_last', 'import_card', 'p4_convert_step']
