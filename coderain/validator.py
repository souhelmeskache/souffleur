"""Wave 1: the Backend Validator — pure code, never an LLM.

The Quad pipeline's third stage (SPEC-V2 §1.4): LLMs PROPOSE state changes as a
versioned JSON envelope (Appendix A.1); this module checks schema + legality and
only clean deltas ever reach the state. It extends the founding invariant — dice
are engine-rolled, never LLM-rolled — to every mutable.

One schema, two producers: the single-brain ```rpg sidecar and the Logic Agent's
plan both validate through here, so no rule is written twice. Envelopes without a
"v" key (every pre-W1 producer) are treated as v1.

Split of duties with rpg.py: this module VALIDATES the whole envelope and APPLIES
the world-level deltas (time_advance / flag_set / location — meaningful even with
the RPG toggle off); `rpg.apply` keeps applying the mechanics block (inert when
RPG is off, exactly as before).
"""
from __future__ import annotations

import copy

ENVELOPE_VERSION = 1

# Per-turn companion-trust delta cap (SPEC-V2 §3.4): a single dramatic turn may
# move trust a little, never swing the whole relationship.
TRUST_CAP = 5
# time_advance day cap (SPEC-V2 §1.3): 1 day/turn normally; a declared scene
# break may skip further, but never unbounded.
DAY_CAP = 1
DAY_CAP_SCENE_BREAK = 30
# Magnitude caps (same philosophy as TRUST_CAP/DAY_CAP): a hallucinated huge
# number must not freeze the level-up loop or explode the state.
NUM_CAP = 1000            # hp/mana/xp per envelope
GOLD_CAP = 100_000        # gold per envelope
QTY_CAP = 100             # per-item quantity
# persist history cap (D-216 §3): the mutation trail kept per persistent
# attribute — enough to reconstruct any arc, small enough to never bloat.
PERSIST_HISTORY_CAP = 20

# Envelope keys that live NEXT TO the deltas (not inside them).
_TOP_KEYS = {"v", "scene_break", "check", "deltas"}

# Deltas that exist today (mechanics from Phase 4 + the Wave 1 world deltas).
_MECHANICS = {"hp_delta", "mana_delta", "xp_delta",
              "inventory_add", "inventory_remove",
              "inventory_equip", "inventory_unequip",
              "status_add", "status_remove", "trust", "npc_state", "enemies",
              "ability_add", "title_add"}
_WORLD = {"time_advance", "flag_set", "location", "gold_delta",
          "quest_update", "beat_advance", "persist"}
# Wave 2/4: sanctioned Markdown mutations, applied by the engine so they can be
# undone (reveal -> re-hide; event_fired -> un-consume).
_LORE = {"reveal", "event_fired"}

_INT_DELTAS = {"hp_delta", "mana_delta", "xp_delta"}
_STR_LISTS = {"status_add", "status_remove"}
_ITEM_LISTS = {"inventory_add", "inventory_remove"}
# Quest state machine (SPEC-V2 A.5): the ONLY legal transitions.
_QUEST_FLOW = {"inactive": {"active"}, "active": {"completed", "failed"}}


def _reject(rejected: list, key: str, value, reason: str) -> None:
    rejected.append({"delta": key, "value": value, "reason": reason})


