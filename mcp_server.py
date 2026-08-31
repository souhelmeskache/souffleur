"""MCP server — coderain deterministic engine for Claude Code.

Exposes coderain's game engine (validator, memory, RPG mechanics, recall tools)
as MCP tools. All LLM calls stay in Claude Code; this server handles only
pure-code operations.

Usage (stdio, for .mcp.json):
    python mcp_server.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from fastmcp import FastMCP

from coderain.memory import Library, MemoryStore
from coderain import assembleur_position
from coderain import save_lock
from coderain import validator as validator_mod
from coderain.rules_engine import get_bridge
from coderain.sidecar import DEFAULT_CFG as _DEFAULT_RPG
from coderain.config import load_config, saves_dir
# D-263 (Issue #147) — organes Auteur : `coderain.acte` et `coderain.formes`
# n'importent jamais coderain.llm (zéro dépendance LLM, voir leurs propres
# docstrings) et sont donc importés directement. `coderain.retour2` et
# `coderain.ecrivain_module`, eux, portent `from .llm import emit_json_ex` à
# leur racine — les importer ferait exécuter `from openai import OpenAI`
# (coderain/llm.py:13) au chargement de ce pont, exactement ce que D-263
# interdit ("aucun appel LLM ... ne touche pas llm.py"). Leurs gardes de
# forme pures sont donc RE-PORTÉES ici en plus petit — voir le bloc
# « organes Auteur » plus bas, jamais un import de ces deux modules.
from coderain import acte as acte_mod
from coderain import formes as formes_mod
# `coderain.converter.convert` is a DIFFERENT case from retour2/ecrivain_module
# above: it does not duplicate llm.py's logic, it takes an injected llm_main/
# llm_recheck exactly like the fold's `sm.llm` — the same _ShimLLM/_NeedLLM
# already plug into it (see "P4 conversion bridge" below). Importing it here
# adds no new dependency: `coderain.rules_engine` above already pulls in
# coderain.llm transitively (engine.py -> llm.py), same as the fold's path
# through Engine.summarizer.
from coderain.converter.convert import convert_module

mcp = FastMCP("coderain-engine")

# ── why this file goes through Engine and Library, not around them ───
# The first version of this bridge re-implemented the pieces it needed:
# it built a MemoryStore by hand, and re-wrote apply_envelope out of
# validator + rpg calls. Each re-implementation quietly dropped whatever
# the original also did — canon events on reveals and on quest outcomes,
# undo bookkeeping, the last-played timestamp. The engine is not a
# reference to imitate; it is the thing to call. LLM work is the only
# part that stays out (it runs on the user's Claude plan, not here), and
# even that is split rather than rewritten — see fold_due/fold_apply.

_lib: Library | None = None
_cfg = None
_engine = None
_store: MemoryStore | None = None
_slug: str = ""
_rpg_cfg: dict = dict(_DEFAULT_RPG)
class InstructionsRootError(RuntimeError):
    """config.yaml sets instructions_root but that folder does not exist.

    Raised where the rule masters are about to be wired, so the server stays
    up and every tool fails with an error naming the misconfiguration instead
    of silently reading empty rules (or seeding a copy) in the wrong place."""


def _resolve_instructions_root() -> tuple[Path, bool]:
    """The governing-masters folder: config.yaml's `instructions_root` when set,
    else the historic ROOT / "instructions". Returns (path, from_config).
    Any config problem falls back to the default — a broken or missing
    config.yaml must not kill server startup; the misconfiguration surfaces as
    a named error when rules are actually read."""
    default = ROOT / "instructions"
    try:
        raw = str(load_config().raw.get("instructions_root") or "").strip()
    except Exception as exc:
        print(f"[mcp_server] [WARN] config.yaml unreadable ({exc}) - "
              f"instructions root stays {default}", file=sys.stderr)
        return default, False
    if not raw:
        return default, False
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve(), True


_saves_root: Path = saves_dir()  # same resolution as memory.Library (config.saves_dir)
# Sentinel: "this pipeline resolved the mechanics before the narrator wrote".
# See _assemble_text — it is what selects the engine's quad-mode sheet.
_RESOLVED_BEFORE_NARRATION = object()
_instructions_root, _instructions_from_config = _resolve_instructions_root()
_scenarios_root: Path = ROOT / "scenarios"

_instructions_source = ("config.yaml instructions_root"
                        if _instructions_from_config else "default")
print(f"[mcp_server] instructions root: {_instructions_root}"
      f"  ({_instructions_source})", file=sys.stderr)
if _instructions_from_config and not _instructions_root.is_dir():
    print(f"[mcp_server] [ERROR] instructions_root points to a missing "
          f"folder: {_instructions_root}", file=sys.stderr)


def _require_store() -> MemoryStore:
    if _store is None:
        raise ValueError("No save loaded. Call load_save first.")
    return _store


def _require_engine():
    if _engine is None:
        raise ValueError(
            "Engine unavailable — load_save could not build it (see its return "
            "value). The degraded path still plays, but reveals and quest "
            "outcomes will not be written to canon-events.md.")
    return _engine


def _library() -> Library:
    global _lib
    if _lib is None:
        lib = Library(ROOT)
        if _instructions_from_config:
            if not _instructions_root.is_dir():
                raise InstructionsRootError(
                    "config.yaml sets instructions_root to "
                    f"'{_instructions_root}' but that folder does not exist")
            # Library pins its masters dir to root/"instructions" internally;
            # re-point all three layers instead of duplicating its wiring.
            # No re-seed on purpose: a configured masters folder is read,
            # never written — the external source stays the single source.
            lib.instructions_dir = _instructions_root
            lib.scenarios.instructions_dir = _instructions_root
            lib.saves.instructions_dir = _instructions_root
        _lib = lib
    return _lib


# ── the one hole the secret guard cannot plug ────────────────────
# _assemble_text protects hidden entries by choosing which haystack feeds the
# Secrets section (see there). That works because a hidden entry reaches the
# section through _entry_activates — i.e. through the haystack. One kind does
# not: memory.py:1308 evaluates `always = e.pinned() or e.weight() == "critical"`
# BEFORE the trigger test and before the hidden() test, so a hidden entry that is
# also pinned or critical activates on EVERY haystack, in both passes, at every
# budget. No code in this bridge can hold it back without overriding the engine's
# own selection, which is the line this file does not cross.
#
# Measured on the live campaign: 0 such entries out of 20 hidden. The protection
# therefore holds by a property of the DATA, not by code — one `pinned: true`
# typed on a hidden entry silently ends it. So it is surfaced where the loop
# already looks: load_save, which every session calls before the screen flips.
# A warning, not a block: an author may want exactly that.
#
# ── and the trap that warning walked into (fixed 2026-08-03) ──
# This list is PRINTED. jouer/SKILL.md step 1 orders it shown "in the terminal,
# here, before the switch" — i.e. on the one screen the player is still watching,
# by design (the switch to the web UI happens at step 4). The first version named
# the entry: `characters.md:<slug> is hidden AND pinned…`. Measured on a
# fabricated store: the printed line contained the secret's slug. Exposure was 0
# because no hidden entry carries either flag today — the anti-spoil lint was one
# `pinned: true` away from writing the name of a secret under the player's eyes.
#
# So the returned lines COUNT, they never name. The author still needs the name
# to act on it: the detail goes to stderr, which is the machine room (stdout is
# the MCP channel), never a value any skill prints.
def _lore_warnings(store) -> list[str]:
    # I-159: the scan itself (registry/slug/why) is the shared "weapon" —
    # coderain.validator.scan_hidden_forced, also exercised standalone by
    # tests/test-garde-secrets-i159.py. This function stays responsible only
    # for what a caller allowed to reach the player is allowed to say.
    out, detail, counts = [], [], {}
    for hit in validator_mod.scan_hidden_forced(store):
        rel = hit["registry"]
        counts[rel] = counts.get(rel, 0) + 1
        detail.append(f"{rel}:{hit['slug']} ({'+'.join(hit['why'])})")
    for rel, n in counts.items():
        out.append(
            f"{rel}: {n} hidden entry/entries also carry pinned or critical — the "
            "engine serves them in the Secrets section on EVERY context, whatever "
            "the scene (memory.py:1308). Names are withheld here on purpose (this "
            "line is printed where the player can read it); the detail is on the "
            "server's stderr. Drop the flag, or accept it as permanent.")
    if detail:
        print("lore_warnings DETAIL (machine room — never print this to the "
              "player): " + "; ".join(detail), file=sys.stderr)
    return out


# ── the turn prologue, armed by the bridge (2026-08-03) ──────────
# Engine.restore_pre_turn_rpg() — what undo_last and retry_turn delegate to —
# undoes a turn from state that only the PROLOGUE of Engine.turn()/opening()
# captures: a deep copy of the whole world state, plus three empty lists that
# then collect what this turn revealed, canonised and consumed. The bridge never
# calls turn() (it is the paid path), so that prologue never ran. Measured
# consequences: the snapshot stayed None, so retry restored nothing and the
# re-narration applied a SECOND set of deltas on top of the first; and the three
# lists, never cleared, accumulated over the whole session, so one retry undid
# every reveal the session had ever made.
#
# It is armed here, automatically, and never by a skill. A fix that takes the
# form of one more step a skill must remember is the bug it is fixing:
# record_turn is already mandatory and two paths still forgot it. So the arming
# hangs off gestures the loop makes anyway — load_save, record_turn, and the two
# rollback tools themselves.
#
# One turn's rollback material has to OUTLIVE the arming of the next turn:
# record_turn is the turn boundary, and retry/undo are called after it, on the
# exchange it just wrote. So record_turn retires what it has before arming
# afresh, and the rollback tools put the retired set back where the engine looks
# for it. Arming without retiring would hand restore_pre_turn_rpg a snapshot
# taken AFTER the very deltas it is meant to undo — a silent no-op, i.e. the
# original bug wearing a fix's clothes.
_completed_turn: tuple | None = None


def _arm_turn(retire: bool = False) -> None:
    """Capture the pre-turn state and reset the per-turn undo trackers."""
    global _completed_turn
    eng = _engine
    if eng is None:
        return
    if retire:
        _completed_turn = (eng._pre_turn_rpg, list(eng._pre_turn_reveals),
                           list(eng._pre_turn_canon), list(eng._pre_turn_events))
    eng._pre_turn_rpg = eng._snapshot_rpg()
    eng._pre_turn_reveals = []
    eng._pre_turn_canon = []
    eng._pre_turn_events = []
    eng._rpg_events = []


def _stage_rollback() -> None:
    """Hand the engine the rollback material of the last RECORDED exchange, so
    restore_pre_turn_rpg undoes THAT turn and not the one being armed."""
    eng = _engine
    if eng is None or _completed_turn is None:
        return
    (eng._pre_turn_rpg, eng._pre_turn_reveals,
     eng._pre_turn_canon, eng._pre_turn_events) = _completed_turn


# ── which ledger records belong to THIS turn (fixed 2026-08-03) ──
# apply_envelope files its record under a PREDICTED index; record_turn corrects
# it once the real one is known. The correction has to know WHICH records to
# correct, and "every record stamped above pending_from" is not that predicate:
# it also matches a record another writer left stamped past the end of the
# transcript. That state is not hypothetical — the save the product SHIPS is in
# it. Measured on `untitled` as delivered (4 turns, ledger [0, 5], the 5 a native
# +1 stamp whose transcript was later rolled back):
#     start            : stamps [0, 5]
#     after apply      : stamps [0, 5, 6]
#     after record_turn: stamps [0, 6, 6]   <- record 5 adopted by this turn
# and then save_branch(5) no longer carried that envelope at all, while
# save_branch(6) replayed it as part of a turn it never belonged to.
#
# So the mark is POSITIONAL, not a value test: how long the ledger was at the
# moment this turn filed its envelope. Whatever was already there is somebody
# else's, whatever it claims. The value test stays as a second belt (a record
# this turn wrote but already at the right index needs no rewrite).
#
# It is armed on apply_envelope and consumed by record_turn — both gestures the
# loop already makes; no skill has a new step to remember. None (no envelope
# applied this turn, or a fresh process) means: restamp nothing.
#
# Declared limit, measured: the mark protects what was in the ledger BEFORE this
# turn filed its envelope, not what a third writer appends BETWEEN apply_envelope
# and record_turn — such a record sits inside the marked slice and is restamped
# with the turn's own. Nothing writes there in this pipeline (the only appender
# is Engine.apply_envelope), and the alternative — matching on the predicted
# value +2 — collides with exactly the orphan this fixes.
_pending_log_mark: int | None = None


# ── R1 signal for `paquet_narrateur` (Issue #192, D-269 ; Issue #200) ──
# "mécanique avant prose" needs a machine-checkable fact, not a Director's
# say-so: whether a mechanic actually landed THIS turn. apply_envelope was the
# one mutation path for the coderain-native envelope pipeline (see its own
# docstring), so its own return value — the human-readable event strings,
# already the engine's journal of what was rolled and applied — IS that fact.
# Kept here rather than re-derived from the event log on disk because the log
# stores raw envelopes, not the readable strings `paquet_narrateur` serves
# under "MÉCANIQUES RÉSOLUES CE TOUR" (spec §"Ce que l'outil compose", point
# 3) — reusing this avoids a second, divergent rendering of the same
# application.
#
# Issue #200: apply_envelope is NOT the only mutation path — the combat
# sub-system (start_combat/submit_intent/monster_turn, dnd5e-engine via
# CombatBridge) mutates entirely outside it. Those three tools post to this
# same signal (see `_record_combat_events` near the combat tools below),
# converting the engine's own events (intents, damage, rounds) into the same
# readable-string register. Unlike apply_envelope (one envelope per turn, so
# an assignment), combat turns chain several calls before paquet_narrateur —
# the events ACCUMULATE there rather than overwrite.
#
# None = "no mechanic resolved since the last turn boundary" — the R1
# refusal fires on exactly that, unless `sans_mecanique` declares it on
# purpose. Reset at every turn boundary (record_turn) and by the three
# gestures that invalidate "this turn" outright (load_save, undo_last,
# retry_turn) — the same boundaries _pending_log_mark already respects, for
# the same reason.
_last_applied_events: list[str] | None = None


def _event_log_len(store) -> int:
    from coderain.memory import _read_event_log
    return len(_read_event_log(store))


def _restamp_turn_log(store, pending_from: int, narrator_turn: int) -> None:
    """Point THIS turn's ledger records at the narrator turn that just landed.

    apply_envelope runs BEFORE the turn is written, so it can only predict the
    index its envelope belongs to (+2: a player turn and a narrator turn are
    about to arrive). The prediction is exact for an ordinary exchange and one
    too far for a narration recorded without an action — the opening scene. Here
    the real count is known, so the prediction is corrected — on the records this
    turn added, and on no others."""
    global _pending_log_mark
    mark, _pending_log_mark = _pending_log_mark, None
    if mark is None or narrator_turn <= pending_from:
        return
    turns = store.turns()
    if not turns or turns[-1]["role"] != "narrator":
        return          # no narrator turn landed; leave the prediction alone
    # The engine's own reader and writer. _write_event_log goes through
    # store.write, i.e. the atomic path (temp + os.replace + the Windows
    # sharing-violation retry): a plain write_text truncates first, and a
    # half-written replay ledger is a save that branches wrong. This file used to
    # carry its own copy of both.
    from coderain.memory import _read_event_log, _write_event_log
    records = _read_event_log(store)
    changed = False
    for rec in records[mark:]:          # slice past the mark = this turn's own
        if rec.get("turn", 0) > pending_from and rec.get("turn") != narrator_turn:
            rec["turn"], changed = narrator_turn, True
    if changed:
        _write_event_log(store, records)


# ── ranked skills (2026-08-03) ───────────────────────────────────
# Upstream gives every trained skill the SAME flat proficiency bonus (+2). For a
# d20 system with per-skill ranks that flattens the character: a +12 skill and a
# +3 skill roll identically. Worse, it is exactly the "lissage vers un héroïsme
# moyen constant" the campaign's own rules forbid — the sheet is supposed to have
# peaks and troughs.
#
# Fix: let the `skills:`/`abilities:` attribute carry the real modifier —
#     skills: fouille (dexterity +8), diplomatie (charisma +3), natation
# `fouille` then adds +8, `natation` (no number) falls back to the flat bonus,
# and an unlisted skill still adds 0. Upstream's own parser puts "dexterity +8"
# in its stat slot, which nothing reads, so the format stays compatible.
#
# Installed by rebinding the module global, so BOTH paths pick it up: the direct
# roll_check tool AND rpg.apply(), which resolves an envelope's `check` through
# the same name (modules/rpg.py:178).
_SKILL_VALUE_RE = re.compile(r"([+-]?\d+)")


def _skill_mod_ranked(store, actor_slug, skill_name, cfg=None) -> int:
    name = (skill_name or "").strip().lower()
    if not name:
        return 0
    is_player = actor_slug in ("player", "you", "")
    rel = "player.md" if is_player else "characters.md"
    try:
        entries = store.entries(rel)
    except Exception:  # noqa: BLE001 — never let a bad file break a roll
        return 0
    target = None
    for e in entries:
        if is_player or e.slug == actor_slug:
            target = e
            break
    if target is None:
        return 0
    try:
        flat = int((cfg or _rpg_cfg).get("skill_bonus") or 2)
    except (TypeError, ValueError):
        flat = 2
    for key in ("skills", "abilities"):
        for part in (target.attrs.get(key, "") or "").split(","):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", part)
            sname, inner = (m.group(1), m.group(2)) if m else (part, "")
            if sname.strip().lower() != name:
                continue
            num = _SKILL_VALUE_RE.search(inner)
            return int(num.group(1)) if num else flat
    return 0


def _load_rpg():
    from coderain.modules import rpg as rpg_mod
    if not getattr(rpg_mod, "_ranked_skills_installed", False):
        rpg_mod.skill_mod = _skill_mod_ranked
        rpg_mod._ranked_skills_installed = True
    return rpg_mod


# ── save management ──────────────────────────────────────────────

@mcp.tool()
def list_saves() -> list[dict]:
    """List available saved games (slug, title, last played)."""
    try:
        return _library().saves.list()
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)}]


@mcp.tool()
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
    global _store, _engine, _cfg, _rpg_cfg, _slug, _completed_turn
    global _pending_log_mark, _last_applied_events
    _pending_log_mark = None     # a mark from another save is meaningless here
    _last_applied_events = None  # idem — R1 signal from another save
    lib = _library()
    if not (_saves_root / slug).exists():
        return {"error": f"Save not found: {slug}",
                "available": [s.get("slug") for s in lib.saves.list()]}

    save_dir = _saves_root / slug
    held = save_lock.held_by_other_live_process(save_dir)
    if held is not None:
        opened = held.get("opened")
        age = f"{(time.time() - opened) / 60:.0f} min" if opened else "?"
        return {"error": f"Save '{slug}' verrouillé — déjà chargé par une "
                          f"autre session ouverte (pid {held.get('pid')} sur "
                          f"{held.get('host')}, depuis {age}). Ferme cette "
                          "session avant de recharger ce save, ou choisis-en "
                          "un autre — deux moteurs vivants sur le même save "
                          "divergent en silence (I-188).",
                "locked_by": held}

    if _slug and _slug != slug:
        # Switching save within the same session: this process's own lock
        # on the previous save is now stale, release it before moving on.
        save_lock.release(_saves_root / _slug, _slug)

    _store = lib.saves.open(slug)  # session-open snapshot (I-148/ESC-4)
    _slug = slug
    save_lock.acquire(save_dir, slug)
    _load_rpg()          # install ranked skills before anything can roll

    # D&D-style saves carry their own stat names; the validator rejects a check
    # on an unknown stat, so the real keys have to replace the defaults.
    rpg = _store.rpg_state()
    player_stats = (rpg.get("player") or {}).get("stats") if rpg else None
    stats = list(player_stats) if isinstance(player_stats, dict) and player_stats \
        else None
    _rpg_cfg = dict(_DEFAULT_RPG)
    if stats:
        _rpg_cfg["stats"] = stats

    engine_error = None
    try:
        from coderain.config import load_config
        from coderain.engine import Engine
        _cfg = load_config()
        if stats:
            _cfg.rpg = dict(_cfg.rpg or {})
            _cfg.rpg["stats"] = stats
        _engine = Engine(_cfg, _store)
        # Engine.turn() would call a paid endpoint; nothing here ever does. The
        # engine is used for its deterministic half only.
        _engine.trinity = None
    except Exception as e:  # noqa: BLE001
        _engine, engine_error = None, f"{type(e).__name__}: {e}"

    # Arm the session's FIRST turn. Without this, the first retry of a session
    # has no snapshot to restore and silently under-undoes.
    _completed_turn = None
    _arm_turn()

    turns = len(_store.turns())
    warnings = _lore_warnings(_store)
    return {
        "loaded": _store.title, "slug": slug,
        "turns": turns,
        "scenes": len(_store.entries("memory/scenes.md")),
        "stats": stats or list(_rpg_cfg.get("stats") or []),
        "engine": _engine is not None,
        "engine_error": engine_error,
        "lore_warning": bool(warnings),
        "lore_warnings": warnings,
    }


@mcp.tool()
def save_snapshot(new_title: str = "") -> dict:
    """Duplicate the current save under a new name — a manual restore point.

    Saves live outside any version control, so this is the only way back after a
    session goes wrong in a way undo_last cannot reach. Cheap: it is a folder copy."""
    if not _slug:
        return {"error": "No save loaded."}
    try:
        new_slug = _library().saves.duplicate(_slug, new_title or None)
        return {"copied_from": _slug, "slug": new_slug,
                "title": _library().saves.meta(new_slug).get("title", new_slug)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def save_branch(turn_n: int) -> dict:
    """Fork the current save into a new one rewound to turn N — the engine's own
    branch: it replays the validated envelope log, so dice land the same way.
    Returns the new slug plus any warnings the engine raised."""
    if not _slug:
        return {"error": "No save loaded."}
    try:
        new_slug, warnings = _library().saves.branch(
            _slug, int(turn_n), (_cfg.rpg if _cfg else None))
        return {"slug": new_slug, "from_turn": int(turn_n),
                "warnings": list(warnings)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def undo_last() -> dict:
    """Undo the last exchange: drops the player turn and the narration, rolls
    back that turn's mechanics, re-hides what it revealed, un-consumes the event
    rules it fired. Use it when a turn came out wrong — re-narrating over a bad
    turn leaves the bad one in the transcript and in the engine's memory."""
    global _completed_turn, _pending_log_mark, _last_applied_events
    eng = _require_engine()
    before = len(_require_store().turns())
    _stage_rollback()
    result = eng.undo_last()
    # The snapshot is consumed by the restore; the next turn needs a fresh one.
    # The ledger mark goes too: the engine truncated the log under it. Same for
    # the R1 signal — the undone turn's envelope no longer applies to anything.
    _completed_turn = None
    _pending_log_mark = None
    _last_applied_events = None
    _arm_turn()
    return {"undone": result["undone"],
            "mechanics_restored": result["mechanics_restored"],
            "turns_before": before,
            "turns_after": len(_require_store().turns())}


