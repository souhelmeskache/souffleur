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
# Runs both as the launched entrypoint (`python mcp_server.py`, __main__)
# and as a plain import (tests: `import mcp_server`) — those are two
# distinct module objects unless aliased. The family tool modules under
# coderain/mcp/ do `import mcp_server` to reach the shared state/helpers
# below; without this alias a run as __main__ would re-execute this file
# a second time under the name 'mcp_server', splitting global state (and
# the `mcp` instance the tools register onto) into two copies (I-233).
sys.modules.setdefault("mcp_server", sys.modules[__name__])

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
    from coderain.validator import fold_skill
    name = fold_skill(skill_name)
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
            if fold_skill(sname) != name:
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


# ── attaque de bout en bout (I-463, D-274 §1-2) ──────────────────
# Au banc (run 20260831-202617, tours 21-27) le Director a simulé sept attaques
# à coups de resolve_check, avec une DEX fabriquée et une CA inventée, puis a
# joué le monstre lui-même : aucun outil ne résolvait une attaque de bout en
# bout. `attack` est ce chemin — il LIT les deux fiches, jette, et applique par
# le guichet. Tout nombre qu'il ne trouve pas sur une fiche est un REFUS ;
# aucun `default=` n'est consulté (surtout pas ceux de monster_bridge.py:214).

def _attack_fiche(store, who: str) -> dict:
    """La fiche de combat d'un camp, telle qu'elle est ÉCRITE — jamais complétée.

    `who` = "player" (fiche joueur, CA/bonus dérivés par rpg.derived_combat)
    ou un slug : entrée de `characters.md`, sinon record de créature du module
    (mêmes champs 5e que `encounter_member_from_record` lit — `ca`, `pv`,
    `attaque_bonus`, `degats` — mais lus SANS ses defaults silencieux).
    Un champ absent reste `None` ici : c'est `attack` qui prononce le refus,
    selon ce dont le jet demandé a besoin."""
    from coderain.templates import slugify
    rpg_mod = _load_rpg()
    if who is None or str(who).strip().lower() in ("player", "you", ""):
        rpg = store.rpg_state()
        derived = rpg_mod.player_combat(store)
        if derived.get("error"):
            return {"error": f"{derived['error']} — player sheet"}
        p = rpg.get("player") or {}
        w = derived.get("weapon") or {}
        return {"kind": "player", "slug": "player", "name": "player",
                "ac": derived["ac"], "attack_bonus": derived["attack_bonus"],
                "damage": w.get("damage"), "weapon": w.get("slug"),
                "hp": p.get("hp"), "hp_max": p.get("hp_max")}

    slug = slugify(str(who))
    attrs, name = None, slug
    for e in store.entries("characters.md"):
        if e.slug == slug:
            attrs = {str(k).strip().lower(): v for k, v in e.attrs.items()}
            name = e.title
            break
    if attrs is None:
        try:
            from coderain.converter.aval import get_record
            rec = get_record(_module_partition(), str(who))
        except Exception:  # noqa: BLE001 — ni fiche ni record : refus plus bas
            rec = None
        if not isinstance(rec, dict):
            return {"error": f"unknown combatant '{who}' (no entry on "
                             f"characters.md, no module record)"}
        stats = rec.get("stats", rec)
        attrs = {str(k).strip().lower(): v
                 for k, v in (stats if isinstance(stats, dict) else {}).items()}
        name = str(attrs.get("nom") or slug)

    def _num(key):
        got = rpg_mod.opt_int(attrs.get(key))
        return None if (got is None or got is False) else got

    return {"kind": "npc", "slug": slug, "name": name,
            "ac": _num("ca"), "attack_bonus": _num("attaque_bonus"),
            "damage": (str(attrs.get("degats")).strip()
                       if str(attrs.get("degats") or "").strip() else None),
            "weapon": None, "hp": None, "hp_max": _num("pv")}


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
    location = validator_mod.current_location(state)
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


# ── outils MCP par famille (I-233 — decoupe de mcp_server.py) ──────
# Chaque module ci-dessous fait `import mcp_server` et enregistre ses outils
# sur `mcp` (import ici -> execution des @mcp.tool() -> enregistrement) ; le
# `import *` les reexpose comme attributs de ce module (mcp_server.attack,
# mcp_server.paquet_narrateur, ...), a l'identique d'avant la decoupe -- les
# tests qui font `mcp_server.<outil>(...)` ou monkeypatchent l'etat partage
# (`mcp_server._store = ...`) n'ont pas a changer.
from coderain.mcp import (jets_combat, position_etat, narrateur,
                          save_installation, auteur, memoire_rappel)
from coderain.mcp.jets_combat import *
from coderain.mcp.position_etat import *
from coderain.mcp.narrateur import *
from coderain.mcp.save_installation import *
from coderain.mcp.auteur import *
from coderain.mcp.memoire_rappel import *


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
