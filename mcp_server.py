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
from coderain import validator as validator_mod
from coderain.sidecar import DEFAULT_CFG as _DEFAULT_RPG

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
_saves_root: Path = ROOT / "saves"
# Sentinel: "this pipeline resolved the mechanics before the narrator wrote".
# See _assemble_text — it is what selects the engine's quad-mode sheet.
_RESOLVED_BEFORE_NARRATION = object()
_instructions_root: Path = ROOT / "instructions"
_scenarios_root: Path = ROOT / "scenarios"


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
        _lib = Library(ROOT)
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
    out, detail, counts = [], [], {}
    for rel in store.gated_registries():
        for e in store.entries(rel):
            if not e.hidden():
                continue
            why = [w for w, on in (("pinned", e.pinned()),
                                   ("critical", e.weight() == "critical")) if on]
            if why:
                counts[rel] = counts.get(rel, 0) + 1
                detail.append(f"{rel}:{e.slug} ({'+'.join(why)})")
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
    outcomes reach canon-events.md and what makes undo_last possible."""
    global _store, _engine, _cfg, _rpg_cfg, _slug, _completed_turn
    global _pending_log_mark
    _pending_log_mark = None     # a mark from another save is meaningless here
    lib = _library()
    if not (_saves_root / slug).exists():
        return {"error": f"Save not found: {slug}",
                "available": [s.get("slug") for s in lib.saves.list()]}

    _store = lib.saves.store(slug)
    _slug = slug
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
    global _completed_turn, _pending_log_mark
    eng = _require_engine()
    before = len(_require_store().turns())
    _stage_rollback()
    done = eng.undo_last()
    # The snapshot is consumed by the restore; the next turn needs a fresh one.
    # The ledger mark goes too: the engine truncated the log under it.
    _completed_turn = None
    _pending_log_mark = None
    _arm_turn()
    return {"undone": bool(done), "turns_before": before,
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
    22 rules land twice and a repetition reads as emphasis."""
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
    global _pending_log_mark
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
        return _echo_checks(_engine.apply_envelope(
            env, rpg_on and store.rpg_enabled(),
            log_turn=len(store.turns()) + 2))

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
    return _echo_checks(events)


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
    # loop is already forbidden to skip.
    _arm_turn(retire=True)
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
    global _completed_turn, _pending_log_mark
    eng = _require_engine()
    store = _require_store()
    turns = store.turns()
    if turns and turns[-1]["role"] == "narrator" and len(turns) >= 2:
        action = turns[-2]["text"]
        store.drop_last_turns(2)
    elif turns and turns[-1]["role"] == "player":
        action = turns[-1]["text"]
        store.drop_last_turns(1)
    else:
        return {"error": "Nothing to retry yet."}
    _stage_rollback()
    eng.restore_pre_turn_rpg()
    _completed_turn = None
    _pending_log_mark = None     # the engine truncated the log under the mark
    _arm_turn()          # the replayed turn needs its own snapshot
    n = len(store.turns())
    # The native loop re-probes the fold after a retry (play.py:363-365); the
    # turn count moved, so the answer can have changed.
    return {"action": action, "turns": n, "fold_due": _fold_probe(n)}


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
                   secrets: bool = True):
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
                                 scenes_tail=tail, budget_tokens=budget_tokens)
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
                                   scenes_tail=tail, budget_tokens=budget_tokens)
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
                  "secrets_window": win}



@mcp.tool()
def assemble_context(player_action: str, budget_tokens: int = 120000,
                     recent_turns: int | None = None, max_secrets: int = 0,
                     wide_lore: bool = True, event_rules: bool = True,
                     secrets_window: int = SECRETS_WINDOW_TURNS,
                     secrets: bool = True) -> str:
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
    entirely — see assemble_context_to_file, which is where that belongs."""
    text, _info = _assemble_text(player_action, budget_tokens, recent_turns,
                                 max_secrets, wide_lore, event_rules,
                                 secrets_window, secrets)
    return text


@mcp.tool()
def assemble_context_to_file(player_action: str, budget_tokens: int = 120000,
                             recent_turns: int | None = None,
                             max_secrets: int = 0, wide_lore: bool = True,
                             event_rules: bool = False,
                             secrets_window: int = SECRETS_WINDOW_TURNS,
                             secrets: bool = False) -> dict:
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

    The file is overwritten every turn and lives outside any save folder."""
    text, info = _assemble_text(player_action, budget_tokens, recent_turns,
                                max_secrets, wide_lore, event_rules,
                                secrets_window, secrets)
    out_dir = ROOT / ".turn"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "context.md"
    out.write_text(text, encoding="utf-8")
    return {"path": str(out), "chars": len(text), **info}


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


if __name__ == "__main__":
    # Opt-in: set CODERAIN_UI_AUTOSTART to a port in the project's .mcp.json env
    # block and the screen is up before Claude Code says a word — so a launcher
    # can open the browser and the engine at the same time without a race.
    import os
    _auto = os.environ.get("CODERAIN_UI_AUTOSTART")
    if _auto:
        try:
            import webui
            webui.start(int(_auto))
        except Exception:  # noqa: BLE001 — a dead screen must not kill the engine
            pass
    mcp.run()