# ── state ────────────────────────────────────────────────────────

@mcp.tool()
def get_world_state() -> dict:
    """Get the full world state: time, player location, flags, quests, RPG block
    (HP/mana/XP/inventory/companions/enemies)."""
    return _require_store().world_state()


@mcp.tool()
def opening_scene() -> dict:
    """The save's authored opening scene, already processed by the engine.

    A save can carry a verbatim first scene under a `## Opening` heading in
    premise.md (FictionLab's greeting message). Reading that file directly — as
    the skill used to — serves it RAW: the ST-20 macros ({{user}}, {{day}},
    {{clock}}, {{roll::2d6}}…) stay literal on the player's screen, and a ```rpg
    sidecar block riding an imported card goes straight to the reader. The
    engine's own opening path strips the sidecar, then expands the macros with
    the same context assemble() uses (engine.py:271-277). This returns that text.

    Returns {"has_opening": bool, "opening": str}. false means the save has no
    authored opening — open on the situation the assembled context describes.

    This writes NOTHING. Send it with ui_say, then record_turn("", <the scene>)
    like any other narration: an opening that isn't recorded is a scene the next
    session cannot read."""
    eng = _require_engine()
    store = _require_store()
    raw = store.opening_override()
    if not raw:
        return {"has_opening": False, "opening": ""}
    from coderain.sidecar import strip_sidecar
    visible, _ = strip_sidecar(raw)
    return {"has_opening": True, "opening": eng._expand_authored(visible).strip()}


@mcp.tool()
def get_event_rules() -> str:
    """Re-read the scenario event rules — the authored 'when X then Y' triggers
    that fire deterministically.

    NOT a step of the loop: assemble_context already carries this block, followed
    by the engine's own clause (engine.py:499-505), because this pipeline is
    single-brain. The old "DIRECTOR-ONLY, never expose to the Writer" wording was
    a quad-mode leftover — it describes the branch where a separate Director
    model exists (engine.py:506-519), which is not this loop. Keep this tool for
    a targeted re-read mid-session; do not make it a briefing step again, or the
    22 rules land twice and a repetition reads as emphasis.

    LEGACY/DEBUG on a save with position + partition (D-260, Issue #146): the
    loop's own turn (`assemble_context_to_file` on that same save, and
    `engine._messages()` upstream, PR #130) never calls this — it gets the
    turn's CANDIDATE verdicts only (`event_rule_verdicts_block`, lane b,
    Issue #127), never this block's full, constant 20 060 chars measured on
    the live campaign (I-158). This tool still returns the full block on
    request — a targeted re-read, not a briefing step — but on such a save
    that is a debug/audit read, not something the loop itself ever serves."""
    return _require_store().event_rules_block()


# ── validation & application ─────────────────────────────────────

@mcp.tool()
def validate_envelope(envelope: str) -> dict:
    """Validate a proposed envelope JSON against game rules.

    The envelope shape is: {"v": 1, "check": {...}, "deltas": {...}}.
    Returns {"clean": {...}, "rejected": [{"delta", "value", "reason"}]}.
    Clean is safe to pass to apply_envelope."""
    store = _require_store()
    env = json.loads(envelope) if isinstance(envelope, str) else envelope
    rpg_mod = _load_rpg()
    stats = list(rpg_mod.cfg_get(_rpg_cfg, "stats"))
    clean, rejected = validator_mod.validate(env, store, stats=stats)
    return {"clean": clean, "rejected": [dict(r) for r in rejected]}


# ── the die the player sees ──────────────────────────────────────
# Measured in the first session ever played (2026-08-04): both rolls resolved
# correctly and the player still asked whether dice had worked at all, or
# whether the scenario had blocked him. A roll he never sees carries no
# tension and gives no felt weight to a growing modifier — and it fails at its
# own job, because the die exists so that "you fail" stops being an author's
# negotiable decision. Invisible, it does that for the MJ and not for the
# player: from his seat nothing separates a missed roll from a railroad.
#
# Pushed by the BRIDGE, never as a skill step. A mandatory skill step is what
# B2 and B3 both were, and the 2026-08-03 correction brief forbids adding one.
# Hanging it on apply_envelope covers the /tour fallback too, and no path can
# forget it. Ordering is already right: the loop calls apply_envelope BEFORE
# ui_say, so the die lands before the prose — the rhythm of a real table.
#
# The engine writes (rpg.py:192):
#   check: agility vs DC14 → d20 8+1=9 FAIL (40% chance)
# The player gets it WITHOUT the odds — a percentage reads as a video game.
# SUCCESS/FAIL are left in the engine's words on purpose: this is a mechanical
# readout, and it must not drift with the language the narration happens to be
# in (see the summarizer's bilingual memory, same session).
_CHECK_ODDS = re.compile(r"\s*\(\d+% chance\)\s*$")


def _echo_checks(events: list[str]) -> list[str]:
    """Show the player every die this envelope rolled. Never raises: a die that
    fails to display must not cost the turn."""
    try:
        import webui
        if not webui.is_running():
            return events
        for e in events:
            if isinstance(e, str) and e.startswith("check: "):
                webui.say("🎲 " + _CHECK_ODDS.sub("", e[len("check: "):]),
                          "systeme")
    except Exception:
        pass
    return events


@mcp.tool()
def apply_envelope(envelope: str, rpg_on: bool = True) -> list[str]:
    """Validate and apply an envelope — mutate state.json + markdown files.

    This is THE single mutation path: dice are rolled, world state updated,
    reveals applied, events consumed, RPG mechanics resolved.
    Returns human-readable event strings (e.g. 'time -> Day 2, evening',
    'gold: +50 -> 150', 'check: strength d20+2=15 vs DC12 -> success').

    Delegates to Engine.apply_envelope, which does four things this bridge used
    to skip: it logs a canon event when something is revealed, logs one when a
    quest completes or fails, records what the turn revealed and fired so
    undo_last can put it back, and stamps the events log with the turn index
    branch replay needs."""
    global _pending_log_mark, _last_applied_events
    store = _require_store()
    env = json.loads(envelope) if isinstance(envelope, str) else envelope
    rpg_mod = _load_rpg()
    # How long the ledger is BEFORE this turn files anything — see
    # _restamp_turn_log. Taken on both paths, engine and degraded.
    #
    # Armed ONCE per turn. Re-arming on a second envelope pushes the mark past
    # the record the first envelope just wrote, and _restamp_turn_log only
    # restamps records[mark:] — so that first record keeps a stamp for a turn
    # that does not exist. Harmless while the +2 prediction holds; it is off by
    # one exactly when the turn is recorded WITHOUT a player action, i.e. the
    # opening scene (record_turn("", ...)). Measured: save_branch on the opening
    # turn then lost one of the two flags that turn had set, which the
    # pre-patch code did not lose.
    # Declared limit of arming once: if a turn applies an envelope and never
    # calls record_turn, the mark survives into the next turn, which will then
    # restamp the aborted turn's records too. The mark is cleared by
    # record_turn (via _restamp_turn_log), undo_last, retry_turn and load_save.
    if _pending_log_mark is None:
        _pending_log_mark = _event_log_len(store)

    if _engine is not None:
        # Match the engine's own convention: the log entry carries the index of
        # the NARRATOR turn this envelope belongs to — that is what branch()
        # filters on (memory.py:1891-1897). Native appends the player turn before
        # applying, so it advances by one; here record_turn appends BOTH turns
        # afterwards, so the count has to be advanced by two. It was +1, which
        # stamped the player turn: branching on that index handed the fork the
        # outcome of an action its transcript never narrated. record_turn
        # corrects the stamp once the real count is known.
        events = _echo_checks(_engine.apply_envelope(
            env, rpg_on and store.rpg_enabled(),
            log_turn=len(store.turns()) + 2))
        _last_applied_events = events    # R1 signal for paquet_narrateur
        return events

    # Degraded path — engine unavailable. Plays, but writes no canon events.
    stats = list(rpg_mod.cfg_get(_rpg_cfg, "stats"))
    clean, rejected = validator_mod.validate(env, store, stats=stats)
    events = [f"validator: dropped {r['delta']} — {r['reason']}" for r in rejected]
    events += validator_mod.apply_world(store, clean)
    deltas = clean.get("deltas") or {}
    for slug in deltas.get("reveal", []):
        e = store.set_hidden(slug, False)
        if e is not None:
            events.append(f"revealed: {e.title}")
    for slug in deltas.get("event_fired", []):
        for rule in store.event_rules(include_consumed=True):
            if rule.slug == slug:
                once = str(rule.attrs.get("once", "")).strip().lower() in (
                    "true", "yes", "1", "on")
                if once:
                    store.mark_event_consumed(slug)
                    events.append(f"event: {rule.title} fired (once — consumed)")
                else:
                    events.append(f"event: {rule.title} fired")
                break
    if rpg_on and store.rpg_enabled():
        events += rpg_mod.apply(store, clean, _rpg_cfg)
    if clean.get("check") or clean.get("deltas"):
        store.append_event_log({"turn": len(store.turns()) + 1, "env": clean})
    events.append("note: moteur degrade — aucun canon-event ecrit")
    events = _echo_checks(events)
    _last_applied_events = events        # R1 signal for paquet_narrateur
    return events


# ── dice ─────────────────────────────────────────────────────────

@mcp.tool()
def roll_check(stat: str, dc: int = 12, skill: str = "",
               actor: str = "player") -> dict:
    """Roll a d20 + stat modifier vs DC. Engine-rolled, deterministic (seed + nonce).

    The LLM NEVER rolls dice — it proposes a check, this tool resolves it.
    Returns {dc, mod, roll, total, success, win_chance}."""
    store = _require_store()
    rpg_mod = _load_rpg()
    from coderain.templates import slugify
    rpg = store.rpg_state()
    actor_slug = slugify(actor) if actor and actor not in ("player", "you") else "player"
    if actor_slug == "player":
        actor_stats = rpg.get("player", {}).get("stats", {})
    else:
        npc = next((e for e in store.entries("characters.md")
                    if e.slug == actor_slug), None)
        actor_stats = npc.stats() if npc else {}
    mod = int(actor_stats.get(stat.strip().lower(), 0))
    if skill:
        mod += rpg_mod.skill_mod(store, actor_slug, skill, _rpg_cfg)
    seed = rpg.get("seed", 0)
    nonce = rpg.get("rolls", 0) + 1
    result = rpg_mod.roll_check(mod, dc, seed, nonce)
    rpg["rolls"] = nonce
    store.set_rpg_state(rpg)
    return result


# ── memory & recall ──────────────────────────────────────────────

@mcp.tool()
def lookup_memory(query: str) -> str:
    """Search all story entries (characters, locations, factions, items, events,
    threads) by keyword. Hidden entries are masked (secrets stay safe)."""
    return _require_store().lookup(query)


@mcp.tool()
def recall_turns(reference: str) -> str:
    """Fetch verbatim past turns by timeline ref, scene slug, or range ('T6-10').
    Use when you need exact earlier dialogue/narration, not just a summary."""
    return _require_store().recall_turns(reference)


@mcp.tool()
def recall_entity(name: str) -> str:
    """Entity index: the full entry + every episode mentioning that character or
    location, with turn pointers for drill-down via recall_turns."""
    return _require_store().recall_entity(name)


@mcp.tool()
def recall_quest(name: str) -> str:
    """Quest index: thread entry + live status + every episode that touched it."""
    return _require_store().recall_quest(name)