def _as_int(v):
    """Strict int for envelope fields: bools and non-numerics are None (invalid),
    unlike rpg._as_int which coerces to a default. json.loads accepts the bare
    tokens NaN/Infinity, so int(float) can raise — those are invalid too."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        return int(v)
    except (ValueError, OverflowError):
        return None


def validate(env, store, stats: list[str] | None = None) -> tuple[dict, list[dict]]:
    """Schema + legality pass over a proposed envelope. Returns
    ``(clean, rejected)`` — `clean` is safe to apply as-is; `rejected` lists every
    dropped delta with its reason (fed back to the Logic Agent for the one
    corrective re-ask, then surfaced as a warning).

    Never raises on bad input: an unusable envelope comes back as ({}, [reason]).
    Values are clamped where the spec says clamp (trust cap, day cap) and dropped
    where the shape or the state says illegal. Pass `stats` (the configured
    attribute list) to reject checks against made-up stats — a live run showed
    models inventing `"stat": "default"`.
    """
    rejected: list[dict] = []
    if not isinstance(env, dict):
        _reject(rejected, "envelope", env, "not a JSON object")
        return {}, rejected
    v = env.get("v", ENVELOPE_VERSION)
    if _as_int(v) != ENVELOPE_VERSION:
        _reject(rejected, "v", v, f"unsupported envelope version (expect {ENVELOPE_VERSION})")
        return {}, rejected

    clean: dict = {"v": ENVELOPE_VERSION}
    scene_break = bool(env.get("scene_break", False))
    if scene_break:
        clean["scene_break"] = True
    for key in env:
        if key not in _TOP_KEYS:
            _reject(rejected, key, env[key], "unknown envelope key")

    # --- check (the engine still rolls; we only sanity-check the proposal) ---
    chk = env.get("check")
    if chk is not None:
        stat = str(chk.get("stat", "")).strip().lower() \
            if isinstance(chk, dict) else ""
        if not isinstance(chk, dict):
            _reject(rejected, "check", chk, "check must be an object")
        elif not stat:
            _reject(rejected, "check", chk, "check needs a 'stat'")
        elif stats and stat not in [s.lower() for s in stats]:
            _reject(rejected, "check", chk,
                    f"unknown stat '{stat}' (use one of: {', '.join(stats)})")
        elif chk.get("dc") is not None and _as_int(chk.get("dc")) is None:
            _reject(rejected, "check", chk, "check 'dc' must be a number")
        else:
            clean["check"] = chk

    # --- deltas ---
    d = env.get("deltas")
    if d is None:
        return clean, rejected
    if not isinstance(d, dict):
        _reject(rejected, "deltas", d, "deltas must be an object")
        return clean, rejected

    state = store.world_state()
    out: dict = {}
    for key, value in d.items():
        if key in _INT_DELTAS:
            iv = _as_int(value)
            if iv is None:
                _reject(rejected, key, value, "must be an integer")
            elif iv:
                out[key] = max(-NUM_CAP, min(NUM_CAP, iv))
        elif key in _STR_LISTS:
            if not isinstance(value, list):
                _reject(rejected, key, value, "must be a list of names")
                continue
            names = [str(x).strip() for x in value if str(x).strip()]
            if names:
                out[key] = names
        elif key in _ITEM_LISTS:
            got = _valid_items(key, value, rejected)
            if got and key == "inventory_remove":
                got = _held_only(got, state, store, rejected)
            if got:
                out[key] = got
        elif key == "trust":
            got = _valid_trust(value, rejected)
            if got:
                out[key] = got
        elif key == "enemies":
            if isinstance(value, dict):
                out[key] = value          # per-enemy shape is clamped in rpg.apply
            else:
                _reject(rejected, key, value, "must be an object of enemy specs")
        elif key == "time_advance":
            got = _valid_time(value, state, scene_break, rejected)
            if got:
                out[key] = got
        elif key == "flag_set":
            got = _valid_flags(value, state, rejected)
            if got:
                out[key] = got
        elif key == "persist":
            got = _valid_persist(value, store, state, rejected)
            if got:
                out[key] = got
        elif key == "location":
            loc = _slug(value)
            if loc:
                out[key] = loc
            else:
                _reject(rejected, key, value, "must be a location name/slug")
        elif key == "reveal":
            got = _valid_reveal(value, store, rejected)
            if got:
                out[key] = got
        elif key == "event_fired":
            got = _valid_events(value, store, rejected)
            if got:
                out[key] = got
        elif key == "gold_delta":
            iv = _as_int(value)
            if iv is None:
                _reject(rejected, key, value, "must be an integer")
            elif iv:
                iv = max(-GOLD_CAP, min(GOLD_CAP, iv))
                have = _as_int((state.get("player") or {}).get("gold", 0)) or 0
                if iv < 0 and have + iv < 0:
                    _reject(rejected, key, value,
                            f"not enough gold (have {have})")
                else:
                    out[key] = iv
        elif key in ("inventory_equip", "inventory_unequip"):
            got = _valid_equip(key, value, state, d, rejected)
            if got:
                out[key] = got
        elif key == "quest_update":
            got = _valid_quests(value, store, state, rejected)
            if got:
                out[key] = got
        elif key == "npc_state":
            got = _valid_npc_state(value, rejected)
            if got:
                out[key] = got
        elif key == "beat_advance":
            steps = 1 if value is True else _as_int(value)
            if not steps or steps < 1:
                if value:                      # false/0 = silently nothing
                    _reject(rejected, key, value, "must be true or a step count")
            elif not _beats(store):
                _reject(rejected, key, value,
                        "no beat structure defined (## Beats in memory/arc.md)")
            else:
                out[key] = steps
        elif key in ("ability_add", "title_add"):
            got = _valid_grants(key, value, d, state, rejected)
            if got:
                out[key] = got
        else:
            _reject(rejected, key, value, "unknown delta")
    if out:
        clean["deltas"] = out
    return clean, rejected


def _slug(value) -> str:
    from .templates import slugify
    s = str(value or "").strip()
    return slugify(s) if s else ""


def _valid_trust(value, rejected: list) -> dict:
    if not isinstance(value, dict):
        _reject(rejected, "trust", value, "must be {slug: delta}")
        return {}
    out = {}
    for slug, delta in value.items():
        iv = _as_int(delta)
        s = _slug(slug)
        if not s or iv is None:
            _reject(rejected, f"trust:{slug}", delta, "must be {slug: integer delta}")
            continue
        if iv:
            out[s] = max(-TRUST_CAP, min(TRUST_CAP, iv))   # per-turn cap: clamp
    return out


def _valid_time(value, state: dict, scene_break: bool, rejected: list) -> dict:
    if not isinstance(value, dict):
        _reject(rejected, "time_advance", value, "must be an object")
        return {}
    out = {}
    days = value.get("days")
    if days is not None:
        iv = _as_int(days)
        if iv is None or iv < 0:
            _reject(rejected, "time_advance", value,
                    "days must be a non-negative integer (the clock never runs back)")
        elif iv:
            out["days"] = min(iv, DAY_CAP_SCENE_BREAK if scene_break else DAY_CAP)
    for k in ("phase", "weather"):
        s = str(value.get(k, "") or "").strip()
        if s:
            out[k] = s
    return out


def _valid_flags(value, state: dict, rejected: list) -> dict:
    if not isinstance(value, dict):
        _reject(rejected, "flag_set", value, "must be {name: scalar}")
        return {}
    flags = state.get("flags") if isinstance(state.get("flags"), dict) else {}
    out = {}
    for name, val in value.items():
        name = str(name).strip()
        if not name:
            continue
        if not isinstance(val, (bool, int, float, str)) or val is None:
            _reject(rejected, f"flag_set:{name}", val, "flag values must be scalars")
            continue
        # Type stability: once a flag exists, its type never changes (a rule that
        # checked a bool must not silently start seeing a string).
        old = flags.get(name)
        if old is not None and _flag_kind(old) != _flag_kind(val):
            _reject(rejected, f"flag_set:{name}", val,
                    f"type change ({_flag_kind(old)} -> {_flag_kind(val)}) not allowed")
            continue
        out[name] = val
    return out


def _md_scalar(raw: str):
    """The natural scalar an authored attribute line carries ('true', '42',
    '3.5', prose) — lets a `persist` write be type-checked against the entry's
    Markdown baseline. Non-ASCII text is never coerced (int()/float() would
    accept Unicode digits no author meant as a number)."""
    s = str(raw or "").strip()
    if not s.isascii():
        return s
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def _persist_current(state: dict, entry, attr: str):
    """The current effective value of a persistent attribute: the engine-tracked
    record when one exists, else the entry's Markdown baseline (None = never
    set anywhere, so the first persist write is type-free)."""
    recs = state.get("persistent")
    if isinstance(recs, dict):
        slot = recs.get(entry.slug)
        if isinstance(slot, dict):
            rec = slot.get(attr)
            if isinstance(rec, dict) and "value" in rec:
                return rec["value"]
    raw = str(entry.attrs.get(attr, "") or "")
    return _md_scalar(raw) if raw.strip() else None


def _valid_persist(value, store, state: dict, rejected: list) -> dict:
    """persist legality (D-216 §3): {slug: {attr: scalar}} where the slug must
    exist and EVERY attr must be declared on its entry via a `persistent:` line.
    The delta vocabulary stays closed for everything else — only attributes the
    author explicitly marked may be mutated in session. Values are scalars,
    int-clamped to NUM_CAP, and keep the kind of their current value once one
    exists (same stability rule as flags)."""
    if not isinstance(value, dict):
        _reject(rejected, "persist", value, "must be {slug: {attr: scalar}}")
        return {}
    out: dict = {}
    for raw, attrs in value.items():
        slug = _slug(raw)
        if not slug or not isinstance(attrs, dict):
            _reject(rejected, f"persist:{raw}", attrs,
                    "must be {slug: {attr: scalar}}")
            continue
        try:
            entry = next((e for rel in store.index_files()
                          for e in store.entries(rel) if e.slug == slug), None)
        except AttributeError:
            entry = None
        if entry is None:
            _reject(rejected, f"persist:{raw}", attrs, "no such entry")
            continue
        declared = entry.persistent_attrs()
        got: dict = {}
        for attr, val in attrs.items():
            attr = str(attr).strip().lower()
            if not attr:
                continue
            if attr not in declared:
                _reject(rejected, f"persist:{slug}.{attr}", val,
                        f"attribute not declared persistent on '{slug}' "
                        f"(declared: {', '.join(declared) or 'none'})")
                continue
            if not isinstance(val, (bool, int, float, str)) or val is None:
                _reject(rejected, f"persist:{slug}.{attr}", val,
                        "value must be a scalar")
                continue
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                iv = _as_int(val)
                if iv is None:
                    _reject(rejected, f"persist:{slug}.{attr}", val,
                            "value must be a finite number")
                    continue
                val = max(-NUM_CAP, min(NUM_CAP, iv))
            cur = _persist_current(state, entry, attr)
            if cur is not None and _flag_kind(cur) != _flag_kind(val):
                _reject(rejected, f"persist:{slug}.{attr}", val,
                        f"type change ({_flag_kind(cur)} -> "
                        f"{_flag_kind(val)}) not allowed")
                continue
            got[attr] = val
        if got:
            out[slug] = got
    return out


def _valid_items(key: str, value, rejected: list) -> list[dict]:
    """Inventory add/remove items: plain name strings or {slug, qty}
    objects (SPEC-V2 A.1, W3). Normalized to {slug, name, qty} dicts."""
    if not isinstance(value, list):
        _reject(rejected, key, value, "must be a list of names or {slug, qty}")
        return []
    out = []
    for raw in value:
        if isinstance(raw, dict):
            name = str(raw.get("name") or raw.get("slug") or "").strip()
            qty = _as_int(raw.get("qty", 1))
            qty = 1 if qty is None else min(QTY_CAP, max(1, qty))
        else:
            name, qty = str(raw).strip(), 1
        slug = _slug(name)
        if not slug:
            _reject(rejected, key, raw, "item needs a name/slug")
            continue
        out.append({"slug": slug, "name": name, "qty": qty})
    return out


def _held_only(items: list[dict], state: dict, store,
               rejected: list) -> list[dict]:
    """Removal legality: the item must actually be held — in the mirror, or (on
    pre-mirror saves) an items.md entry whose status says held. A model
    'removing' an authored world item must not erase its definition."""
    inv = ((state.get("rpg") or {}).get("inventory")
           if isinstance(state.get("rpg"), dict) else {}) or {}
    try:
        held_md = {e.slug for e in store.entries("items.md")
                   if "held" in str(e.attrs.get("status", "")).lower()}
    except AttributeError:
        held_md = set()
    out = []
    for it in items:
        if it["slug"] in inv or it["slug"] in held_md:
            out.append(it)
        else:
            _reject(rejected, f"inventory_remove:{it['name']}", it["name"],
                    "not held")
    return out


def _valid_equip(key: str, value, state: dict, deltas: dict,
                 rejected: list) -> list[str]:
    """Equip/unequip legality: the item must be in the held-inventory mirror —
    or added by THIS envelope ("you pick up the sword and ready it" is one
    turn; rpg.apply processes inventory_add before equips)."""
    if not isinstance(value, list):
        _reject(rejected, key, value, "must be a list of item names")
        return []
    inv = ((state.get("rpg") or {}).get("inventory")
           if isinstance(state.get("rpg"), dict) else {}) or {}
    adds = deltas.get("inventory_add") if isinstance(deltas, dict) else None
    added = set()
    if isinstance(adds, list):
        for raw in adds:
            name = (raw.get("name") or raw.get("slug", "")) \
                if isinstance(raw, dict) else raw
            s = _slug(name)
            if s:
                added.add(s)
    out = []
    for raw in value:
        slug = _slug(raw)
        entry = inv.get(slug) if isinstance(inv, dict) else None
        if not slug:
            continue
        held = isinstance(entry, dict) and _as_int(entry.get("qty")) not in (None, 0)
        if not held and slug not in added:
            _reject(rejected, f"{key}:{raw}", raw, "not held")
        elif slug not in out:
            out.append(slug)
    return out


def _valid_quests(value, store, state: dict, rejected: list) -> dict:
    """Quest-update legality: the thread must exist and the transition must
    follow the state machine (A.5): inactive -> active -> completed|failed."""
    if not isinstance(value, dict):
        _reject(rejected, "quest_update", value, "must be {slug: state}")
        return {}
    threads = {e.slug for e in store.entries("threads.md")}
    quests = state.get("quests") if isinstance(state.get("quests"), dict) else {}
    out = {}
    for raw, new in value.items():
        slug = _slug(raw)
        new = str(new or "").strip().lower()
        cur = str(quests.get(slug, "inactive")).lower()
        if slug not in threads:
            _reject(rejected, f"quest_update:{raw}", new,
                    "no such thread/quest")
        elif new not in _QUEST_FLOW.get(cur, set()):
            _reject(rejected, f"quest_update:{raw}", new,
                    f"illegal transition ({cur} -> {new})")
        else:
            out[slug] = new
    return out


def _valid_npc_state(value, rejected: list) -> dict:
    """Companion mood/disposition: {slug: {mood, disposition}} strings only."""
    if not isinstance(value, dict):
        _reject(rejected, "npc_state", value, "must be {slug: {mood, disposition}}")
        return {}
    out = {}
    for raw, spec in value.items():
        slug = _slug(raw)
        if not slug or not isinstance(spec, dict):
            _reject(rejected, f"npc_state:{raw}", spec,
                    "must be {slug: {mood, disposition}}")
            continue
        got = {}
        for k in ("mood", "disposition"):
            s = str(spec.get(k, "") or "").strip()
            if s:
                got[k] = s
        if got:
            out[slug] = got
    return out


def _valid_grants(key: str, value, deltas: dict, state: dict,
                  rejected: list) -> list[str]:
    """Level-up grants: only legal while a grant is pending (set by the engine on
    level-up), and never more grants than are pending — the model must not hand
    itself abilities whenever it likes."""
    if not isinstance(value, list):
        _reject(rejected, key, value, "must be a list of names")
        return []
    rpg = state.get("rpg") if isinstance(state.get("rpg"), dict) else {}
    pending = _as_int(rpg.get("pending_grant")) or 0
    names = [str(x).strip() for x in value if str(x).strip()]
    if not names:
        return []
    if pending <= 0:
        _reject(rejected, key, value, "no level-up grant pending")
        return []
    other = deltas.get("title_add" if key == "ability_add" else "ability_add")
    other_n = len([x for x in other if str(x).strip()]) \
        if isinstance(other, list) else 0
    if len(names) + other_n > pending:
        _reject(rejected, key, value,
                f"only {pending} grant(s) pending")
        return []
    return names


def _beats(store) -> list[str]:
    """The pacing list (MemoryStore.beats); tolerant of bare stores in tests."""
    try:
        return store.beats()
    except AttributeError:
        return []


def _valid_events(value, store, rejected: list) -> list[str]:
    """event_fired legality: the rule must exist in events.md and not already
    be consumed (a once-rule can never fire twice)."""
    slugs = value if isinstance(value, list) else [value]
    try:
        rules = {e.slug: e for e in store.event_rules(include_consumed=True)}
    except AttributeError:
        rules = {}
    out: list[str] = []
    for raw in slugs:
        slug = _slug(raw)
        rule = rules.get(slug)
        if rule is None:
            _reject(rejected, f"event_fired:{raw}", raw, "no such event rule")
        elif str(rule.attrs.get("consumed", "")).strip().lower() in \
                ("true", "yes", "1", "on"):
            _reject(rejected, f"event_fired:{raw}", raw, "already consumed")
        elif slug not in out:
            out.append(slug)
    return out


def _valid_reveal(value, store, rejected: list) -> list[str]:
    """Legality for `reveal`: each slug must exist in a registry AND currently be
    hidden — anything else is a hallucinated or double reveal."""
    slugs = value if isinstance(value, list) else [value]
    known: dict[str, bool] = {}
    # threads.md joins the gated registries here: a hidden quest thread is
    # revealable lore too (set_hidden covers it the same way).
    for rel in list(store.gated_registries()) + ["threads.md"]:
        for e in store.entries(rel):
            known.setdefault(e.slug, e.hidden())
    out: list[str] = []
    for raw in slugs:
        slug = _slug(raw)
        if slug not in known:
            _reject(rejected, f"reveal:{raw}", raw, "no such lore entry")
        elif not known[slug]:
            _reject(rejected, f"reveal:{raw}", raw, "entry is not hidden")
        elif slug not in out:
            out.append(slug)
    return out


def _flag_kind(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    return "text"


def apply_world(store, env: dict) -> list[str]:
    """Apply the validated world-level deltas (clock / flags / player location).
    Runs regardless of the RPG toggle — the world exists in every mode. Returns
    human-readable event strings, same surface as rpg.apply."""
    d = (env or {}).get("deltas") or {}
    if not any(k in d for k in _WORLD):
        return []
    events: list[str] = []
    state = store.world_state()

    ta = d.get("time_advance")
    if isinstance(ta, dict) and ta:
        tm = state.get("time")
        if not isinstance(tm, dict):
            tm = state["time"] = {}
        if ta.get("days"):
            try:
                day0 = int(tm.get("day") or 1)
            except (TypeError, ValueError):   # hand-edited/legacy non-numeric day
                day0 = 1
            tm["day"] = max(1, day0) + int(ta["days"])
        if ta.get("phase"):
            tm["phase"] = ta["phase"]
        if ta.get("weather"):
            tm["weather"] = ta["weather"]
        events.append(f"time → {store_clock(state)}")

    fs = d.get("flag_set")
    if isinstance(fs, dict) and fs:
        flags = state.setdefault("flags", {})
        if not isinstance(flags, dict):
            flags = state["flags"] = {}
        for name, val in fs.items():
            flags[name] = val
            events.append(f"flag: {name} = {val}")

    loc = d.get("location")
    if loc:
        player = state.setdefault("player", {})
        if not isinstance(player, dict):
            player = state["player"] = {}
        if player.get("location") != loc:
            player["location"] = loc
            events.append(f"location → {loc}")

    gold = d.get("gold_delta")
    if gold:
        player = state.setdefault("player", {})
        if not isinstance(player, dict):
            player = state["player"] = {}
        have = max(0, (_as_int(player.get("gold")) or 0) + int(gold))
        player["gold"] = have
        events.append(f"gold: {'+' if gold >= 0 else ''}{gold} → {have}")

    qu = d.get("quest_update")
    if isinstance(qu, dict) and qu:
        quests = state.setdefault("quests", {})
        if not isinstance(quests, dict):
            quests = state["quests"] = {}
        for slug, new in qu.items():
            quests[slug] = new
            events.append(f"quest: {slug} → {new}")

    # persist (D-216 §3): engine-tracked durable attributes. Lives at the TOP
    # level of state.json — deliberately outside the rpg block and outside any
    # scene/combat reset — so the value survives scene breaks, combat
    # boundaries, and everything else that recycles ephemeral pools.
    pv = d.get("persist")
    if isinstance(pv, dict) and pv:
        pstate = state.get("persistent")
        if not isinstance(pstate, dict):
            pstate = state["persistent"] = {}
        for slug, attrs in pv.items():
            slot = pstate.setdefault(str(slug), {})
            if not isinstance(slot, dict):
                slot = pstate[str(slug)] = {}
            for attr, val in attrs.items():
                old = slot.get(attr)
                hist = old.get("history") if isinstance(old, dict) else None
                hist = list(hist) if isinstance(hist, list) else []
                hist.append({"who": "director",
                             "when": store_clock(state),
                             "value": val})
                slot[attr] = {"value": val,
                              "history": hist[-PERSIST_HISTORY_CAP:]}
                events.append(f"persist: {slug}.{attr} = {val}")

    steps = d.get("beat_advance")
    if steps:
        beats = _beats(store)
        cur = _as_int(state.get("beat")) or 0
        new = min(cur + int(steps), max(0, len(beats) - 1))
        if new != cur:
            state["beat"] = new
            label = beats[new] if new < len(beats) else "?"
            events.append(f"beat → {new + 1}/{len(beats)}: {label}")

    if events:
        store.set_world_state(state)
    return events


def store_clock(state: dict) -> str:
    """Render a clock string from an (already loaded) state dict — mirrors
    MemoryStore.clock_str but avoids a re-read mid-apply."""
    t = state.get("time", {})
    if not isinstance(t, dict):
        return ""
    parts = []
    if t.get("day") is not None:
        parts.append(f"Day {t['day']}")
    if t.get("phase"):
        parts.append(str(t["phase"]))
    if t.get("weather"):
        parts.append(str(t["weather"]))
    return ", ".join(parts)


def rejection_text(rejected: list[dict]) -> str:
    """The corrective re-ask payload: one line per dropped delta."""
    return "\n".join(f"- {r['delta']}: {r['reason']}" for r in rejected)


def replay_records(store, rpg_cfg, records: list[dict]) -> int:
    """Re-apply logged CLEAN envelopes onto a store (branch rebuild, SPEC-V2
    §4.2). Deterministic: rolls reuse the seed+nonce already in the state.
    Covers world deltas, reveals, once-rule consumption, and rpg mechanics —
    a snapshot restore may have rewound events.md, so a fired once-rule must
    be re-consumed or it could fire twice in the branch. Canon-event entries
    are not rebuilt (context flavor only, never legality-bearing).
    Returns how many envelopes were applied."""
    from . import features
    rpg_mod = features.pro_module("rpg") if features.enabled("rpg") else None
    n = 0
    for rec in records:
        env = rec.get("env")
        if not isinstance(env, dict):
            continue
        apply_world(store, env)
        d = env.get("deltas") or {}
        for slug in d.get("reveal", []):
            try:
                store.set_hidden(slug, False)
            except AttributeError:
                pass
        for slug in d.get("event_fired", []):
            try:
                rule = next((e for e in store.event_rules()
                             if e.slug == slug), None)
                once = rule is not None and \
                    str(rule.attrs.get("once", "")).strip().lower() in \
                    ("true", "yes", "1", "on")
                if once:
                    store.mark_event_consumed(slug)
            except AttributeError:
                pass
        if store.rpg_enabled() and rpg_mod is not None:
            rpg_mod.apply(store, env, rpg_cfg)
        n += 1
    return n


def snapshot_state(store) -> dict:
    """Deep-copy the WHOLE mutable state for the pre-turn undo snapshot — with
    world deltas in play, undo must cover time/flags/location, not just the rpg
    block (SPEC-V2 §1.4: every applied delta is reversible)."""
    return copy.deepcopy(store.world_state())