@mcp.tool()
def record_turn(player_action: str, narration: str) -> dict:
    """Write the turn into the save's transcript. CALL THIS AT THE END OF EVERY TURN.

    Nothing else records what was played. apply_envelope advances the world state
    (HP, flags, location, quests) but never stores a word of fiction; the engine's
    own play loop is what normally calls this, and the MCP pipeline replaces that
    loop. Skip it and the save keeps a world that moved through a story nobody can
    read: assemble_context's "recent scenes" stay empty, recall_turns finds
    nothing, and a new conversation resumes with amnesia.

    An empty player_action is legal and is how an opening scene is recorded: the
    narration is a turn on its own.

    Order matters — the player's action is recorded first, then the narration.
    Returns the resulting turn count."""
    global _last_applied_events
    store = _require_store()
    pending_from = len(store.turns())
    if player_action and player_action.strip():
        store.append_turn("player", player_action.strip())
    if narration and narration.strip():
        store.append_turn("narrator", narration.strip())
    if _slug:
        try:
            _library().saves.touch(_slug)   # last-played stamp, as the CLI does
        except Exception:  # noqa: BLE001
            pass
    n = len(store.turns())
    _restamp_turn_log(store, pending_from, n)
    out = {"turns": n, "fold_due": _fold_probe(n)}
    # The turn is closed: retire its rollback material and arm the next one.
    # This is what makes the arming automatic — it rides the one gesture the
    # loop is already forbidden to skip. The R1 signal closes with it — a new
    # turn starts with no envelope applied yet, exactly like a fresh session.
    _arm_turn(retire=True)
    _last_applied_events = None
    return out


@mcp.tool()
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
    global _completed_turn, _pending_log_mark, _last_applied_events
    eng = _require_engine()
    store = _require_store()
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
    _stage_rollback()
    eng.restore_pre_turn_rpg()
    _completed_turn = None
    _pending_log_mark = None     # the engine truncated the log under the mark
    _last_applied_events = None  # the retried envelope no longer applies
    _arm_turn()          # the replayed turn needs its own snapshot
    n = len(store.turns())
    # The native loop re-probes the fold after a retry (play.py:363-365); the
    # turn count moved, so the answer can have changed.
    return {"action": action, "turns": n, "fold_due": _fold_probe(n),
            "mechanics_restored": mechanics_restored}


# ── companion side-chat — the engine's prompt, our model ─────────
# A private conversation with a companion between story turns: advice, banter,
# strategy. It is logged to memory/companion-chat.md, never the transcript — no
# turn counter, no folds — and the story only ever sees a short digest of it,
# which assemble() already injects. The engine builds a genuinely specific
# system prompt for it (who the companion is, their current mood block, the last
# six story turns clipped, the earlier private talk). That prompt is engine work
# worth having; only the reply is ours to generate.

@mcp.tool()
def companions() -> list[str]:
    """Characters a private side-chat can target: those flagged `companion: true`
    plus anyone in the state's companions block. Empty is a normal answer — it
    means no character carries the flag in this save."""
    return _require_engine().companions()


@mcp.tool()
def companion_prompt(name: str, user_text: str) -> dict:
    """Build the engine's side-chat prompt for one companion.

    Returns {"slug", "system", "user"} — speak AS that companion, following the
    system text exactly, then pass the reply to companion_log. Do not improvise
    the framing yourself: the prompt carries the companion's sheet, their current
    state, what just happened, and your earlier private talk."""
    from coderain.templates import slugify
    store = _require_store()
    slug = slugify(str(name or ""))
    comp = next((e for e in store.entries("characters.md") if e.slug == slug),
                None)
    if comp is None:
        return {"error": f"no such character: {name}",
                "candidates": _require_engine().companions()}
    cstate = store.rpg_state().get("companions", {}).get(slug, {})
    mood = ", ".join(f"{k}: {v}" for k, v in cstate.items() if v)
    story = "\n".join(f"[{t['role'].upper()}] {t['text'][:400]}"
                      for t in store.recent_turns(6))
    prior = store.companion_chat_tail(slug, lines=12)
    system = (f"You ARE {comp.title}, a companion travelling with the player in "
              "an interactive story. This is a PRIVATE conversation between "
              "story turns — speak in first person, fully in character (see "
              "your Voice). Give opinions, advice, warnings, banter; ask "
              "questions back. Do NOT narrate story events, do NOT advance the "
              "plot, do NOT speak for the player. Keep replies short and "
              "conversational (2-6 sentences).\n\n# WHO YOU ARE\n"
              + comp.render()
              + (f"\n# YOUR CURRENT STATE\n{mood}" if mood else "")
              + (f"\n\n# WHAT JUST HAPPENED IN THE STORY\n{story}" if story else "")
              + (f"\n\n# YOUR EARLIER PRIVATE TALK\n{prior}" if prior else ""))
    return {"slug": slug, "title": comp.title, "system": system,
            "user": user_text}


@mcp.tool()
def companion_log(slug: str, user_text: str, reply: str) -> dict:
    """Log one side-chat exchange where the engine keeps it: out of the
    transcript, out of the fold, out of the timeline. Skip this and the private
    conversation never happened as far as the story is concerned — the digest
    assemble() feeds back to the narrator comes from this file."""
    store = _require_store()
    store.append_companion_chat(slug, user_text, reply)
    return {"logged": True, "digest_lines": len(
        store.companion_chat_tail(slug, lines=12).splitlines())}


# ── memory fold — coderain's summarizer, LLM step lifted out ─────
# The engine folds turns into scenes and scenes into an arc, promoting durable
# facts into entries along the way. All of that logic, and its prompts, already
# exist in coderain (summarizer.py + memory-rules.md). The single piece that
# cannot run here is its one LLM call. So instead of writing a fold, the call is
# lifted out: fold_due returns the exact prompt and payload coderain would have
# sent, Claude answers it, and fold_apply hands the answer back so coderain's own
# code does the writing. Zero summarising logic lives in this file.
#
# emit_json_ex swallows Exception around llm.complete, so the signal that a call
# is needed has to be a BaseException to travel through it.

class _NeedLLM(BaseException):
    def __init__(self, system: str, payload: str):
        super().__init__("fold needs one LLM call")
        self.system, self.payload = system, payload


class _ShimLLM:
    """Stands in for coderain's LLM client. Serves prepared answers; when it runs
    out, it reports what would have been asked. No `gen` attribute, so emit_json
    leaves its parameters alone."""

    def __init__(self, answers: list[str] | None = None):
        self._answers = list(answers or [])

    def complete(self, messages: list[dict], **_kw) -> str:
        if self._answers:
            return self._answers.pop(0)
        sys_msg = next((m["content"] for m in messages
                        if m.get("role") == "system"), "")
        usr_msg = next((m["content"] for m in messages
                        if m.get("role") == "user"), "")
        raise _NeedLLM(sys_msg, usr_msg)

    def stream(self, messages, **kw):
        yield self.complete(messages, **kw)


def _run_fold(answers: list[str] | None, probe: bool) -> dict:
    eng = _require_engine()
    sm = eng.summarizer
    store = sm.store
    real_llm, real_snapshot = sm.llm, store.snapshot
    sm.llm = _ShimLLM(answers)
    if probe:
        # A probe must not consume a branch restore point.
        store.snapshot = lambda *a, **k: None
    try:
        events = sm.maybe_fold()
        return {"due": False, "events": events}
    except _NeedLLM as need:
        return {"due": True, "instruction": need.system, "payload": need.payload}
    finally:
        sm.llm = real_llm
        store.snapshot = real_snapshot


def _fold_probe(turn_count: int) -> bool:
    if _engine is None:
        return False
    try:
        return bool(_run_fold(None, probe=True).get("due"))
    except Exception:  # noqa: BLE001
        return False


@mcp.tool()
def fold_due() -> dict:
    """Is a memory fold due, and if so what does coderain want summarised?

    Returns {"due": false} when nothing is pending, otherwise
    {"due": true, "instruction": ..., "payload": ...} — coderain's own prompt and
    its own payload, verbatim. Hand both to a cheap subagent, take the JSON it
    returns, and pass it to fold_apply. Do not edit the instruction and do not
    write the summary yourself: the JSON shape it asks for is what fold_apply
    feeds back into the engine.

    Nothing is written by this call."""
    return _run_fold(None, probe=True)


@mcp.tool()
def fold_apply(summary_json: str) -> dict:
    """Feed one fold answer back to coderain, which writes the scene (or the
    arc), updates the timeline, promotes durable facts into entries, and advances
    its fold counters.

    Returns what changed plus "next": another fold is due right away (a long
    session can owe several), so keep looping fold_due -> subagent -> fold_apply
    until "next" is null."""
    eng = _require_engine()
    store = eng.summarizer.store
    before = (len(store.entries("memory/scenes.md")),
              len(store.read("memory/arc.md")))
    out = _run_fold([summary_json], probe=False)
    after = (len(store.entries("memory/scenes.md")),
             len(store.read("memory/arc.md")))
    return {
        "scenes": after[0], "scenes_added": after[0] - before[0],
        "arc_chars": after[1], "arc_changed": after[1] != before[1],
        "events": out.get("events", []),
        "next": ({"instruction": out["instruction"], "payload": out["payload"]}
                 if out.get("due") else None),
    }


# ── P4 conversion bridge — pont-MCP variant (Issue #173) ──────────
# convert_module (converter/convert.py) already takes llm_main/llm_recheck as
# injection — segmentation.segment (segmentation.py:52), buckets.classify
# (buckets.py:47) and semantic.convert_unit/convert_batch (semantic.py:198,
# :223) all reach the model through emit_json_ex(llm, ...). _ShimLLM/_NeedLLM
# (defined above for the fold) plug in unmodified: no new shim, no rewritten
# stage logic.
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

@mcp.tool()
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
    shim = _ShimLLM(answers)
    try:
        partition, report = convert_module(
            source_text, titre, list(structures), corpus_source,
            target_version, shim, Path(out_dir), llm_recheck=None)
    except _NeedLLM as need:
        return {"due": True, "step": len(answers),
                "instruction": need.system, "payload": need.payload}
    return {"due": False, "report": report,
            "nodes": len(partition.nodes), "records": len(partition.records),
            "tables": len(partition.tables), "secrets": len(partition.secrets)}


# ── proactive context assembly ───────────────────────────────────

# ── two haystacks, because one input cannot serve two opposite outputs ──
# store.assemble() derives EVERYTHING from a single haystack: the lore it
# activates (which we want maximal — the briefing is all the MJ knows for a whole
# thread) and the "Secrets you know" section (which we want minimal — a secret
# served early is a twist spent). Widening the haystack widens both. Measured on
# the live campaign: a wide haystack serves 80/89 gated visible entries instead
# of 1/89 — and 16/20 hidden entries FULL BODY instead of 0/20.
#
# So the bridge runs the SAME engine twice, on two haystacks, and keeps one
# section from each:
#   WIDE   haystack = the whole campaign memory  -> everything but the secrets
#   NARROW haystack = store.turns()[-SECRETS_WINDOW_TURNS:] + the action -> the
#                     Secrets section, and nothing else.
#
# The engine keeps the whole SELECTION: it decides twice, with its own gates,
# which entries fire. The bridge scores nothing, sorts nothing, caps nothing. It
# only chooses which haystack feeds which output, and swaps one section for the
# other by exact string — never by parsing. (Parsing on "## " lines is wrong:
# world-bible.md alone carries 8 of them and a naive split invents 37 sections.)
#
# The recomposition is not trusted: after splicing, every unauthorised hidden
# body is searched for in the flattened result. One hit — or one entry the check
# cannot verify — and the whole wide pass is dropped for the narrow one, which is
# exactly today's behaviour and provably safe. Failing closed costs lore; failing
# open costs the campaign's twists.

# ── the narrow window — AN AUTHOR'S DIAL, NOT A BRIDGE DECISION ──────
# How many past turns feed the SECRETS pass. It selects nothing else: the lore
# comes from the wide pass, and this number leaves it untouched — measured: the
# set of lore blocks served is IDENTICAL at 6, 11 and 12 on every transcript
# tested (125 blocks on the 8 mid-scene transcripts, 103 on the save as it sits
# with 0 turns played). (The `lore=N` field of the stderr line moves anyway: it
# counts every {#slug} block in the assembled text, secrets included, so it reads
# the lore count PLUS the `secrets=` figure printed beside it. That has always
# been true of that counter; it is not this dial.)
#
# It was 6. A later patch replaced the literal with `_engine.short_term` (12) on
# the claim, written into the comment above, that this made the narrow haystack
# "byte for byte what the native loop passes (engine.py:293)". That claim is
# FALSE, and measured so: engine.turn() appends the player turn FIRST and then
# takes recent_turns(short_term)[:-1] — 11 EARLIER turns plus the action. Passing
# turns[-12:] plus the action reaches one turn further back than native.
#
# What each setting costs, measured on the live campaign (20 hidden entries;
# 8 synthetic 12-turn mid-scene transcripts built from the campaign's own folded
# prose, since the save has 0 turns played — a declared proxy):
#      6 -> 5.6 secrets served on average (range 4-8)   the setting this shipped with
#     11 -> 8.2                            (range 6-10) exact parity with engine.py:293
#     12 -> 8.2                            (range 6-10) what the undeclared patch left
# 11 and 12 measure the same here because the 12th turn back is a player line in
# an alternating transcript; on a transcript with long player turns they could
# part. A wider window spends twists earlier — a secret served is a secret the MJ
# can foreshadow, and one it can no longer let the player discover cold.
#
# Restored to 6 because 6 is what the author last chose. 11 and 12 are one named
# argument away (`secrets_window=`). THE CHOICE IS NOT THIS FILE'S TO MAKE.
SECRETS_WINDOW_TURNS = 6

_SECRETS_TITLE = ("Secrets you know (NOT yet revealed to the player — "
                  "foreshadow, hint, let them discover; never state outright)")
_ENFORCE_CLAUSE = ("\n\n(Enforce these silently; NEVER reveal an unfired rule "
                   "in prose.)")
_H2_IN_BODY = re.compile(r"(?m)^##(?=\s)")


def _secrets_segment(hits: list) -> str:
    """The Secrets section as memory.py emits it, byte for byte: the section is
    built at memory.py:1373-1377 and wrapped by the salience loop at
    memory.py:1437 as f"## {title}\\n{body}". Rendering goes through the engine's
    own Entry.render, never a copy of it."""
    return "## " + _SECRETS_TITLE + "\n" + "\n\n".join(e.render() for e in hits)


def _hidden_entries(store) -> list:
    """Hidden entries in the engine's own iteration order (memory.py:1305-1306),
    so a sub-list of them matches the order of the section it built."""
    return [e for rel in store.gated_registries()
            for e in store.entries(rel) if e.hidden()]


# ── measuring exposure, and the two things it must not confuse ───
# The first detector tested ONE window of the body, body[20:80] — 10.8% of a
# typical entry, at a fixed offset. Two ways that is wrong, both measured:
#
#   too narrow — a body served with its opening cut, or served in pieces, passes.
#   too brittle — the nearest author echo in this campaign starts at offset 83,
#     THREE characters past the end of that window. Had it landed inside, the
#     guard would have tripped on every single context, for ever, and the bridge
#     would serve 24 lore blocks instead of 103 with nobody the wiser. The
#     carrier is world-bible.md, which is served in every context.
#
# So the whole body is probed — 48-char windows every 12 chars, end included —
# and the result is a COVERAGE, which separates the two cases the guard must not
# confuse. Measured on the live campaign (20 hidden entries):
#     the body served as a block (wide pass, guard bypassed) -> coverage 1.000
#         on all 16 entries that fire, min 1.000
#     a fragment of the body echoed in AUTHOR material (the shipped context)
#         -> coverage 0.000 to 0.091, max 0.091 over 20 entries; the largest
#         echo anywhere measured, block or not, is 0.179
# 0.179 to 1.000 is the gap; the threshold sits at 0.50, with a factor ~2.8 of
# margin on the echo side and 2.0 on the leak side.
#
# A block hit is exact and needs no threshold: the entry's own render(), which is
# how the engine emits it, found verbatim in the output. Coverage is what catches
# a body served truncated, which the block test alone would miss.
_PROBE_WIN = 48
_PROBE_STRIDE = 12
_LEAK_COVERAGE = 0.50


def _body_probes(entry) -> list[str]:
    """Windows over the WHOLE body, as render() emits it (render demotes a
    leading '## ' to '### ', memory.py:299), whitespace-flattened.

    Two kinds are dropped: a window carrying a {{macro}}, because ST-20
    (memory.py:1450) expands macros over the joined context and the window is
    then not the same string in the output as on disk; and a window not found in
    the entry's OWN render, which the detector would be blind to. Measured on the
    live campaign: 0 hidden entries lose all their windows this way (the smallest
    body still yields 8)."""
    body = " ".join(_H2_IN_BODY.sub("###", entry.body.strip()).split())
    if len(body) < _PROBE_WIN:
        return []
    own = " ".join(entry.render().split())
    last = len(body) - _PROBE_WIN
    pos = list(range(0, last + 1, _PROBE_STRIDE))
    if pos[-1] != last:
        pos.append(last)            # the tail of the body is probed too
    return [w for w in (body[p:p + _PROBE_WIN] for p in pos)
            if "{{" not in w and "}}" not in w and w in own]


def _hidden_exposure(text: str, hidden: list, allowed: set):
    """(leaks, echoes) for every hidden entry that is NOT authorised.

    leak  = (slug, kind, coverage) — the body is SERVED: kind "block" (its render
            found verbatim), "partial" (coverage past the threshold), or
            "unverifiable" (no probe survived and no block hit — the check cannot
            decide, which counts as a failure, as it did before).
    echo  = (slug, coverage) — a fragment appears, far below the threshold. That
            is an author who wrote the same words twice, in material they chose to
            make visible. It is reported and NOTHING is degraded: dropping the
            wide pass would not remove one character of it."""
    flat = " ".join(text.split())
    leaks, echoes = [], []
    for e in hidden:
        if e.slug in allowed:
            continue
        if " ".join(e.render().split()) in flat:
            leaks.append((e.slug, "block", 1.0))
            continue
        probes = _body_probes(e)
        if not probes:
            leaks.append((e.slug, "unverifiable", -1.0))
            continue
        cov = sum(1 for w in probes if w in flat) / float(len(probes))
        if cov >= _LEAK_COVERAGE:
            leaks.append((e.slug, "partial", cov))
        elif cov > 0:
            echoes.append((e.slug, cov))
    return leaks, echoes


def _fmt_leaks(rows) -> str:
    return ", ".join(f"{s}({k})" if c < 0 else f"{s}({k} {c:.2f})"
                     for s, k, c in rows)


def _fmt_echoes(rows) -> str:
    return ", ".join(f"{s}({c:.2f})" for s, c in rows)


def _splice_secrets(text: str, old_hits: list, new_hits: list):
    """Swap the Secrets section of `text` for the one `new_hits` renders.
    Returns (text, located). located=False means the section was not found
    EXACTLY once — the caller must fall back rather than ship an unproven text."""
    if not old_hits:
        if not new_hits:
            return text, True
        # `triggers_not` could in theory suppress a secret on the wide haystack
        # and not on the narrow one. 0 entries carry it today; handled anyway.
        return text + "\n\n" + _secrets_segment(new_hits), True
    old = _secrets_segment(old_hits)
    if text.count(old) != 1:
        return text, False
    if new_hits:
        return text.replace(old, _secrets_segment(new_hits), 1), True
    if text.count("\n\n" + old) == 1:
        return text.replace("\n\n" + old, "", 1), True
    return text.replace(old, "", 1), True


# ── R2, `paquet_narrateur`'s literal leak guard (Issue #192, D-269) ──
# The Director's OWN text (`directive_director`) is the one thing this tool
# does not compose itself — it is typed by an agent that has already read the
# hidden entries and the event rules to decide the beat. R2 is the filet that
# catches what that agent should not have TYPED into a channel the narrator
# reads: a slug it named, or a fragment of the withheld body/rule text
# itself. Paraphrase (the Director describing the SAME twist in its own
# words) is explicitly out of scope (spec: "hors périmètre du filet — gabarit
# et fumée") — this is a literal-string net, not a meaning classifier.
def _slug_named(slug: str, flat_lower: str) -> bool:
    """A bare slug token in the text — word-boundary, not a substring hit
    (a slug like `porte` must not fire on `porteur`)."""
    return bool(re.search(r"(?<![\w-])" + re.escape(slug.lower()) + r"(?![\w-])",
                          flat_lower))


def _content_leak(entry, flat: str) -> bool:
    """Same two tests as `_hidden_exposure`'s per-entry check (block render,
    or probe coverage past `_LEAK_COVERAGE`), reused standalone: R2 scans one
    short text (the directive) against one entry at a time, not a whole
    assembled context against an authorised set."""
    if " ".join(entry.render().split()) in flat:
        return True
    probes = _body_probes(entry)
    if not probes:
        return False
    cov = sum(1 for w in probes if w in flat) / float(len(probes))
    return cov >= _LEAK_COVERAGE


def _r2_scan(store, directive: str) -> str:
    """Returns the name of the guard that fired (safe to put in a refusal —
    the Director already knows the coulisses, R2's own contract), or "" when
    the directive is clean. Three refusals, one scan: an unrevealed hidden
    entry (slug or body fragment), an event rule (fired or not — its slug or
    text is director-only material regardless), or a hidden entry's content
    reached through the same body-fragment test (the "secret non déclenché"
    case, D-019: a secret is a hidden character/faction entry, no separate
    registry to scan)."""
    flat = " ".join(str(directive or "").split())
    if not flat:
        return ""
    low = flat.lower()
    for e in _hidden_entries(store):
        if _slug_named(e.slug, low) or _content_leak(e, flat):
            return f"entrée cachée non révélée ({e.slug})"
    for rule in store.event_rules(include_consumed=True):
        if _slug_named(rule.slug, low) or _content_leak(rule, flat):
            return f"règle d'événement ({rule.slug})"
    return ""


def _wide_history(store) -> list[dict]:
    """The activation haystack for the lore pass: the campaign's own memory —
    every folded scene, the arc, and the unresolved threads — in front of the
    transcript.

    Not a cost: assemble() returns a system message plus one chat message per
    turn (memory.py:1458-1463) and this bridge keeps only the system ones, so a
    wider `history` adds nothing to the output. It is a pure activation key. Its
    only price is CPU (trigger_hit scans it per trigger token) — watch the ms in
    the stderr line; past ~1 s this needs revisiting."""
    parts = [e.render().strip() for e in store.entries("memory/scenes.md")]
    arc = store.read("memory/arc.md").strip()
    if arc:
        parts.append(arc)
    parts += [e.render().strip() for e in store.entries("threads.md")
              if e.attrs.get("status", "open").lower() != "resolved"]
    primer = "\n\n".join(p for p in parts if p)
    turns = list(store.turns())
    return ([{"role": "narrator", "text": primer}] + turns) if primer else turns


def _partition_dir(store) -> Path | None:
    """D-260 (Issue #146) : même résolution que `Engine._partition_dir()`
    (engine.py) — dupliquée ici plutôt qu'importée parce que le pont tourne
    parfois sans Engine chargé (`_engine is None`, voir les tests qui posent
    `mcp_server._engine = None` à la main) et cette lecture du pointeur
    save->partition n'a aucune dépendance sur l'Engine lui-même."""
    p = store.dir / "module.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    partition = data.get("partition")
    return Path(partition) if partition else None


def _position_context_text(store, partition_dir: Path, state: dict,
                           history: list[dict], player_action: str,
                           recent_turns: int, event_rules: bool,
                           secrets: bool, role_section: bool = True
                           ) -> tuple[str, dict]:
    """D-260 (Issue #146) : le chemin par position pour
    `assemble_context_to_file` — même sélection que `engine._messages()`
    (`assembleur_position`, PR #130), jamais l'ancien assemblage par
    mots-clés + budget. `secrets`/`event_rules` gardent EXACTEMENT le même
    sens que sur l'ancien chemin (voir le docstring d'`assemble_context_to_file`) :
    narrateur-seul par défaut, les deux blocs réservés au Director (secrets,
    règles d'événement) restent absents sauf demande explicite.

    `role_section` (Issue #198, point 3) : la section « Rôle (Director) »
    (`DIRECTOR_SYS`) que `build_sections` préfixe systématiquement décrit LE
    DIRECTOR, pas son lecteur — vrai pour `assemble_context_to_file` (le
    Director se briefe lui-même, défaut `True`), faux pour `paquet_narrateur`
    qui réutilise ce même chemin pour composer le paquet du NARRATEUR : ce
    dernier appelle avec `role_section=False` pour ne pas lui servir un
    prompt de rôle qui ne le décrit pas.

    `budget_tokens`/`wide_lore`/`max_secrets`/`secrets_window`/`lore_include`
    n'ont pas cours ici : la sélection par position n'a ni budget ni passe
    large/étroite, elle est déterministe (node courant + records ancrés) —
    même divergence assumée que `engine._messages()` sur le chemin position."""
    location = str(state.get("location", ""))
    sections = assembleur_position.build_sections(
        partition_dir, store, location, history, player_action,
        secrets=secrets, role_section=role_section)
    text = "\n\n".join(s.render() for s in sections if s.render())
    # Verdicts du tour (lane b, #127) — jamais event_rules_block() entier.
    # `event_rules` garde le même sens que sur l'ancien chemin : False par
    # défaut sur assemble_context_to_file (narrateur-seul), True réservé à
    # un appelant qui joue aussi le rôle du Director.
    if event_rules:
        ev_block = store.event_rule_verdicts_block(history, player_action)
        if ev_block:
            text += "\n\n" + ev_block
    if recent_turns > 0 and history:
        lines = []
        for t in history[-recent_turns:]:
            who = "JOUEUR" if t["role"] == "player" else "MJ"
            lines.append(f"### {who}\n{t['text'].strip()}")
        text += ("\n\n# DERNIERS TOURS (verbatim — la scène où l'on reprend)\n\n"
                 + "\n\n".join(lines))
    hidden = _hidden_entries(store)
    allowed = [e for e in hidden if secrets and e.render() in text]
    served = len(set(re.findall(r"\{#([^}]+)\}", text)))
    print("assemble(position): final=%d chars, lore=%d blocks, secrets=%d/%d, "
         "turns=%d" % (len(text), served, len(allowed), len(hidden),
                       recent_turns), file=sys.stderr)
    return text, {"degraded": False, "reason": "position", "lore_blocks": served,
                 "secrets": len(allowed), "secrets_suppressed": not secrets,
                 "hidden_total": len(hidden), "echoes": 0,
                 "secrets_window": None, "lore_selected": None}


def _finalize(messages, store, history, recent_turns: int,
              event_rules: bool) -> str:
    """Everything the bridge concatenates AFTER the engine's assemble: the two
    engine augmenters, the scenario event rules, the verbatim tail.

    It is a separate function because the guard has to run on the FINAL text, and
    the guard's fallback has to be able to build its own. Note what that split
    also proves: NONE of what is added here depends on which haystack fed the
    lore, so it is identical on both paths — which is exactly why a hidden body
    found in this material cannot be cured by falling back (see _assemble_text)."""
    if _engine is not None:
        # The engine's own two augmenters, which the bridge never called. The
        # first carries rpg-rules.md + the live sheet (the mechanical block the
        # native narrator gets every turn — until now the MJ had only
        # get_world_state's raw JSON); the second carries response_length and,
        # above all, the save's custom-instructions.md, the player's per-campaign
        # style directives, which reached nobody.
        #
        # trinity is swapped for a sentinel across _augment_rpg only: it selects
        # prompt_narrate=False, the variant for a pipeline that resolves the
        # mechanics BEFORE the narrator writes — which is exactly this loop's
        # order (apply_envelope, then ui_say). Left alone, the sheet would end
        # with "Narrate this result now" about a check narrated a turn ago.
        prev = _engine.trinity
        _engine.trinity = _RESOLVED_BEFORE_NARRATION
        try:
            messages = _engine._augment_rpg(messages)
        finally:
            _engine.trinity = prev
        # Same rite, one step further: the author's note fires only when
        # exchange % every == 0 (engine.py:198-200), where `exchange` counts
        # narrator turns. That frequency is meaningful in a loop that assembles
        # EVERY turn; here we assemble once per thread, so `every N` degenerates
        # into a lottery — the campaign's style directives make it into the
        # briefing, or not, depending on the parity of the turn counter at the
        # moment of resuming. Forced to 1 for this call only; the author's chosen
        # depth (system | tail) is left untouched.
        #
        # Restored by REMOVING the instance attribute, not by writing the bound
        # method back into it: `_authors_note_cfg` is a class method, and putting
        # engine._authors_note_cfg back as an instance attribute leaves the
        # instance holding a bound method that holds the instance — a reference
        # cycle that never goes away, planted once per assemble.
        had = "_authors_note_cfg" in _engine.__dict__
        prev_attr = _engine.__dict__.get("_authors_note_cfg")
        depth = _engine._authors_note_cfg()[0]
        _engine._authors_note_cfg = lambda: (depth, 1)
        try:
            messages = _engine._augment_style(messages)
        finally:
            if had:
                _engine.__dict__["_authors_note_cfg"] = prev_attr
            else:
                _engine.__dict__.pop("_authors_note_cfg", None)
    text = messages[0]["content"]
    # An author's note placed at `tail` depth rides its own system message
    # (engine.py:210-212). Returning messages[0] alone would drop it.
    for m in messages[1:]:
        if m.get("role") == "system":
            text += "\n\n" + m["content"]
    # Scenario event rules, and the engine's own clause after them
    # (engine.py:499-505). That branch is `if self.trinity is None` — single
    # brain: the one model IS the logic agent, so it gets the rules; in quad mode
    # only the Director sees them. This loop is single-brain (the same Claude
    # builds the envelope and writes the prose), and load_save pins trinity to
    # None, so the native equivalent of our architecture puts them here. It
    # changes no exposure — the skills already handed them to the MJ by hand —
    # it just moves them onto a gesture the loop makes anyway, instead of a step
    # a resumed session can skip. If a Director ever becomes a separate model,
    # this condition turns itself off, exactly as upstream intends.
    #
    # `event_rules` is the caller's declaration of WHICH architecture it is, and
    # it is not a switch anyone has to remember: each tool's default is right for
    # its only caller. assemble_context serves the single-brain loop (/jouer,
    # /tour) -> True. assemble_context_to_file serves the blind-montage Director
    # (.claude/agents/director.md), whose Writer READS the file -> False, because
    # there the rules belong to the Director alone, which reads them itself.
    if event_rules and (_engine is None or _engine.trinity is None):
        rules = store.event_rules_block()
        if rules:
            text += "\n\n" + rules + _ENFORCE_CLAUSE
    if recent_turns > 0 and history:
        lines = []
        for t in history[-recent_turns:]:
            who = "JOUEUR" if t["role"] == "player" else "MJ"
            lines.append(f"### {who}\n{t['text'].strip()}")
        text += ("\n\n# DERNIERS TOURS (verbatim — la scène où l'on reprend)\n\n"
                 + "\n\n".join(lines))
    return text


# What a degraded context says about itself, in the returned VALUE. The stderr
# line below is the author's channel and carries names; this one is read by the
# MJ and can end up on a screen the player sees, so it counts and never names.
_DEGRADED_BANNER = (
    "# ⚠ CONTEXTE DÉGRADÉ — la garde des secrets s'est déclenchée\n"
    "La passe large a été abandonnée : ce briefing porte le lore de la scène "
    "courante seulement, pas celui de toute la campagne. Ce n'est pas une "
    "campagne pauvre, c'est une garde qui a fermé. Joue avec ce que tu as, "
    "appuie-toi sur `recall_entity` / `lookup_memory` quand un nom te manque, "
    "et signale-le au joueur en fin de session (l'auteur a un détail sur la "
    "sortie d'erreur du serveur).\n")


def _assemble_text(player_action: str, budget_tokens: int,
                   recent_turns: int | None = None, max_secrets: int = 0,
                   wide_lore: bool = True, event_rules: bool = True,
                   secrets_window: int = SECRETS_WINDOW_TURNS,
                   secrets: bool = True, lore_include: set[str] | None = None):
    """Returns (text, info). info carries the guard's verdict — see the tools."""
    t0 = time.perf_counter()
    store = _require_store()
    history = store.turns()
    short = _engine.short_term if _engine is not None else 12
    if recent_turns is None:
        recent_turns = short
    # All folded scenes, not the engine's default 4 (memory.py:1212). At 7 scenes
    # this is a wash (-49 chars); at 30 it is the difference between the whole
    # chronology and 4 recent scenes + at most 4 guessed by the "Related past
    # scenes" heuristic, which memory.py:1396 caps at 4 and which switches itself
    # off once the tail covers everything.
    tail = max(1, len(store.entries("memory/scenes.md")))

    win = secrets_window
    hist_narrow = history[-win:] if win > 0 else list(history)
    narrow_msgs = store.assemble(hist_narrow, player_action,
                                 scenes_tail=tail, budget_tokens=budget_tokens,
                                 lore_include=lore_include)
    if not narrow_msgs:
        return "", {"degraded": False, "reason": "empty assemble"}
    narrow = narrow_msgs[0]["content"]

    hidden = _hidden_entries(store)
    hits_n = [e for e in hidden if e.render() in narrow]
    # §13-A of the spec, left to the human: the engine never scores hidden
    # entries (memory.py:1313-1315 `continue`s before any scoring), so a cap has
    # no engine-given order to cut on. 0 = no cap = the engine's own envelope.
    #
    # `secrets=False` is NOT max_secrets pushed to zero — 0 already means "no
    # cap" on that dial, and there is no number that means "none". It empties
    # the authorised set, which is the ONE lever the rest of this function reads:
    #   - _splice_secrets(text, hits, []) DELETES the section on both haystacks
    #     (the `if new_hits:` branch at _splice_secrets, lines 1115-1119);
    #   - allowed_slugs then being empty, _hidden_exposure treats EVERY hidden
    #     body as unauthorised, so the guard that already protects unfired
    #     twists now protects all of them, with no second mechanism to trust.
    # Nothing else in this file needs to know about the mode. Upstream has no
    # equivalent: memory.py:1373-1377 emits that section unconditionally, so
    # this is a declared divergence from the engine, not a bug fixed.
    if not secrets:
        allowed = []
    elif max_secrets > 0:
        allowed = hits_n[:max_secrets]
    else:
        allowed = hits_n
    allowed_slugs = {e.slug for e in allowed}

    # The fallback, built once and kept ready: the narrow text with the same cap
    # applied, so an explicit max_secrets still holds when the wide pass is
    # dropped. A no-op when max_secrets is 0.
    capped, located_n = _splice_secrets(narrow, hits_n, allowed)
    narrow_msgs_final = ([{**narrow_msgs[0], "content": capped}, *narrow_msgs[1:]]
                         if located_n else narrow_msgs)
    narrow_final = capped if located_n else narrow
    _fallback = {}

    def fallback_text():
        if "t" not in _fallback:
            _fallback["t"] = _finalize(narrow_msgs_final, store, history,
                                       recent_turns, event_rules)
        return _fallback["t"]

    # `note` names names and goes to stderr — the machine room, the author's
    # channel. `public` is the same verdict with the names taken out, and it is
    # the one that travels in the tool's return value: a caller may print it, and
    # a guard that spells out sixteen secrets to prove it protected them has
    # protected nothing (this is R4's lesson, applied here before it bit).
    text, final, wide_chars = None, narrow_final, 0
    note, public, degraded, echoes = "narrow-only", "narrow-only", False, []
    if wide_lore:
        wide_msgs = store.assemble(_wide_history(store), player_action,
                                   scenes_tail=tail, budget_tokens=budget_tokens,
                                   lore_include=lore_include)
        wide = wide_msgs[0]["content"] if wide_msgs else ""
        wide_chars = len(wide)
        if wide:
            hits_w = [e for e in hidden if e.render() in wide]
            spliced, located = _splice_secrets(wide, hits_w, allowed)
            if not located:
                note = public = "secrets section not located exactly once"
                degraded = True
            else:
                cand_msgs = [{**wide_msgs[0], "content": spliced}, *wide_msgs[1:]]
                cand = _finalize(cand_msgs, store, history, recent_turns,
                                 event_rules)
                # THE WHOLE OUTPUT is checked, not the assembled prefix. What used
                # to escape: the rpg block, the style directives, the event-rules
                # block and the verbatim turns — 15 to 27 kchars appended after
                # the old check point, one of which measurably carries a fragment
                # of a hidden body.
                leaks, echoes = _hidden_exposure(cand, hidden, allowed_slugs)
                if not leaks:
                    text, final, note, public = cand, spliced, "spliced", "spliced"
                else:
                    # Fail closed ONLY where failing closed cures something. The
                    # fallback shares its whole tail with the wide pass, so a
                    # hidden body found in that tail is in both texts: degrading
                    # would cost 79 lore blocks and remove not one character of
                    # the exposure. That is the shape of an author who wrote the
                    # same sentence in a hidden entry and in visible material —
                    # it must be SAID, loudly, and not silently paid for.
                    leaks_n, echoes_n = _hidden_exposure(
                        fallback_text(), hidden, allowed_slugs)
                    incurable = {s for s, _k, _c in leaks_n}
                    curable = [r for r in leaks if r[0] not in incurable]
                    if curable:
                        note = "guard tripped: " + _fmt_leaks(curable)
                        public = (f"guard tripped: {len(curable)} hidden "
                                  "entry/entries were served by the wide pass "
                                  "and are not in the fallback; names on the "
                                  "server's stderr")
                        degraded, echoes = True, echoes_n
                    else:
                        text, final, echoes = cand, spliced, echoes
                        note = ("guard: hidden body present on BOTH paths "
                                "(author duplication — degrading would not "
                                "remove it): " + _fmt_leaks(leaks))
                        public = (f"guard: {len(leaks)} hidden body/bodies "
                                  "present on BOTH paths (author duplication) "
                                  "— NOT degraded, degrading would not remove "
                                  "it; names on the server's stderr")
    if text is None:
        text = fallback_text()
        if not degraded:
            _, echoes = _hidden_exposure(text, hidden, allowed_slugs)
    if degraded:
        print(f"assemble: FAIL-CLOSED on the wide pass ({note}); serving the "
              "narrow context — lore is degraded, secrets are not.",
              file=sys.stderr)
        text = _DEGRADED_BANNER + "\n" + text
    if echoes:
        print("assemble: hidden-body ECHO in author-visible material (no "
              "degradation, the fallback carries it too): " + _fmt_echoes(echoes),
              file=sys.stderr)
    # One line per assemble, on stderr (stdout is the MCP channel). This — not a
    # budget ceiling — is what makes a drift visible: a lore count that collapses,
    # a char count that runs away, a haystack scan that crosses a second.
    served = len(set(re.findall(r"\{#([^}]+)\}", final)))
    print("assemble: wide=%d narrow=%d final=%d chars, lore=%d blocks, "
          "secrets=%d/%d, window=%d, turns=%d, %s, %d ms"
          % (wide_chars, len(narrow), len(text), served, len(allowed),
             len(hidden), win, recent_turns, note,
             (time.perf_counter() - t0) * 1000), file=sys.stderr)
    # `secrets_suppressed` exists because `secrets: 0` is ambiguous to a blind
    # caller: it reads the same whether no twist happened to fire or the mode
    # forbade all of them. The Director cannot open the file to tell.
    return text, {"degraded": degraded, "reason": public,
                  "lore_blocks": served, "secrets": len(allowed),
                  "secrets_suppressed": not secrets,
                  "hidden_total": len(hidden), "echoes": len(echoes),
                  "secrets_window": win,
                  "lore_selected": (len(lore_include)
                                    if lore_include is not None else None)}



@mcp.tool()
def assemble_context(player_action: str, budget_tokens: int = 120000,
                     recent_turns: int | None = None, max_secrets: int = 0,
                     wide_lore: bool = True, event_rules: bool = True,
                     secrets_window: int = SECRETS_WINDOW_TURNS,
                     secrets: bool = True,
                     lore_include: list[str] | None = None) -> str:
    """Build the full Writer context from memory + lorebook activation.

    This is the PROACTIVE memory system: given the player's action, it activates
    lorebook entries by keyword match, layers memory tiers (recent scenes, arc,
    timeline, facts), and assembles everything within a token budget. It also
    carries the RPG block, the campaign's style directives and the scenario event
    rules, so this ONE call is the whole briefing — there is no second step to
    remember.

    Returns the system prompt content the Writer should receive. Hidden entries
    appear as 'Secrets you know (foreshadow, never state outright)', and they are
    selected on the NARROW haystack only — the current scene — while the lore is
    selected on the whole campaign memory. See _assemble_text.

    If the secrets guard ever has to drop the wide pass, the returned text OPENS
    with a '⚠ CONTEXTE DÉGRADÉ' banner saying so. Without it, a MJ amputated of
    ~77% of its lore reads a thin campaign and blames the campaign.

    What this costs is the ENTRY PRICE OF A THREAD, paid once, not a per-turn
    cost: a thread is relaunched several times an evening and each time this
    briefing is all the MJ knows. Measured on the live campaign: ~162 000 chars,
    ~40 500 tokens, about a tenth of a usable thread.

    budget_tokens is a CEILING, not an allocation. Measured: the output is
    identical byte for byte from 45 000 up to 400 000 (147 509 chars), so a
    larger number costs nothing today and buys ~2.3x the current lore material
    before the budget starts evicting entries again. At the previous default
    (30 000) it already evicted 35 of the 80 reachable entries. Lower it only
    with a measured reason — and know that it rations, it does not guard: the
    guard is the stderr line this call prints.

    recent_turns appends the last N turns VERBATIM under a final heading. None
    (default) = the engine's own short_term_turns (12), which is the window the
    engine considers NOT YET FOLDED: serving fewer opens a gap between the last
    fold and the verbatim window, i.e. fiction that lives nowhere. 0 opts out.

    max_secrets caps the Secrets section (0 = no cap = the engine's own
    envelope, which serves 2 to 7 secrets on a mid-scene resume). LEFT AT 0 ON
    PURPOSE: the engine never ranks hidden entries, so any cap would have to
    invent an order here — a human call, not a bridge's.

    wide_lore=False falls back to the engine's native haystack, i.e. a MJ who
    only knows what the current scene names. Also a human call: breadth vs.
    focus. Default True — on a resume the native haystack is empty and serves
    1 lore entry out of 89.

    secrets_window is HOW MANY PAST TURNS feed the secrets pass, and it is the
    one dial in here that spends the campaign's twists. It touches the lore not
    at all (103 blocks at any setting). Measured on the live campaign, mid-scene:
        6  -> 5.6 of the 20 secrets served on average — the default, and the
              setting this bridge shipped with before an undeclared patch
        11 -> 8.2 — exact parity with the native loop (engine.py:293 appends the
              player turn, then takes recent_turns(short_term)[:-1] = 11 earlier
              turns + the action)
        12 -> 8.2 — one turn further back than native; what that patch left here
    THE VALUE IS THE AUTHOR'S CALL, not this file's. See SECRETS_WINDOW_TURNS.

    event_rules defaults True because THIS tool serves the single-brain loop,
    where the model that decides is the model that narrates (engine.py:496-498).
    Pass False only from a pipeline with a separate Director.

    secrets defaults True for the same reason: the reader of this text is also
    the one deciding, and a decider stripped of the campaign's unfired twists
    plans against a world it cannot see. False drops the Secrets section
    entirely — see assemble_context_to_file, which is where that belongs.

    lore_include is the CAMERA'S TRANCHE (the selection stage): the slugs the
    Director judged to serve THIS scene. None (default) = no tranche, the
    activation decides alone — the pre-camera behavior. A list restricts the
    served lore to those slugs (forced entries — pinned/critical — stay in:
    that contract is the author's, not the camera's). Call context_candidates
    first: it reports what the activation WOULD serve, at no LLM cost."""
    text, _info = _assemble_text(player_action, budget_tokens, recent_turns,
                                 max_secrets, wide_lore, event_rules,
                                 secrets_window, secrets,
                                 lore_include=(set(lore_include)
                                               if lore_include is not None
                                               else None))
    return text


@mcp.tool()
def assemble_context_to_file(player_action: str, budget_tokens: int = 120000,
                             recent_turns: int | None = None,
                             max_secrets: int = 0, wide_lore: bool = True,
                             event_rules: bool = False,
                             secrets_window: int = SECRETS_WINDOW_TURNS,
                             secrets: bool = False,
                             lore_include: list[str] | None = None) -> dict:
    """Same as assemble_context, but WRITES the context to a file and returns
    only {path, chars, degraded, ...} — the text itself never enters the calling
    agent's context window.

    `degraded: true` means the secrets guard dropped the wide pass and the file
    carries the current scene's lore only. The caller sees it here BECAUSE it
    cannot see the text: a silent degradation on this path is a Director planning
    a scene against a campaign it was never shown. `lore_blocks`, `secrets` and
    `echoes` are the same counters the stderr line prints.

    Use this in a blind-orchestration pipeline: a cheap planner calls this and
    hands the path to the narrator, which reads the file. The assembled context
    is then loaded exactly once, by the only agent that needs it, instead of
    once per agent in the chain.

    ── WHAT THIS FILE IS: A NARRATOR'S BRIEFING, NOT A DIRECTOR'S ──
    Both defaults below are False, and they are the SAME decision made twice:
    the only agent that ever opens this file is the one that writes prose. The
    Director is not deprived of anything — it holds get_event_rules, recall_*
    and the world state, and it never reads this path (its own procedure forbids
    it). Two blocks, and only two, are withheld here; the rules of play, the
    style directives, the mechanical block, the world, the open threads, the
    arc, the established facts, the recent scenes and the timeline all stay.

    event_rules defaults FALSE. A separate Director is exactly the case where
    the engine keeps the event rules to itself (engine.py:496-505, "in quad mode
    only the Director sees them"), and the bridge's own copy of that block
    (_finalize) is a bridge addition with no upstream equivalent on this path.

    secrets defaults FALSE, and this one IS a declared divergence from upstream:
    memory.py:1373-1377 emits 'Secrets you know' with no test of mode at all, so
    the native Writer does see the twists. Here it does not — a narrator receives
    the character's perception, not the world's contents. Setting it False does
    not merely delete the section: it empties the authorised set, so the secrets
    guard (see _hidden_exposure) then treats every hidden body as a leak
    anywhere in the text, section or not. Pass True only if the agent reading
    this file is also the one deciding — and know that it then reads twists it
    is expected not to spend.

    `secrets_suppressed` in the return says which of the two it was: `secrets: 0`
    alone cannot distinguish "no twist fired" from "the mode forbade them".

    Measured on two saves, with every hidden entry forced to fire (the action was
    built from their own triggers, the worst case this can produce):
        20 hidden served -> the section is 14 951 chars, 20 lore blocks, 21 '## '
            headings; the rest of the context is byte-for-byte identical
         1 hidden served ->    565 chars,  1 lore block,  2 headings; same
    The event-rules block, on the save that carries one, is 20 060 chars + a
    66-char clause. Removing either leaves the other and everything else
    untouched — verified as string equality, not as a count.

    secrets_window: see assemble_context — same dial, same default, same warning
    that its value belongs to the author. It still selects which twists WOULD
    have been authorised, so it still governs what the guard lets through.

    The file is overwritten every turn and lives outside any save folder.

    lore_include: the CAMERA'S TRANCHE — see assemble_context. The Director
    calls context_candidates first (the documentaliste's report), then names
    here the slugs that serve THIS scene. None keeps the blind montage.

    ── D-260 (Issue #146): la bascule par position ──
    Save AVEC position + partition projetée (`assembleur_position.eligible()`,
    même frontière que `engine._messages()`, PR #130) : ce chemin sert le
    MÊME paquet keyé position que le corps single-brain, jamais l'ancien
    assemblage par mots-clés + budget. `budget_tokens`/`wide_lore`/
    `max_secrets`/`secrets_window`/`lore_include` n'ont pas cours sur ce
    chemin (sélection déterministe, pas de haystack) — voir
    `_position_context_text`. `event_rules`/`secrets` gardent EXACTEMENT le
    même sens : les verdicts du tour (jamais `event_rules_block()` entier)
    et la sous-section Secrets restent absents par défaut. Toute save SANS
    position/partition retombe sur `_assemble_text`, inchangé octet pour
    octet (cohabitation, épic #124)."""
    store = _require_store()
    state = store.world_state()
    pdir = _partition_dir(store)
    if pdir is not None and assembleur_position.eligible(store, state):
        if recent_turns is None:
            recent_turns = _engine.short_term if _engine is not None else 12
        history = store.turns()
        text, info = _position_context_text(
            store, pdir, state, history, player_action, recent_turns,
            event_rules, secrets)
    else:
        text, info = _assemble_text(player_action, budget_tokens, recent_turns,
                                    max_secrets, wide_lore, event_rules,
                                    secrets_window, secrets,
                                    lore_include=(set(lore_include)
                                                  if lore_include is not None
                                                  else None))
    out_dir = ROOT / ".turn"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "context.md"
    out.write_text(text, encoding="utf-8")
    return {"path": str(out), "chars": len(text), **info}


@mcp.tool()
def paquet_narrateur(directive_director: str, action_joueur: str,
                     sans_mecanique: bool = False) -> dict:
    """Issue #192 (D-269) — LE péage du tour : l'unique canal vers le
    narrateur. Le Director l'appelle après résolution mécanique du tour ;
    l'outil compose le paquet, l'écrit dans un FICHIER, et ne retourne au
    Director que le chemin + des métadonnées — le contenu n'entre jamais
    dans SA fenêtre (même patron qu'`assemble_context_to_file`).

    ── D-110 (caméra) : filtre MOTEUR + visée DIRECTOR ──
    `directive_director` porte la VISÉE SEULE — plan du beat, angle/cadrage,
    croyance divergente, inflexion de ton du TOUR. Tout le reste, l'outil le
    COMPOSE lui-même depuis le moteur (jamais recopié par le Director) :

      1. Contexte perçu du narrateur — même sélection par position que
         `assemble_context_to_file` (`assembleur_position.build_sections`,
         secrets/event_rules toujours OFF ici : un narrateur reçoit la
         perception du personnage, jamais les twists non tirés ni le bloc
         de règles entier), ou son repli mots-clés+budget sur une save sans
         partition — même frontière de cohabitation (`eligible()`).
      2. Derniers tours verbatim — inclus dans ce même texte (la scène où
         l'on reprend).
      3. Mécaniques résolues CE TOUR — les événements réellement APPLIQUÉS
         (jets, patchs, `event_fired`, ou — Issue #200 — intents/dégâts/
         rounds de combat), lus au JOURNAL de l'outil (`apply_envelope`
         pour la mécanique coderain classique, `start_combat`/
         `submit_intent`/`monster_turn` pour le sous-système combat —
         voir `_record_combat_events`), jamais retapés par le Director.
      4. `rendu_md` du node courant (résout D-269) — section « DIRECTION DE
         RENDU », symétrique de `modules/trinity.py::_writer_directive` mais
         désormais servie sur le chemin PRODUIT. Absente si le node n'en
         porte pas.
      5. La directive du Director, verbatim, après le filet R2.

    ── Les trois refus ──
    R1 — mécanique avant prose : refuse si aucune mécanique n'a été résolue
    depuis le dernier tour (aucune enveloppe via `apply_envelope`, ni aucun
    combat via `start_combat`/`submit_intent`/`monster_turn` — Issue #200)
    et que `sans_mecanique` n'est pas déclaré à `True` — une déclaration
    explicite qu'aucune résolution n'a eu lieu ce tour (ex. un tour de pure
    parole).

    R2 — filet anti-fuite littéral : refuse si `directive_director` contient
    un slug ou un fragment de texte d'une entrée cachée non révélée, ou le
    slug/texte d'une règle d'événement (fired ou non). Nomme la garde
    déclenchée — le Director connaît déjà les coulisses, ce n'est jamais ce
    texte qui atteint le narrateur. La paraphrase est HORS périmètre (filet
    littéral, pas un classifieur de sens).

    R3 — pas de contenu en retour : le retour ne porte jamais le texte du
    paquet, ni `rendu_md` même en booléen de contenu — seulement le chemin,
    la taille, et les NOMS des sections écrites.

    Le fichier est écrasé à chaque tour et vit hors de tout dossier de save
    (même sentinel que `assemble_context_to_file` : `.turn/`)."""
    store = _require_store()
    if _last_applied_events is None and not sans_mecanique:
        raise ValueError(
            "R1 (mécanique avant prose) : aucune mécanique résolue depuis "
            "le dernier tour — appelle apply_envelope (ou start_combat/"
            "submit_intent/monster_turn en combat) d'abord, ou déclare "
            "sans_mecanique=True si ce tour ne résout explicitement aucune "
            "mécanique.")
    directive = str(directive_director or "")
    guard = _r2_scan(store, directive)
    if guard:
        raise ValueError(
            f"R2 (filet anti-fuite) : directive_director contient la garde "
            f"« {guard} » — reformule sans slug ni fragment littéral de "
            "matériau caché ou de règle d'événement (la paraphrase reste "
            "permise, ce filet est littéral).")

    state = store.world_state()
    pdir = _partition_dir(store)
    history = store.turns()
    recent_turns = _engine.short_term if _engine is not None else 12
    rendu_md = ""
    if pdir is not None and assembleur_position.eligible(store, state):
        text, info = _position_context_text(
            store, pdir, state, history, action_joueur, recent_turns,
            event_rules=False, secrets=False, role_section=False)
        rendu_md = assembleur_position.rendu_md_for(
            pdir, str(state.get("location", "")))
    else:
        text, info = _assemble_text(action_joueur, 120000, recent_turns,
                                    0, True, False, SECRETS_WINDOW_TURNS,
                                    False)

    sections = ["Contexte perçu (scène + derniers tours)"]
    parts = [text]

    outcome = [e for e in (_last_applied_events or [])
              if not str(e).startswith("validator:")]
    if outcome:
        parts.append(
            "# MÉCANIQUES RÉSOLUES CE TOUR (déjà tirées et appliquées — "
            "narre ces résultats comme des faits, ne les contredis jamais)\n"
            + "\n".join(f"- {e}" for e in outcome))
        sections.append("Mécaniques résolues")

    rendu_md = rendu_md.strip()
    if rendu_md:
        # Issue #181 (SERVICE) puis #192 (D-269, chemin PRODUIT) : la COULEUR
        # de ton/rythme du node — narrateur SEUL, jamais citée au joueur, et
        # jamais dans le retour de cet outil (R3).
        parts.append(
            "# DIRECTION DE RENDU — jamais citée au joueur\n" + rendu_md)
        sections.append("Direction de rendu")

    if directive.strip():
        parts.append("# DIRECTIVE DU DIRECTOR\n" + directive.strip())
        sections.append("Directive du Director")

    full = "\n\n".join(parts)
    out_dir = ROOT / ".turn"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "paquet-narrateur.md"
    out.write_text(full, encoding="utf-8")
    return {"path": str(out), "chars": len(full), "sections": sections,
           **info}


@mcp.tool()
def context_candidates(player_action: str,
                       budget_tokens: int = 120000) -> dict:
    """The documentaliste's report for the SELECTION stage: what the lorebook
    activation WOULD serve for this action, as metadata only — slug, registry,
    title, size in chars, whether the entry is forced (pinned/critical), plus
    the hidden entries that activated, flagged `hidden`.

    This is the cheap half of the camera (lookup by function, deterministic,
    no LLM): it REPORTS candidates. Choosing which ones serve THIS scene is a
    JUDGMENT, and it belongs to the Director — pass the chosen slugs to
    assemble_context_to_file as `lore_include`.

    ⛔ This report feeds the DIRECTOR only (it names hidden entries). It must
    never reach the narrator or the player.

    Selection is RETIRING as much as ADDING (anti-saturation): a briefing that
    grows under this stage has moved the saturation from one organ to another.
    None/omitted `lore_include` on the assemble tools keeps the old blind
    montage — the tranche is opt-in."""
    store = _require_store()
    rows = store.lore_candidates(_wide_history(store), player_action,
                                 budget_tokens=budget_tokens)
    visible = [r for r in rows if not r.get("hidden")]
    hidden = [r for r in rows if r.get("hidden")]
    return {"candidates": rows,
            "n_visible": len(visible),
            "n_forced": sum(1 for r in visible if r.get("forced")),
            "chars_if_all_served": sum(r["chars"] for r in visible),
            "n_hidden_activated": len(hidden),
            "hidden_chars": sum(r["chars"] for r in hidden)}


# ── SillyTavern card import ──────────────────────────────────────

@mcp.tool()
def import_card(file_path: str) -> dict:
    """Import a SillyTavern character card (PNG/JSON/.charx).
    Returns the parsed card data (name, description, personality, scenario, etc.)."""
    from coderain.cards import parse_card
    p = Path(file_path)
    if not p.exists():
        return {"error": f"File not found: {file_path}"}
    try:
        return parse_card(p.read_bytes(), p.name)
    except Exception as e:
        return {"error": str(e)}


# ── player screen (web UI) ───────────────────────────────────────
# See webui.py for the why. In short: the player reads the browser, not the
# terminal, so nothing has to be hidden from the main conversation any more —
# which is what buys back the one-hour prompt cache.

@mcp.tool()
def ui_open(port: int = 8787) -> dict:
    """Open the player's screen: start the local web server and return its URL.

    Idempotent — calling it twice returns the running server. Binds 127.0.0.1
    only. The player opens this URL in a browser and plays there; the terminal
    becomes a machine room nobody reads."""
    import webui
    return webui.start(port)


@mcp.tool()
def ui_say(text: str, role: str = "mj") -> dict:
    """Print a message on the player's screen.

    role="mj" renders as prose (markdown: **bold**, *italic*, > quote, ---),
    role="systeme" as a small centred note (use it sparingly — an out-of-fiction
    aside costs the fiction). This is the ONLY channel to the player: anything
    written in the terminal instead is written to nobody."""
    import webui
    if not webui.is_running():
        return {"error": "écran non ouvert — appeler ui_open d'abord"}
    return {"id": webui.say(text, role)}


@mcp.tool()
def ui_wait(timeout_seconds: int = 40) -> dict:
    """Wait for the player to type something. Blocks up to timeout_seconds
    (capped at 40 s — see below).

    Returns {"status": "input", "text": ...} or {"status": "timeout"}.
    On timeout, call it again — the player is thinking, and thinking is free.
    Input typed while nobody was waiting is queued, never lost.

    Harness note (measured against the docs, 2026-08-03): this is a stdio server,
    so there is no 60-second per-request timer in Claude Code; the wall clock is
    the per-server `timeout` in .mcp.json (set to 30 min) and the stdio idle
    window is 30 min. The one real limit there is that a main-conversation MCP
    call still running after two minutes moves to a background task — hence the
    old advice to stay under 110 s.

    ⭐ opencode note (2026-08-22): opencode kills long tool calls with its own
    timer, so blocking long here produces an infinite retry-timeout loop.
    The wait is therefore CAPPED AT 40 s: on timeout you get {"status":
    "timeout"} and simply call again — cheap, and input is never lost."""
    import webui
    if not webui.is_running():
        return {"error": "écran non ouvert — appeler ui_open d'abord"}
    try:
        asked = int(timeout_seconds)
    except (TypeError, ValueError):
        asked = 40
    return webui.wait(max(5, min(asked, 40)))


@mcp.tool()
def ui_panel(state_line: str = "", title: str = "") -> dict:
    """Set the header of the player's screen: a one-line state readout
    (location, day, HP, gold...) and optionally the campaign title.
    Only ever put here what the player already knows about their own character."""
    import webui
    if not webui.is_running():
        return {"error": "écran non ouvert — appeler ui_open d'abord"}
    if state_line:
        webui.set_panel(state_line)
    if title:
        webui.set_title(title)
    return {"ok": True}


@mcp.tool()
def ui_sheet() -> dict:
    """Render the player's full character sheet from the loaded save and
    pin it to the right rail of the player's screen. Call it after load_save
    and after any mechanical change (HP, gold, inventory)."""
    import webui
    if not webui.is_running():
        return {"error": "écran non ouvert — appeler ui_open d'abord"}
    try:
        from coderain.modules import rpg as rpg_mod
        sheet = rpg_mod.render_sheet_lines(_require_store().rpg_state())
    except Exception as e:  # noqa: BLE001
        return {"error": f"feuille non rendue: {e}"}
    webui.set_sheet(sheet)
    return {"ok": True, "lines": sheet.count("\n") + 1}


@mcp.tool()
def ui_close() -> dict:
    """Stop the player's screen server."""
    import webui
    return webui.stop()


# ── P4 module kit: read the converted Partition (SPEC-P4 §8) ────────────────
# The current save's module.json points at its partition directory, so a
# Director playing one module can only ever see THAT module's content —
# cross-campaign confusion is structurally impossible.

def _module_partition() -> Path:
    if not _slug:
        raise ValueError("No save loaded. Call load_save first.")
    ptr = _saves_root / _slug / "module.json"
    if not ptr.exists():
        raise ValueError(f"Save '{_slug}' is not module-backed (no module.json)")
    return Path(json.loads(ptr.read_text(encoding="utf-8"))["partition"])


@mcp.tool()
def module_index() -> dict:
    """Index of the loaded save's converted module — the discovery
    primitive (SPEC-P4 §8): ids/types of nodes, records, tables and
    secrets ({id, statut} only — bodies stay out) + aventure summary.
    Read-only, no path argument: sealed to the loaded save."""
    try:
        from coderain.converter.aval import load_partition
        return load_partition(_module_partition())
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def module_list_nodes() -> list[dict]:
    """List every node of the loaded save's converted module (id/type/altitude)."""
    try:
        from coderain.converter.aval import load_partition
        return load_partition(_module_partition())["nodes"]
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)}]


@mcp.tool()
def module_get_node(node_id: str) -> dict:
    """Read ONE node of the module: its typed links + verbatim body."""
    try:
        from coderain.converter.aval import get_node
        return get_node(_module_partition(), node_id)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def module_get_record(record_id: str) -> dict:
    """Read one stat block (creature/pnj/...) of the module, already 5e."""
    try:
        from coderain.converter.aval import get_record
        return get_record(_module_partition(), record_id)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def module_roll_table(table_id: str, die_result: int | None = None) -> dict:
    """Read a rollable table; pass die_result to fetch the matching row.
    Rolling the die stays the engine's job — this only resolves the row."""
    try:
        from coderain.converter.aval import roll_table
        return roll_table(_module_partition(), table_id, die_result)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def module_get_aventure() -> dict:
    """Read the AVENTURE stage of the loaded save's module (D-178): default
    trajectory + disturbances, world conditions with triggers, exit hinge.
    Read it BEFORE directing — it is what happens if the player does nothing."""
    try:
        from coderain.converter.aval import _split_front
        raw = (_module_partition() / "aventure.md").read_text(encoding="utf-8")
        front, body = _split_front(raw)
        meta = json.loads(front) if front else {}
        return {**meta, "charniere_md":
                body.replace("## Charnière de sortie", "").strip()}
    except FileNotFoundError:
        return {"error": "cette partition ne porte pas d'étage aventure"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


# ---------------------------------------------------------------------
# Rules engine — dnd5e-engine appelé via coderain.rules_engine (D-200).
# L'état de combat vit DANS la bibliothèque pendant un combat ; ces
# endpoints soumettent des intentions et miroient les résultats en
# lecture. Les IntentRejectedError remontent telles quelles : c'est le
# moteur qui refuse, le pont ne traduit pas. modules/rpg.py garde les
# jets simples hors combat (coexistence v0).

# ── R1 signal, sous-système combat (Issue #200) ────────────────────
# `_last_applied_events` (voir sa définition plus haut) n'était posé que par
# `apply_envelope` — le SEUL chemin de mutation quand la mécanique passe par
# la couche coderain classique. Le combat mute ailleurs (dnd5e-engine, via
# CombatBridge) : start_combat/submit_intent/monster_turn ne passaient donc
# jamais par apply_envelope, R1 restait aveugle à un tour entièrement résolu
# en combat, et le Director devait déclarer sans_mecanique=True — exact au
# sens strict, faux au sens large : la section « Mécaniques résolues »
# disparaissait en plein combat (run 20260831-202617, tours 07-08).
#
# Fix : ces trois outils post-traitent aussi le même signal, avec les
# événements du moteur (intents, dégâts, rounds) convertis en lignes lisibles
# — même convention que les strings d'apply_envelope. Contrairement à
# apply_envelope (une seule enveloppe par tour, donc une AFFECTATION), un
# tour de combat enchaîne plusieurs appels avant paquet_narrateur
# (start_combat, plusieurs submit_intent, monster_turn) : les événements
# s'ACCUMULENT ici plutôt que de s'écraser, pour que la section porte tout
# le round et pas seulement le dernier appel.


def _combat_event_str(e: dict) -> str:
    """Un événement de combat (dict, model_dump du moteur) -> ligne lisible.

    Même registre que les strings d'apply_envelope ('check: ... -> succès',
    'gold: +50 -> 150') : un fait déjà tiré et appliqué, à narrer tel quel."""
    t = e.get("type", "?")
    if t == "round_started":
        return f"combat: round {e.get('round_number')} commence"
    if t == "round_ended":
        return f"combat: round {e.get('round_number')} termine"
    if t == "turn_started":
        return f"combat: tour de {e.get('actor_id')}"
    if t == "attack_rolled":
        crit = " (critique)" if e.get("is_crit") else ""
        outcome = "touche" if e.get("is_hit") else "manque"
        return (f"combat: {e.get('attacker_id')} attaque {e.get('target_id')} "
                f"-> {e.get('roll_total')} {outcome}{crit}")
    if t == "save_rolled":
        outcome = "réussi" if e.get("succeeded") else "échoué"
        return (f"combat: jet de sauvegarde {e.get('ability')} de "
                f"{e.get('target_id')} vs DD{e.get('dc')} -> "
                f"{e.get('roll_total')} {outcome}")
    if t == "check_rolled":
        succeeded = e.get("succeeded")
        outcome = "réussi" if succeeded else "échoué" if succeeded is not None else "?"
        return (f"combat: jet de {e.get('skill') or e.get('ability')} de "
                f"{e.get('actor_id')} -> {e.get('roll_total')} {outcome}")
    if t == "damage_applied":
        over = " (overkill)" if e.get("is_overkill") else ""
        return (f"combat: {e.get('target_id')} subit {e.get('amount')} dégâts "
                f"{e.get('damage_type')}{over}")
    if t == "healing_applied":
        return f"combat: {e.get('target_id')} soigné de {e.get('amount')}"
    if t == "temphp_applied":
        return f"combat: {e.get('target_id')} gagne {e.get('amount')} PV temporaires"
    if t == "condition_applied":
        return f"combat: {e.get('target_id')} subit la condition {e.get('condition')}"
    if t == "condition_removed":
        return f"combat: {e.get('target_id')} perd la condition {e.get('condition')}"
    if t == "death":
        return f"combat: {e.get('target_id')} meurt ({e.get('reason')})"
    if t == "unconscious":
        return f"combat: {e.get('target_id')} tombe inconscient"
    if t == "actor_moved":
        return (f"combat: {e.get('actor_id')} se déplace de {e.get('from_zone')} "
                f"vers {e.get('to_zone')} ({e.get('distance_ft')}ft)")
    if t == "combat_ended":
        return f"combat: terminé ({e.get('reason')})"
    # Repli générique — un type non mappé reste visible plutôt que perdu
    # silencieusement (le registre d'événements ci-dessus n'a pas vocation à
    # suivre chaque extension du moteur événement par événement).
    details = ", ".join(f"{k}={v}" for k, v in e.items() if k != "type")
    return f"combat: {t} ({details})" if details else f"combat: {t}"


def _record_combat_events(events: list[dict]) -> None:
    """Empile les événements de combat sur le signal R1 de paquet_narrateur."""
    global _last_applied_events
    if not events:
        return
    _last_applied_events = (_last_applied_events or []) + [
        _combat_event_str(e) for e in events]

@mcp.tool()
async def resolve_check(spec: dict, seed: int | None = None) -> dict:
    """Résout un jet 5e isolé (skill/ability/saving_throw) par dnd5e-engine.

    `spec` = CheckSpec du moteur : kind ("skill"|"ability"|"saving_throw"),
    ability_scores {str:int}, proficiency_bonus, et selon le cas skill,
    ability, dc, proficient_skills, proficient_saves, advantage,
    disadvantage. `seed` amorce le RNG pour un jet reproductible.
    Retour : natural_roll, modifier, roll_total, success.
    """
    from coderain.rules_engine import resolve_check as _resolve
    return _resolve(spec, seed=seed)


@mcp.tool()
async def start_combat(session_id: str, party: list[dict],
                       encounter: list[dict], rng_seed: int,
                       zones: list[str] | None = None) -> dict:
    """Ouvre un combat détenu par dnd5e-engine ; retourne handle_id.

    party/encounter = specs du moteur (PartyMemberSpec / EncounterMemberSpec :
    entity_id, name, initiative, hp_current, hp_max, ac, zone_id... ; un monstre
    jouable porte monster_template_slug ex. "goblin-warrior"). rng_seed rend le
    combat déterministe : mêmes graines ⇒ mêmes dés.
    """
    result = await get_bridge().start_combat(
        session_id=session_id, party=party, encounter=encounter,
        rng_seed=rng_seed, zones=zones)
    _record_combat_events(result.get("events", []))
    return result


@mcp.tool()
async def submit_intent(handle_id: str, actor_id: str, intent: dict) -> dict:
    """Soumet l'intention du personnage dont c'est le tour (PlayerIntent).

    intent = {"intent_type": "attack"|"move"|"pass"|..., target_id?,
    weapon_id?, target_zone_id?, ...}. Une attaque exige weapon_id résolvable
    du corpus. Refus du moteur (mauvais tour...) => IntentRejectedError brute.
    """
    result = await get_bridge().submit_intent(handle_id, actor_id, intent)
    _record_combat_events(result.get("events", []))
    return result


@mcp.tool()
async def monster_turn(handle_id: str) -> dict:
    """Fait jouer par l'IA du moteur le tour du monstre courant."""
    result = await get_bridge().monster_turn(handle_id)
    _record_combat_events(result.get("events", []))
    return result


@mcp.tool()
async def end_combat(handle_id: str) -> dict:
    """Clôt le combat : issue du moteur (ended_reason victory|defeat_tpk|
    flee|forced, morts, XP). Le handle est ensuite invalidé côté pont."""
    return await get_bridge().end_combat(handle_id)


@mcp.tool()
async def narration_events(handle_id: str) -> dict:
    """Événements de combat pendants depuis le dernier fetch (drain non
    bloquant). Même file que l'itérateur narration_events du moteur : premier
    arrivé premier servi ; MCP étant requête/réponse, on ne bloque jamais sur
    une file vide — rappeler après chaque action.
    """
    bridge = get_bridge()
    return {"events": bridge.drain_events(handle_id),
            "live": bridge.live(handle_id)}


# ── I-200: evolution interne du personnage ─────────────────────
# Two tools, one deriver. D-125: portable, setting ontology (not a 9-alignment
# grid). D-090: interoception invited IN CHARACTER, never probed in meta.
# D-100: execution = proposition (the player decides, the engine records).

_EVOLUTION_INTERNE_MIN = -5
_EVOLUTION_INTERNE_MAX = 5
_EVOLUTION_INTERNE_SCHEMA = ROOT / "schemas" / "character.json"

_FORBIDDEN_ALIGNMENTS = {
    "lawful good", "neutral good", "chaotic good",
    "lawful neutral", "true neutral", "chaotic neutral",
    "lawful evil", "neutral evil", "chaotic evil",
    "lg", "ng", "cg", "ln", "tn", "cn", "le", "ne", "ce",
}


def _validate_evolution_interne(vecteurs: list[dict]) -> list[dict]:
    """Validate a list of evolution_interne vectors against the schema rules.
    Returns the cleaned list. Raises ValueError on any problem."""
    if not isinstance(vecteurs, list):
        raise ValueError("vecteurs must be a list")
    if len(vecteurs) < 2:
        raise ValueError("at least 2 vectors required (D-125: graduated axes)")
    clean = []
    seen_ids = set()
    for v in vecteurs:
        if not isinstance(v, dict):
            raise ValueError(f"each vector must be a dict, got {type(v).__name__}")
        vid = str(v.get("id", "")).strip()
        if not vid:
            raise ValueError("vector id is required")
        if vid in seen_ids:
            raise ValueError(f"duplicate vector id: {vid}")
        seen_ids.add(vid)
        label = str(v.get("label", "")).strip()
        if not label:
            raise ValueError(f"vector {vid}: label is required")
        if label.lower() in _FORBIDDEN_ALIGNMENTS:
            raise ValueError(
                f"vector {vid}: label {label!r} is a 9-alignment grid value "
                f"(D-090 forbidden — graduated axes only)")
        try:
            valeur = int(v.get("valeur", 0))
        except (TypeError, ValueError):
            raise ValueError(f"vector {vid}: valeur must be an integer")
        if valeur < _EVOLUTION_INTERNE_MIN or valeur > _EVOLUTION_INTERNE_MAX:
            raise ValueError(
                f"vector {vid}: valeur {valeur} out of range "
                f"[{_EVOLUTION_INTERNE_MIN}, {_EVOLUTION_INTERNE_MAX}]")
        source = str(v.get("source", "")).strip().lower()
        if source not in ("interoception", "journal"):
            raise ValueError(
                f"vector {vid}: source must be 'interoception' or 'journal'")
        clean.append({"id": vid, "label": label,
                       "valeur": valeur, "source": source})
    return clean


def journal2vecteur(acte: str, vecteur_id: str) -> dict:
    """Derive a vector delta from a role-play act (non-declarative).

    The act is a description of what the CHARACTER did (not what the player
    thinks or feels — D-090 guard). Returns {"delta": int, "reason": str}.
    The delta is +1 or -1 based on keyword polarity; 0 if the act is ambiguous.

    D-090 guard: if the act reads as meta-probing (the player asking the
    character how they feel, or declaring an alignment), returns {"delta": 0,
    "refused": True, "reason": ...}."""
    acte_lower = acte.strip().lower()
    if not acte_lower:
        return {"delta": 0, "refused": True,
                "reason": "empty act — nothing to derive"}
    meta_markers = [
        "quel est ton alignement", "what is your alignment",
        "je pense que je suis", "i think i am",
        "mon alignement est", "my alignment is",
        "en tant que joueur", "as a player",
        "je ressens que le personnage", "i feel that the character",
        "je pense que mon personnage", "i think my character",
        "mon personnage est", "my character is",
    ]
    for marker in meta_markers:
        if marker in acte_lower:
            return {"delta": 0, "refused": True,
                    "reason": f"D-090: meta-probing detected ({marker!r}) — "
                              f"interoception must be IN CHARACTER, not probed "
                              f"from outside"}
    positive_poles = [
        "sauve", "protect", "defend", "sacrifice", "pardonne", "forgive",
        "aide", "help", "console", "comfort", "partage", "share",
        "courage", "bravely", "bold", "audacieux",
    ]
    negative_poles = [
        "trahit", "betray", "abandonne", "abandon", "vole", "steal",
        "ment", "lie", "manipule", "manipulate", "cruel", "blesse", "hurt",
        "fuit", "flee", "lachete", "coward", "retenue", "hesite", "hesitate",
    ]
    delta = 0
    reasons = []
    for word in positive_poles:
        if word in acte_lower:
            delta += 1
            reasons.append(f"positive pole: {word}")
            break
    for word in negative_poles:
        if word in acte_lower:
            delta -= 1
            reasons.append(f"negative pole: {word}")
            break
    if delta == 0:
        return {"delta": 0, "reason": "ambiguous act — no clear pole matched"}
    return {"delta": max(-1, min(1, delta)),
            "reason": "; ".join(reasons)}


@mcp.tool()
def set_evolution_interne(vecteurs: list[dict]) -> dict:
    """Set the character's evolution_interne vectors (I-200, performatif).

    The player DECIDES the vectors — this is not a state report (D-100).
    Each vector: {id, label, valeur (-5..+5), source: "interoception"|"journal"}.
    At least 2 vectors required (D-125: graduated axes, not 9-alignment grid).

    D-090 guard: labels matching D&D alignments are REJECTED. Source
    'interoception' means the player declared in-character; 'journal' means
    derived from acts via journal2vecteur."""
    store = _require_store()
    try:
        clean = _validate_evolution_interne(vecteurs)
    except ValueError as e:
        return {"error": str(e)}
    rpg = store.rpg_state()
    if "evolution_interne" not in rpg:
        rpg["evolution_interne"] = {}
    rpg["evolution_interne"]["vecteurs"] = clean
    store.set_rpg_state(rpg)
    return {"ok": True, "vecteurs": clean,
            "count": len(clean),
            "schema": str(_EVOLUTION_INTERNE_SCHEMA)}


@mcp.tool()
def derive_evolution_interne(acte: str, vecteur_id: str) -> dict:
    """Derive a vector delta from a role-play act (journal2vecteur, I-200).

    The act describes what the CHARACTER did — not what the player feels or
    thinks (D-090: interoception in-character, never meta-probed). Returns
    the delta and, if applied, the new vector value.

    Use after set_evolution_interne has created the vectors."""
    store = _require_store()
    result = journal2vecteur(acte, vecteur_id)
    if result.get("refused"):
        return result
    rpg = store.rpg_state()
    ei = rpg.get("evolution_interne", {})
    vecteurs = ei.get("vecteurs", [])
    target = None
    for v in vecteurs:
        if v["id"] == vecteur_id:
            target = v
            break
    if target is None:
        return {**result,
                "error": f"vector {vecteur_id!r} not found — call "
                         f"set_evolution_interne first"}
    old = target["valeur"]
    new = max(_EVOLUTION_INTERNE_MIN,
              min(_EVOLUTION_INTERNE_MAX, old + result["delta"]))
    target["valeur"] = new
    target["source"] = "journal"
    ei["vecteurs"] = vecteurs
    rpg["evolution_interne"] = ei
    store.set_rpg_state(rpg)
    return {**result, "vecteur_id": vecteur_id,
            "old_valeur": old, "new_valeur": new}


# ── organes Auteur au pont MCP (D-263, Issue #147) ────────────────
# Régime forfait : le LLM EST la session Claude Code qui pilote. Le jugement
# (conformité, choix du régime) se fait DANS la session ; ce que le code doit
# lui servir, ce sont les GARDES, les CHARGEMENTS et les RENDUS — jamais un
# appel API. `coderain.acte`/`coderain.formes` sont importés tels quels (zéro
# LLM). `coderain.retour2`/`coderain.ecrivain_module` ne le sont PAS — voir le
# commentaire d'import en tête de fichier — donc les trois choses pures que
# ces deux organes portent (le texte des exigences par régime, le prompt
# RETOUR2, les gardes de forme sur les verdicts) sont re-portées ici, à
# l'identique de leur source, avec la ligne qui les rend traçables.
#
# État de la session d'écriture en cours (un tour Auteur à la fois, même
# esprit que `_completed_turn`/`_pending_log_mark` pour un tour de jeu) :
# posé par auteur_bloc_cadre, complété par auteur_valider_ecriture, lu par
# auteur_verdicts_conformite. Une session Claude Code pilote un seul module en
# écriture à la fois — pas de pile, pas d'identifiant de session à gérer ici.
_auteur_ctx: dict = {}

_AUTEUR_REGIMES = ("pont", "rattrapage", "aiguillage")

# Copie verbatim d'ecrivain_module._EXIGENCES_REGIME (D-262 §2).
_AUTEUR_EXIGENCES_REGIME = {
    "pont": (
        "PONT : écris le MINIMUM nécessaire pour rendre le raccord "
        "atteignable — pas de matière superflue, chaque scène sert "
        "explicitement le passage vers le module/l'acte suivant."),
    "rattrapage": (
        "RATTRAPAGE : fais VIVRE, dans ce module, chacun des jalons "
        "pas-vécus listés ci-dessous — un jalon rattrapé doit se jouer "
        "réellement, jamais être mentionné en passant."),
    "aiguillage": (
        "AIGUILLAGE : propose des situations à VRAIS enjeux qui "
        "discriminent réellement entre plusieurs agendas de personnages/"
        "factions — on aiguille les AGENDAS, jamais les révélations "
        "(aucun secret ne doit dépendre du choix du joueur pour exister ou "
        "non)."),
}

# Copie verbatim d'ecrivain_module._CONTRAINTES_TRANSVERSES (D-262 §2).
_AUTEUR_CONTRAINTES_TRANSVERSES = (
    "CONTRAINTES D'ÉCRITURE TRANSVERSALES :\n"
    "- Écris des ÉTATS et des POTENTIELS, JAMAIS une séquence d'événements "
    "imposée au joueur : ce que tu écris doit rester jouable dans "
    "n'importe quel ordre que le joueur choisit.\n"
    "- Écris du texte de MODULE SOURCE (scènes, lieux, PNJ avec objectifs "
    "et accroches) — de la prose telle que le convertisseur de ce dépôt "
    "sait l'ingérer, jamais une partition d'événements scriptés.")

# Copie verbatim de retour2.RETOUR2_SYS (D-262/D-128) — le prompt de
# conformité que la SESSION juge elle-même en régime forfait, jamais un
# appel emit_json_ex depuis ce fichier.
_AUTEUR_RETOUR2_SYS = """\
You are the RETOUR 2, a compliance judge (not a play-effect judge). You are \
given OBJECTIFS (goals stated by the layer above: act objective, targeted \
milestones, régime requirements — free text, one per id) and a TEXTE (an \
episode-module written by an Author). Your job is a TEXT-VS-TEXT compliance \
check, before anything is played — never invent effects, never speculate \
about how play might go.

For EVERY objectif given to you, return ONE verdict: does the TEXTE fulfill \
it? "conforme" (fulfilled), "non-conforme" (addressed but falls short), or \
"absent" (the text never addresses it at all). Ground every verdict in a \
"justification" and, when the text does address the objectif, "extraits": \
one or more short passages QUOTED VERBATIM from the TEXTE (never \
paraphrased, never invented) that support your verdict.

If FORMES DÉCLARÉES are given (forms the Author claims to have used), judge \
each one separately: does the TEXTE actually do what the declaration \
claims? "conforme" or "non-conforme", with justification and verbatim \
extraits the same way.

Never invent an objectif_id or a forme_id — use only the ids given to you. \
Never assign a numeric score or grade — only the fixed verdict vocabulary.

Return ONLY a JSON object:
{"verdicts": [{"objectif_id": "...", "verdict": "conforme|non-conforme|absent",
               "justification": "...", "extraits": ["..."]}],
 "verdicts_formes": [{"forme_id": "...", "correspond": "conforme|non-conforme",
                       "justification": "...", "extraits": ["..."]}]}
"""

# Vocabulaire fermé des verdicts — jamais une note chiffrée (D-131/D-118),
# copie verbatim de retour2.VERDICTS_VALIDES/CORRESPONDANCES_VALIDES.
_AUTEUR_VERDICTS_VALIDES = ("conforme", "non-conforme", "absent")
_AUTEUR_CORRESPONDANCES_VALIDES = ("conforme", "non-conforme")


# Copie de ecrivain_module._valider_declaration_rendu (Issue #183,
# PRODUCTION) : garde de forme sur declaration_rendu — champ OPTIONNEL,
# liste vide toujours acceptée. La garde anti-rail D-065 elle-même (une
# couleur, jamais un script) reste au socle (Node._check_rendu_md), pas
# dupliquée ici, même choix que le converter (#182).
def _auteur_valider_declaration_rendu(declaration) -> tuple[list[dict], list[dict]]:
    if not isinstance(declaration, list):
        return [], [{"champ": "declaration_rendu",
                     "raison": "declaration_rendu n'est pas une liste"}]
    validees: list[dict] = []
    rejets: list[dict] = []
    for i, entry in enumerate(declaration):
        if not isinstance(entry, dict):
            rejets.append({"champ": "declaration_rendu",
                           "raison": f"entrée {i} n'est pas un objet"})
            continue
        scene = str(entry.get("scene", "")).strip()
        rendu_md = str(entry.get("rendu_md", "")).strip()
        if not scene:
            rejets.append({"champ": "declaration_rendu",
                           "raison": f"entrée {i} : 'scene' absente ou vide"})
            continue
        if not rendu_md:
            rejets.append({"champ": "declaration_rendu",
                           "raison": f"entrée {i} (scène {scene!r}) : "
                                    "'rendu_md' absent ou vide"})
            continue
        validees.append({"scene": scene, "rendu_md": rendu_md})
    return validees, rejets


def _auteur_normaliser_espaces(s: str) -> str:
    """Copie de retour2._normaliser_espaces : tolérance espaces pour la
    vérification par inclusion de sous-chaîne."""
    return re.sub(r"\s+", " ", s).strip()


def _auteur_extrait_present(extrait: str, texte_normalise: str) -> bool:
    return _auteur_normaliser_espaces(extrait) in texte_normalise


def _auteur_resolve_actes_path(actes_path: str) -> Path | None:
    """`actes.md` — fichier FRÈRE non encore câblé dans MemoryStore
    (acte.py:3-10) : pas de résolution automatique par le moteur. Un chemin
    explicite prime toujours ; à défaut, s'il y a une save chargée, on
    cherche `actes.md` à sa racine (même dossier que `campagne.md`, quand il
    existe). Aucune save et aucun chemin explicite -> None, erreur motivée
    côté appelant."""
    if actes_path:
        return Path(actes_path)
    if _store is not None:
        return _store.dir / "actes.md"
    return None


def _auteur_bloc_regime(acte, regime: str) -> str:
    """Copie de ecrivain_module._bloc_regime : exigences fixes + jalons
    pas-vécus concrets pour le rattrapage, jamais une re-déduction."""
    lignes = [f"## Régime d'écriture : {regime}", "",
             _AUTEUR_EXIGENCES_REGIME[regime]]
    if regime == "rattrapage":
        cibles = [j for j in acte.jalons if j.statut == "pas-vécu"]
        lignes.append("")
        lignes.append("Jalons pas-vécus à faire vivre :")
        if cibles:
            for j in cibles:
                lignes.append(f"- [{j.id}] {j.intention_md}")
        else:
            lignes.append("(aucun jalon pas-vécu — vérifier le cadre avant "
                          "d'écrire en régime rattrapage)")
    return "\n".join(lignes)


def _auteur_objectifs_regime(acte, regime: str) -> list[dict]:
    """Copie de ecrivain_module._objectifs_regime : les objectifs du retour 2
    formulés en TEXTE depuis l'acte transmis, jamais un champ structuré
    inventé par le LLM. `{id, texte}` — même forme que `Objectif.to_prompt_dict`."""
    if regime == "pont":
        raccord = acte.raccord
        return [{"id": "raccord",
                 "texte": "Le module rend atteignable le raccord vers "
                         f"{raccord.module_id or '(module suivant pas encore choisi)'} "
                         "— conditions d'entrée : "
                         f"{raccord.conditions_entree_md.strip() or '(aucune condition posée)'}"}]
    if regime == "rattrapage":
        cibles = [j for j in acte.jalons if j.statut == "pas-vécu"]
        return [{"id": f"jalon-{j.id}",
                 "texte": f"Le module fait vivre le jalon '{j.id}' : "
                         f"{j.intention_md}"}
               for j in cibles]
    if regime == "aiguillage":
        return [{"id": "aiguillage",
                 "texte": "Le module propose des situations qui discriminent "
                         "réellement entre plusieurs agendas de personnages/"
                         "factions (jamais les révélations) — objectif de "
                         f"l'acte : {acte.objectif_md.strip()}"}]
    raise ValueError(f"régime inconnu : {regime!r} (attendu {_AUTEUR_REGIMES})")


def _auteur_payload_retour2(objectifs: list[dict], texte: str,
                            formes_declarees: list[dict] | None) -> str:
    """Copie de retour2._payload."""
    parts = ["OBJECTIFS TRANSMIS:\n"
             + json.dumps(objectifs, ensure_ascii=False),
             "\nTEXTE À JUGER:\n" + texte.strip()]
    if formes_declarees:
        parts.append("\nFORMES DÉCLARÉES PAR L'ÉCRITURE:\n"
                     + json.dumps(formes_declarees, ensure_ascii=False))
    return "\n".join(parts)


def _auteur_valider_verdict(raw: dict, ids_objectifs: set[str],
                            texte_normalise: str) -> tuple[dict | None, str | None]:
    """Copie de retour2._valider_verdict — jamais un verdict accepté sur la
    parole du LLM (ici : sur la parole de la session)."""
    if not isinstance(raw, dict):
        return None, "verdict n'est pas un objet"
    objectif_id = str(raw.get("objectif_id", "")).strip()
    if not objectif_id:
        return None, "verdict sans objectif_id"
    if objectif_id not in ids_objectifs:
        return None, f"verdict cite un objectif non transmis : {objectif_id}"
    verdict = str(raw.get("verdict", "")).strip()
    if verdict not in _AUTEUR_VERDICTS_VALIDES:
        return None, (f"verdict de {objectif_id} hors vocabulaire fermé : "
                      f"{verdict!r} (attendu {_AUTEUR_VERDICTS_VALIDES})")
    justification = str(raw.get("justification", "")).strip()
    if not justification:
        return None, f"verdict de {objectif_id} sans justification"
    extraits_raw = raw.get("extraits", [])
    if not isinstance(extraits_raw, list):
        return None, f"verdict de {objectif_id} : champ 'extraits' n'est pas une liste"
    extraits = [str(e).strip() for e in extraits_raw if str(e).strip()]
    for extrait in extraits:
        if not _auteur_extrait_present(extrait, texte_normalise):
            return None, (f"verdict de {objectif_id} : extrait introuvable "
                          f"dans le texte : {extrait!r}")
    return {"objectif_id": objectif_id, "verdict": verdict,
            "justification": justification, "extraits": extraits}, None


def _auteur_valider_verdict_forme(raw: dict, ids_formes: set[str],
                                  texte_normalise: str) -> tuple[dict | None, str | None]:
    """Copie de retour2._valider_verdict_forme."""
    if not isinstance(raw, dict):
        return None, "verdict de forme n'est pas un objet"
    forme_id = str(raw.get("forme_id", "")).strip()
    if not forme_id:
        return None, "verdict de forme sans forme_id"
    if forme_id not in ids_formes:
        return None, f"verdict cite une forme non déclarée : {forme_id}"
    correspond = str(raw.get("correspond", "")).strip()
    if correspond not in _AUTEUR_CORRESPONDANCES_VALIDES:
        return None, (f"verdict de forme {forme_id} hors vocabulaire fermé : "
                      f"{correspond!r} (attendu {_AUTEUR_CORRESPONDANCES_VALIDES})")
    justification = str(raw.get("justification", "")).strip()
    if not justification:
        return None, f"verdict de forme {forme_id} sans justification"
    extraits_raw = raw.get("extraits", [])
    if not isinstance(extraits_raw, list):
        return None, f"verdict de forme {forme_id} : champ 'extraits' n'est pas une liste"
    extraits = [str(e).strip() for e in extraits_raw if str(e).strip()]
    for extrait in extraits:
        if not _auteur_extrait_present(extrait, texte_normalise):
            return None, (f"verdict de forme {forme_id} : extrait introuvable "
                          f"dans le texte : {extrait!r}")
    return {"forme_id": forme_id, "correspond": correspond,
            "justification": justification, "extraits": extraits}, None


def _auteur_synthese(objectifs: list[dict], verdicts: list[dict],
                     formes_declarees: list[dict] | None,
                     verdicts_formes: list[dict]) -> tuple[bool, list[dict]]:
    """Copie de retour2._synthese. ⛔ AUCUN score agrégé (D-131/D-118) : une
    LISTE d'écarts nommés, jamais un chiffre."""
    par_objectif = {v["objectif_id"]: v for v in verdicts}
    ecarts: list[dict] = []
    for obj in objectifs:
        v = par_objectif.get(obj["id"])
        if v is None:
            ecarts.append({"type": "objectif", "id": obj["id"],
                           "verdict": "non-couvert",
                           "justification": "aucun verdict validé pour cet "
                           "objectif (absent de la sortie ou rejeté par la "
                           "garde de forme)"})
        elif v["verdict"] != "conforme":
            ecarts.append({"type": "objectif", "id": obj["id"],
                           "verdict": v["verdict"],
                           "justification": v["justification"]})

    if formes_declarees:
        par_forme = {v["forme_id"]: v for v in verdicts_formes}
        for decl in formes_declarees:
            forme_id = str(decl.get("id", "")).strip()
            v = par_forme.get(forme_id)
            if v is None:
                ecarts.append({"type": "forme", "id": forme_id,
                               "verdict": "non-couvert",
                               "justification": "aucun verdict de "
                               "correspondance validé pour cette forme "
                               "déclarée"})
            elif v["correspond"] != "conforme":
                ecarts.append({"type": "forme", "id": forme_id,
                               "verdict": v["correspond"],
                               "justification": v["justification"]})

    return len(ecarts) == 0, ecarts


@mcp.tool()
def auteur_bloc_cadre(acte_id: str, regime: str, actes_path: str = "") -> dict:
    """Le bloc cadre de l'Auteur pour UN acte, UN régime — CODE seul, aucune
    génération : la session LIT ce bloc et écrit elle-même le module.

    Rend {"bloc_cadre", "bloc_regime", "bloc_formes", "contraintes_transverses",
    "objectifs"} :
    - bloc_cadre : les trois lectures de l'acte (remplissage mesuré au vécu
      promu, pièces de divergence, raccord) — `acte.bloc_cadre`.
    - bloc_regime : les exigences du régime choisi (pont|rattrapage|
      aiguillage) — le régime est un JUGEMENT d'Auteur/Souhel fait par la
      session sur les lectures du cadre, jamais déduit ici.
    - bloc_formes : le stock de formes narratives (D-261), déclaration
      obligatoire.
    - contraintes_transverses : états/potentiels jamais une séquence
      imposée · texte de module source tel que le convertisseur sait
      l'ingérer (D-262 §2, transverse aux trois régimes).
    - objectifs : les objectifs du retour 2 pour ce régime, en TEXTE — ce que
      `auteur_valider_ecriture`/`auteur_verdicts_conformite` utiliseront
      ensuite ; posés en contexte de session par cet appel.

    `actes_path` : chemin explicite vers `actes.md`. Vide -> si une save est
    chargée (`load_save`), `<save>/actes.md` ; sinon erreur motivée
    (`actes.md` n'est pas encore câblé dans le moteur, acte.py:3-10)."""
    if regime not in _AUTEUR_REGIMES:
        return {"error": f"régime inconnu : {regime!r} "
                         f"(attendu {_AUTEUR_REGIMES})"}
    path = _auteur_resolve_actes_path(actes_path)
    if path is None:
        return {"error": "actes_path vide et aucune save chargée — appeler "
                         "load_save d'abord ou passer actes_path explicitement"}
    if not path.exists():
        return {"error": f"actes.md introuvable : {path}"}
    actes = acte_mod.load_file(path)
    acte = actes.by_id(acte_id)
    if acte is None:
        return {"error": f"acte introuvable : {acte_id!r} ({path})",
                "actes_disponibles": [a.id for a in actes.actes]}

    cadre = acte_mod.bloc_cadre(acte, _store)
    bloc_regime = _auteur_bloc_regime(acte, regime)
    vocabulaire = formes_mod.charger_vocabulaire()
    bloc_formes = formes_mod.bloc_prompt(vocabulaire)
    objectifs = _auteur_objectifs_regime(acte, regime)

    global _auteur_ctx
    _auteur_ctx = {"acte_id": acte.id, "regime": regime, "objectifs": objectifs}
    return {"bloc_cadre": cadre, "bloc_regime": bloc_regime,
            "bloc_formes": bloc_formes,
            "contraintes_transverses": _AUTEUR_CONTRAINTES_TRANSVERSES,
            "objectifs": objectifs}


@mcp.tool()
def auteur_valider_ecriture(module_md: str, declaration_formes_json: str,
                            note_intention_md: str,
                            declaration_rendu_json: str = "") -> dict:
    """Enchaîne les gardes CODE sur ce que la session vient d'écrire, APRÈS
    un appel `auteur_bloc_cadre` (qui pose les objectifs du régime en
    contexte de session).

    Gardes : `module_md`/`note_intention_md` non vides · `declaration_formes_json`
    ancrée au vocabulaire de formes (`formes.valider_declaration` — id hors
    vocabulaire ou justification vide REFUSÉS). Refus motivés, jamais
    silencieux : {"ok": false, "rejets": [...]}.

    `declaration_rendu_json` (Issue #183, PRODUCTION) : OPTIONNEL — une
    couleur de rendu par scène (`[{"scene", "rendu_md"}, ...]`), présent/
    impératif, jamais un enchaînement d'événements. Vide -> `[]`, aucun
    rejet. Présent -> chaque entrée exige `scene`/`rendu_md` non vides
    (forme seulement ; la garde anti-rail D-065 elle-même reste au socle,
    `Node._check_rendu_md`, constatée à la conversion — pas dupliquée ici,
    même choix que le converter #182).

    Sur garde passée : {"ok": true, "formes_validees": [...],
    "declaration_rendu_validee": [...],
    "conformite_prompt": {"system", "payload", "objectifs"}} — le PROMPT de
    conformité du retour 2 (D-262/D-128), prêt à l'emploi. Le jugement de
    conformité (le texte remplit-il chaque objectif ?) reste un jugement LLM
    et se fait PAR LA SESSION : elle répond à ce prompt elle-même puis passe
    sa réponse à `auteur_verdicts_conformite` — aucun appel API ici."""
    global _auteur_ctx
    if not _auteur_ctx.get("objectifs"):
        return {"ok": False, "rejets": [{"champ": "regime",
                "raison": "aucun cadre en contexte — appeler auteur_bloc_cadre "
                         "(acte_id + régime) d'abord"}]}

    module_md = (module_md or "").strip()
    note_intention_md = (note_intention_md or "").strip()
    rejets: list[dict] = []
    if not module_md:
        rejets.append({"champ": "module_md", "raison": "module_md absent ou vide"})
    if not note_intention_md:
        rejets.append({"champ": "note_intention_md",
                       "raison": "note_intention_md absente ou vide"})

    try:
        declaration = (json.loads(declaration_formes_json)
                       if isinstance(declaration_formes_json, str)
                       else declaration_formes_json)
    except json.JSONDecodeError as e:
        rejets.append({"champ": "declaration_formes_json",
                       "raison": f"JSON invalide : {e}"})
        return {"ok": False, "rejets": rejets}
    if not isinstance(declaration, list):
        declaration = []

    try:
        declaration_rendu = (json.loads(declaration_rendu_json)
                             if declaration_rendu_json else [])
    except json.JSONDecodeError as e:
        rejets.append({"champ": "declaration_rendu_json",
                       "raison": f"JSON invalide : {e}"})
        return {"ok": False, "rejets": rejets}

    vocabulaire = formes_mod.charger_vocabulaire()
    validees, rejets_formes = formes_mod.valider_declaration(declaration, vocabulaire)
    for r in rejets_formes:
        rejets.append({"champ": "declaration_formes", **r})

    rendu_valide, rejets_rendu = _auteur_valider_declaration_rendu(declaration_rendu)
    rejets.extend(rejets_rendu)

    if rejets:
        return {"ok": False, "rejets": rejets}

    objectifs = _auteur_ctx["objectifs"]
    payload = _auteur_payload_retour2(objectifs, module_md, validees)

    _auteur_ctx = {**_auteur_ctx, "module_md": module_md,
                   "declaration_formes": validees,
                   "declaration_rendu": rendu_valide,
                   "texte_normalise": _auteur_normaliser_espaces(module_md)}
    return {"ok": True, "formes_validees": validees,
            "declaration_rendu_validee": rendu_valide,
            "conformite_prompt": {"system": _AUTEUR_RETOUR2_SYS,
                                  "payload": payload, "objectifs": objectifs}}


@mcp.tool()
def auteur_verdicts_conformite(verdicts_json: str) -> dict:
    """La garde de forme du retour 2 (D-262/D-128) sur les verdicts rendus
    PAR LA SESSION en réponse au `conformite_prompt` d'`auteur_valider_ecriture`.

    Forme attendue : `{"verdicts": [{"objectif_id", "verdict", "justification",
    "extraits"}], "verdicts_formes": [{"forme_id", "correspond",
    "justification", "extraits"}]}` — même contrat que le prompt le demande.

    Rejeté, jamais accepté sur parole : objectif_id/forme_id hors de ceux
    transmis · verdict hors du vocabulaire fermé (conforme|non-conforme|
    absent, ou conforme|non-conforme pour une forme) · justification vide ·
    extrait introuvable dans le texte (sous-chaîne, tolérance espaces).

    Rend un `RapportConformite` en dict : verdicts validés, verdicts_formes
    validés, rejets motivés, `conforme_total`, `ecarts`. ⛔ AUCUN score
    agrégé, aucune note chiffrée (D-131/D-118) : `ecarts` est une LISTE
    d'écarts nommés — l'Auteur (ou Souhel) tranche sur cette liste, jamais
    sur un chiffre."""
    if "texte_normalise" not in _auteur_ctx:
        return {"error": "aucune écriture validée en contexte — appeler "
                         "auteur_valider_ecriture d'abord"}
    try:
        obj = (json.loads(verdicts_json) if isinstance(verdicts_json, str)
              else verdicts_json)
    except json.JSONDecodeError as e:
        return {"error": f"JSON invalide : {e}"}
    if not isinstance(obj, dict):
        return {"error": "verdicts_json doit être un objet "
                         "{verdicts: [...], verdicts_formes: [...]}"}

    objectifs = _auteur_ctx["objectifs"]
    formes_declarees = _auteur_ctx.get("declaration_formes") or []
    ids_objectifs = {o["id"] for o in objectifs}
    ids_formes = {d["id"] for d in formes_declarees}
    texte_normalise = _auteur_ctx["texte_normalise"]

    bruts = obj.get("verdicts")
    if not isinstance(bruts, list):
        return {"error": "sortie sans champ 'verdicts' (liste)"}

    verdicts: list[dict] = []
    rejets: list[dict] = []
    for raw in bruts:
        v, raison = _auteur_valider_verdict(raw, ids_objectifs, texte_normalise)
        if v is not None:
            verdicts.append(v)
        else:
            rejets.append({"verdict": raw, "raison": raison})

    verdicts_formes: list[dict] = []
    if formes_declarees:
        bruts_formes = obj.get("verdicts_formes")
        if not isinstance(bruts_formes, list):
            rejets.append({"verdict": None, "raison": "sortie sans champ "
                          "'verdicts_formes' (liste) alors que des formes "
                          "étaient déclarées"})
        else:
            for raw in bruts_formes:
                v, raison = _auteur_valider_verdict_forme(raw, ids_formes,
                                                          texte_normalise)
                if v is not None:
                    verdicts_formes.append(v)
                else:
                    rejets.append({"verdict": raw, "raison": raison})

    conforme_total, ecarts = _auteur_synthese(objectifs, verdicts,
                                              formes_declarees, verdicts_formes)
    return {"verdicts": verdicts, "verdicts_formes": verdicts_formes,
            "rejets": rejets, "conforme_total": conforme_total,
            "ecarts": ecarts}


def _release_save_lock() -> None:
    """Clean-shutdown side of I-188 (Issue #115): drop this process's own
    save lock so the slug is free again for the next session. Registered
    against atexit and the terminating signals below — best-effort, since a
    shutdown path must never itself fail to shut down. A hard kill (SIGKILL,
    or TerminateProcess on Windows) skips all of this; that's exactly the
    orphan case `save_lock.held_by_other_live_process` reclaims on next
    load."""
    if _slug:
        try:
            save_lock.release(_saves_root / _slug, _slug)
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    # Opt-in: set CODERAIN_UI_AUTOSTART to a port in the project's .mcp.json env
    # block and the screen is up before Claude Code says a word — so a launcher
    # can open the browser and the engine at the same time without a race.
    import atexit
    import os
    import signal

    atexit.register(_release_save_lock)
    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(_sig, lambda signum, frame: sys.exit(0))
        except (ValueError, OSError, AttributeError):
            pass  # not every signal is settable on every platform

    _auto = os.environ.get("CODERAIN_UI_AUTOSTART")
    if _auto:
        try:
            import webui
            webui.start(int(_auto))
        except Exception:  # noqa: BLE001 — a dead screen must not kill the engine
            pass
    mcp.run()
