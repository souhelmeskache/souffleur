"""Phase 4: optional RPG mechanics module (per-story toggle, off by default).

Design invariants (see ROADMAP.md "Phase 4" + HANDOFF.md):
- **Dice are engine-rolled, never LLM-rolled.** The narrator proposes a structured
  sidecar ({check, deltas}); this module rolls deterministically and applies the
  result. Rolls are reproducible: a per-roll seed = (story seed, roll counter).
- **Live numbers live in `state.json`** under an `rpg` block, next to the clock.
- **Single-pass turn flow.** The narrator streams prose and appends a fenced ```rpg
  sidecar. The engine hides the sidecar from the reader, resolves it after the turn,
  and feeds the outcome back via context on the *next* turn ("Last check: ...").
- When `enabled` is false, this module is inert and the narrative engine is unchanged.

Markdown stays the source of truth: inventory lives on `items.md`, companions on
`characters.md`, quests on `threads.md`. Only the mutable numbers (HP/mana/XP/level/
stats/trust/enemy HP/last-check) are mirrored into `state.json`.
"""
from __future__ import annotations

import json
import random
import re

# Open-core split (2026-07-05): the sidecar channel + state-block defaults are
# CORE (coderain.sidecar) — the free engine filters ```rpg leaks and keeps
# state.json shape-stable without this module. Re-exported here so existing
# imports (engine internals, tests) keep working.
from ..sidecar import (DEFAULT_CFG, SIDECAR_MARKER,          # noqa: F401
                      _FENCE_RE, _JSON_RE, _first_json_object,
                      _partial_tail, cfg_get, default_block,
                      filter_sidecar, parse_sidecar, strip_sidecar)
# fold_skill/skill_trained are CORE (validator.py never imports this optional
# module back — one-directional, no cycle): I-213 needs the SAME
# accent/case-fold and the same "on the actor's own sheet" definition of
# 'trained' on both sides of the guichet (validate() legality check here,
# apply() bonus + `trained` readout).
from ..validator import fold_skill, known_skills, skill_trained  # noqa: F401

# Death-save rule (D-271 §1, straight 5e): d20, no modifier, success >= DC;
# 3 successes -> stabilized, 3 failures -> dead.
DEATH_SAVE_DC = 10
DEATH_SAVE_TARGET = 3


# --- dice (deterministic) ---
def win_chance(mod: int, dc: int) -> float:
    """P(d20 + mod >= dc). Faces in [1,20] uniform; no crit rules."""
    faces = 21 - dc + mod          # count of faces r with r+mod >= dc
    return max(0, min(20, faces)) / 20.0


def skill_mod(store, actor_slug: str, skill_name: str,
              cfg: dict | None = None) -> int:
    """Tiered skill bonus: a flat proficiency bonus if `actor_slug` is trained in
    `skill_name`, else 0. Skills are descriptive by default (they guide the writer);
    when a check names one they become this mechanical modifier. Reads the actor's
    entry from Markdown (source of truth): the player from `player.md`, an NPC by
    slug from `characters.md`. Returns 0 when the skill/actor is absent."""
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
    # Wave 3: granted abilities count as trained skills for the bonus.
    for sname, _stat in target.skills() + target.abilities():
        if fold_skill(sname) == name:
            return _as_int(cfg_get(cfg, "skill_bonus"), 2)
    return 0


def roll_check(mod: int, dc: int, seed: int, nonce: int) -> dict:
    """Roll d20 + mod vs dc using a per-roll seed so it's reproducible & testable."""
    rng = random.Random(f"{seed}-{nonce}")
    roll = rng.randint(1, 20)
    total = roll + mod
    return {
        "dc": int(dc), "mod": int(mod), "roll": roll, "total": total,
        "success": total >= dc, "win_chance": win_chance(mod, dc),
    }


# I-206: a stat block's `degats` field is a free 5e-flavored string, e.g.
# "9 (1d8+3) slashing" (see coderain/converter/annexe_a.py REQUIRED_STATS,
# docs/annexe-a-stats-5e.md c7) — the dice notation is the parenthesized part.
# Matching anywhere in the input (not anchored) lets a caller pass either the
# bare formula ("1d8+3") or the whole fiche field without pre-extracting it.
_DICE_RE = re.compile(r"(\d+)\s*d\s*(\d+)\s*([+-]\s*\d+)?", re.IGNORECASE)
_DICE_COUNT_CAP = 100     # generous for any 5e formula; bounds a hostile input
_DICE_FACES_CAP = 1000


def roll_damage(formula: str, seed: int, nonce: int) -> dict:
    """Roll a damage formula ('1d8+3', or a fiche's full 'degats' field like
    '9 (1d8+3) slashing') using the same reproducible per-roll seed as
    roll_check. The LLM never rolls damage either — it proposes the formula
    from a stat block, this rolls it.

    Returns {formula, dice: [faces...], modifier, total} (total floored at 0 —
    damage never goes negative). Raises ValueError on a formula with no
    recognizable 'NdM[+-]K' dice notation, or one outside sane bounds — the
    caller should surface that, not guess a number."""
    m = _DICE_RE.search(str(formula or ""))
    if m is None:
        raise ValueError(f"malformed damage formula: {formula!r} (expected 'NdM[+-]K')")
    count, faces = int(m.group(1)), int(m.group(2))
    modifier = int(m.group(3).replace(" ", "")) if m.group(3) else 0
    if not (1 <= count <= _DICE_COUNT_CAP) or not (1 <= faces <= _DICE_FACES_CAP):
        raise ValueError(f"damage formula out of range: {formula!r}")
    rng = random.Random(f"{seed}-{nonce}-damage")
    dice = [rng.randint(1, faces) for _ in range(count)]
    total = max(0, sum(dice) + modifier)
    return {"formula": str(formula).strip(), "dice": dice, "modifier": modifier,
            "total": total}


# --- downed / death saves (I-213, D-271 §1) ---
def _hp_zero_damage_failure(player: dict, events: list[str], crit: bool) -> None:
    """5e: damage taken while already downed at 0 HP is an automatic
    death-save failure — two on a critical hit. Breaks `stabilized` back into
    active risk first (RAW: a stable creature that takes damage stops being
    stable and resumes rolling); a no-op once `dead` (defensive — the guichet
    already refuses any hp_delta on a dead player, see validator.py's
    `_PLAYER_MUTATING_DELTAS` lock, before this is ever reached)."""
    conditions = player.setdefault("conditions", [])
    if "dead" in conditions:
        return
    if "stabilized" in conditions:
        conditions.remove("stabilized")
        events.append("condition: -stabilized (damage while at 0 HP)")
    ds = player.setdefault("death_saves", {"successes": 0, "failures": 0})
    n = 2 if crit else 1
    ds["failures"] = min(DEATH_SAVE_TARGET, ds["failures"] + n)
    events.append(f"death save: automatic failure ×{n} (damage at 0 HP) "
                  f"→ {ds['failures']}/{DEATH_SAVE_TARGET}")
    if ds["failures"] >= DEATH_SAVE_TARGET:
        if "downed" in conditions:
            conditions.remove("downed")
        if "dead" not in conditions:
            conditions.append("dead")
        events.append("condition: +dead")


def death_save(store, cfg: dict | None = None) -> dict:
    """Resolve ONE death saving throw for the player (D-271 §1, straight 5e):
    d20, no modifier, success >= DEATH_SAVE_DC (10). 3 successes -> stabilized
    (stays at 0 HP, unconscious, no further rolls); 3 failures -> dead. A
    natural 20 restores 1 HP and clears `downed`/`stabilized`, resetting the
    counters; a natural 1 counts as TWO failures.

    Engine-rolled, deterministic — same seed+nonce discipline as roll_check;
    the LLM never rolls this either. Refuses (returns {"error": ...}) when
    RPG is off, or the player isn't `downed`, is already `stabilized` (no
    more rolls once stable), or already `dead`.

    Writes state.json directly via store.set_rpg_state — D-141's one write
    point (guard_world_state still runs on every write). Like roll_check's
    nonce bookkeeping, this does NOT append to events.jsonl: a raw death save
    isn't itself an undo/branch-replayed envelope (same precedent, same
    limit) — the pre-turn snapshot (validator.snapshot_state) still covers it
    for undo_last, since it deep-copies the whole world_state including rpg.
    """
    rpg = store.rpg_state()
    if not rpg.get("enabled"):
        return {"error": "rpg is not enabled for this story"}
    player = rpg.setdefault("player", {})
    conditions = player.setdefault("conditions", [])
    if "dead" in conditions:
        return {"error": "player is dead"}
    if "downed" not in conditions:
        return {"error": "player is not downed — no death save to make"}
    if "stabilized" in conditions:
        return {"error": "player is stabilized — no further death saves"}

    ds = player.setdefault("death_saves", {"successes": 0, "failures": 0})
    nonce = _as_int(rpg.get("rolls", 0))
    rpg["rolls"] = nonce + 1
    rng = random.Random(f"{_as_int(rpg.get('seed', 0))}-{nonce}-death")
    roll = rng.randint(1, 20)
    transition = None

    if roll == 20:
        cap = max(1, _as_int(player.get("hp_max", 1)))
        player["hp"] = min(1, cap)
        conditions[:] = [c for c in conditions if c not in ("downed", "stabilized")]
        ds["successes"], ds["failures"] = 0, 0
        outcome, transition = "natural 20 — revived at 1 HP, downed cleared", "revived"
    else:
        if roll == 1:
            ds["failures"] = min(DEATH_SAVE_TARGET, ds["failures"] + 2)
            outcome = "natural 1 — two failures"
        elif roll >= DEATH_SAVE_DC:
            ds["successes"] = min(DEATH_SAVE_TARGET, ds["successes"] + 1)
            outcome = "success"
        else:
            ds["failures"] = min(DEATH_SAVE_TARGET, ds["failures"] + 1)
            outcome = "failure"
        if ds["failures"] >= DEATH_SAVE_TARGET:
            conditions[:] = [c for c in conditions if c not in ("downed", "stabilized")]
            if "dead" not in conditions:
                conditions.append("dead")
            transition = "dead"
        elif ds["successes"] >= DEATH_SAVE_TARGET:
            if "stabilized" not in conditions:
                conditions.append("stabilized")
            transition = "stabilized"

    player["death_saves"] = ds
    store.set_rpg_state(rpg)
    return {
        "roll": roll, "dc": DEATH_SAVE_DC, "outcome": outcome,
        "death_saves": dict(ds), "transition": transition,
        "hp": player.get("hp"), "conditions": list(conditions),
    }


# --- sidecar extraction ---
# --- applying a validated sidecar ---
def _item_spec(spec) -> tuple[str, str, int]:
    """Normalize an inventory item ({slug|name, qty} dict or plain string,
    both shapes reach here) to (slug, display name, qty>=1)."""
    from ..templates import slugify
    if isinstance(spec, dict):
        name = str(spec.get("name") or spec.get("slug") or "").strip()
        qty = max(1, _as_int(spec.get("qty", 1), 1) or 1)
    else:
        name, qty = str(spec).strip(), 1
    return slugify(name) if name else "", name, qty


def _write_player_grants(store, player: dict) -> None:
    """Mirror granted abilities/titles back into player.md — md wins on every
    open, so a grant that lived only in state.json would be erased by the next
    sync. Best-effort: a malformed file never blocks the turn."""
    from ..memory import Entry  # noqa: F401  (local import, avoids cycle)
    try:
        entries = store.entries("player.md")
        target = next((e for e in entries if e.slug == "player"),
                      entries[0] if entries else None)
        if target is None:
            return
        changed = False
        for attr in ("abilities", "titles"):
            lst = player.get(attr) or []
            line = ", ".join(lst)
            if lst and target.attrs.get(attr, "") != line:
                target.attrs[attr] = line
                changed = True
        if changed:
            store.upsert_entry("player.md", target)
    except Exception:  # noqa: BLE001
        pass


def _mirror_stub(store, slug: str) -> bool:
    """True when the items.md entry for `slug` is a mirror-created held-item stub
    (status contains 'held by you') — the only entries rpg.apply may delete."""
    entry = next((e for e in store.entries("items.md") if e.slug == slug), None)
    return entry is not None and \
        "held by you" in str(entry.attrs.get("status", "")).lower()


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


_ENEMY_HP_CAP = 100_000     # generous for a boss, bounded so no unkillable enemy


def _as_int(v, default=0) -> int:
    try:
        if isinstance(v, bool):
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def apply(store, sidecar: dict, cfg: dict | None = None) -> list[str]:
    """Resolve a sidecar against the story's rpg state + Markdown files. Returns
    human-readable event strings (surfaced in the UI like fold events). Deterministic;
    no LLM calls. No-op (returns []) when RPG is disabled for this story."""
    from ..memory import Entry  # local import: memory.py must not depend on rpg.py
    from ..templates import slugify

    rpg = store.rpg_state()
    if not rpg.get("enabled"):
        return []
    if not isinstance(sidecar, dict):
        return []
    events: list[str] = []
    player = rpg.setdefault("player", {})
    player.setdefault("conditions", [])

    # 1) skill check (engine-rolled). Optional "actor": an NPC slug — the check
    # then uses THAT character's `stats:`/`skills:` from characters.md (Markdown is
    # the baseline source of truth); default/unknown actor = the player.
    chk = sidecar.get("check")
    if isinstance(chk, dict) and chk.get("stat"):
        stat = str(chk.get("stat", "")).strip().lower()
        dc = _clamp(_as_int(chk.get("dc"), int(cfg_get(cfg, "default_dc"))), 1, 40)
        actor = slugify(str(chk.get("actor", "")).strip()) or "player"
        if actor != "player":
            npc = next((e for e in store.entries("characters.md")
                        if e.slug == actor), None)
            actor_stats = npc.stats() if npc is not None else {}
            if npc is None:
                actor = "player"          # unknown slug: fall back to the player
        if actor == "player":
            actor_stats = player.get("stats", {})
        mod = _as_int(actor_stats.get(stat, 0))
        # Tiered skill bonus: if the check names a skill the actor is trained in,
        # add its flat proficiency bonus on top of the governing stat.
        skill = str(chk.get("skill", "")).strip()
        sk_mod = skill_mod(store, actor, skill, cfg) if skill else 0
        mod += sk_mod
        nonce = _as_int(rpg.get("rolls", 0))
        rpg["rolls"] = nonce + 1
        res = roll_check(mod, dc, _as_int(rpg.get("seed", 0)), nonce)
        res["stat"] = stat
        if skill:
            res["skill"] = skill
            res["trained"] = skill_trained(store, actor, skill)
        if actor != "player":
            res["actor"] = actor
        rpg["last_check"] = res
        label = f"{stat}+{skill}" if (skill and sk_mod) else stat
        who = "" if actor == "player" else f"{actor}: "
        events.append(
            f"check: {who}{label} vs DC{dc} → d20 {res['roll']}{mod:+d}={res['total']} "
            f"{'SUCCESS' if res['success'] else 'FAIL'} "
            f"({round(res['win_chance'] * 100)}% chance)"
        )

    # 2) state deltas
    d = sidecar.get("deltas")
    if isinstance(d, dict):
        # HP / mana (clamped to [0, max])
        for pool, mx in (("hp", "hp_max"), ("mana", "mana_max")):
            delta = _as_int(d.get(f"{pool}_delta"))
            if delta:
                cap = _as_int(player.get(mx, player.get(pool, 0)))
                # D-271 §1: damage received while already downed at 0 HP is an
                # automatic death-save failure (two on a crit), not a second
                # trip below 0 — read BEFORE the clamp below overwrites hp.
                damage_at_zero = (
                    pool == "hp" and delta < 0
                    and _as_int(player.get("hp", 0)) <= 0
                    and "downed" in player["conditions"]
                    and "dead" not in player["conditions"]
                )
                cur = _clamp(_as_int(player.get(pool, 0)) + delta, 0, cap)
                player[pool] = cur
                events.append(f"{pool}: {'+' if delta >= 0 else ''}{delta} → {cur}/{cap}")
                if pool == "hp":
                    if damage_at_zero:
                        _hp_zero_damage_failure(player, events,
                                                crit=bool(d.get("hp_delta_crit")))
                    # "downed" is auto-managed symmetrically: set at 0, cleared on heal.
                    elif cur == 0 and "downed" not in player["conditions"]:
                        player["conditions"].append("downed")
                        events.append("condition: +downed")
                    elif cur > 0 and "downed" in player["conditions"]:
                        player["conditions"].remove("downed")
                        if "stabilized" in player["conditions"]:
                            player["conditions"].remove("stabilized")
                        player["death_saves"] = {"successes": 0, "failures": 0}
                        events.append("condition: -downed")

        # XP + level-up. `per` is clamped >=1 so a bad config (0/negative/blank ->
        # int() -> 0) can't turn the threshold loop into an infinite loop; XP floors
        # at 0 so a negative delta can't desync the sheet.
        xp_delta = _as_int(d.get("xp_delta"))
        if xp_delta:
            player["xp"] = max(0, _as_int(player.get("xp", 0)) + xp_delta)
            per = max(1, _as_int(cfg_get(cfg, "xp_per_level"), 100))
            hp_gain = _as_int(cfg_get(cfg, "hp_per_level"), 5)
            mana_gain = _as_int(cfg_get(cfg, "mana_per_level"), 2)
            events.append(f"xp: {'+' if xp_delta >= 0 else ''}{xp_delta} → {player['xp']}")
            while player["xp"] >= player.get("level", 1) * per:
                player["xp"] -= player.get("level", 1) * per
                player["level"] = player.get("level", 1) + 1
                player["hp_max"] = _as_int(player.get("hp_max", 0)) + hp_gain
                player["mana_max"] = _as_int(player.get("mana_max", 0)) + mana_gain
                player["hp"], player["mana"] = player["hp_max"], player["mana_max"]
                # Wave 3: each level banks one ability/title grant the Logic
                # Agent may spend via ability_add / title_add (validator-gated).
                rpg["pending_grant"] = _as_int(rpg.get("pending_grant")) + 1
                events.append(f"level up → {player['level']} "
                              "(HP/mana restored; new ability or title pending)")

        # Wave 3 level-up grants (validator already checked pending_grant).
        # Written to the state list AND back into player.md — md wins on every
        # open, so a grant that skipped md would be erased by the next sync.
        granted = False
        for key in ("ability_add", "title_add"):
            attr = "abilities" if key == "ability_add" else "titles"
            for name in d.get(key, []) or []:
                name = str(name).strip()
                if not name:
                    continue
                lst = player.setdefault(attr, [])
                label = attr[:-1] if attr != "abilities" else "ability"
                if name in lst:
                    # Re-proposing a known ability must not burn the grant.
                    events.append(f"{label}: {name} already known (grant kept)")
                    continue
                lst.append(name)
                rpg["pending_grant"] = max(0, _as_int(rpg.get("pending_grant")) - 1)
                granted = True
                events.append(f"{label}: +{name}")
        if granted:
            _write_player_grants(store, player)

        # status conditions
        for name in d.get("status_add", []) or []:
            name = str(name).strip().lower()
            if name and name not in player["conditions"]:
                player["conditions"].append(name)
                events.append(f"condition: +{name}")
        for name in d.get("status_remove", []) or []:
            name = str(name).strip().lower()
            if name in player["conditions"]:
                player["conditions"].remove(name)
                events.append(f"condition: -{name}")

        # inventory: definitions on items.md (Markdown stays source of truth),
        # the mutable {qty, equipped} mirror in the rpg block (Wave 3).
        inv = rpg.setdefault("inventory", {})
        for spec in d.get("inventory_add", []) or []:
            slug, name, qty = _item_spec(spec)
            if not slug:
                continue
            cur = inv.setdefault(slug, {"qty": 0, "equipped": False})
            cur["qty"] = _as_int(cur.get("qty")) + qty
            # Don't clobber an authored/existing item's attrs (e.g. its `status:`);
            # only create a fresh held entry when the item isn't already on items.md.
            if not any(e.slug == slug for e in store.entries("items.md")):
                store.merge_entry("items.md", Entry(
                    title=name, slug=slug, importance=2,
                    attrs={"status": "held by you"},
                    body=f"{name} — carried by you."))
            events.append(f"item: +{name}" + (f" ×{qty}" if qty > 1 else ""))
        for spec in d.get("inventory_remove", []) or []:
            slug, name, qty = _item_spec(spec)
            if not slug:
                continue
            cur = inv.get(slug)
            if cur is not None:
                cur["qty"] = max(0, _as_int(cur.get("qty")) - qty)
                if cur["qty"] <= 0:
                    inv.pop(slug, None)
                    # Only a mirror-created held stub leaves items.md with it —
                    # an authored definition (lore, rarity, links) outlives the
                    # player letting go of the object.
                    if _mirror_stub(store, slug):
                        store.remove_entry("items.md", slug)
                events.append(f"item: -{name}" + (f" ×{qty}" if qty > 1 else ""))
            elif _mirror_stub(store, slug) and store.remove_entry("items.md", slug):
                events.append(f"item: -{name}")   # pre-mirror held stub
        for slug in d.get("inventory_equip", []) or []:
            cur = inv.get(slugify(str(slug)))
            if cur is not None and not cur.get("equipped"):
                cur["equipped"] = True
                events.append(f"equipped: {slug}")
        for slug in d.get("inventory_unequip", []) or []:
            cur = inv.get(slugify(str(slug)))
            if cur is not None and cur.get("equipped"):
                cur["equipped"] = False
                events.append(f"unequipped: {slug}")

        # companion trust
        trust = d.get("trust")
        if isinstance(trust, dict):
            comps = rpg.setdefault("companions", {})
            for slug, delta in trust.items():
                slug = slugify(str(slug))
                delta = _as_int(delta)
                if not slug or not delta:
                    continue
                c = comps.setdefault(slug, {"trust": 0})
                c["trust"] = _clamp(_as_int(c.get("trust", 0)) + delta, -100, 100)
                events.append(f"trust: {slug} {'+' if delta >= 0 else ''}{delta} → {c['trust']}")

        # companion mood/disposition (Wave 3; validated shape)
        ns = d.get("npc_state")
        if isinstance(ns, dict):
            comps = rpg.setdefault("companions", {})
            for slug, spec in ns.items():
                slug = slugify(str(slug))
                if not slug or not isinstance(spec, dict):
                    continue
                c = comps.setdefault(slug, {"trust": 0})
                changed = []
                for k in ("mood", "disposition"):
                    val = str(spec.get(k, "") or "").strip()
                    if val and c.get(k) != val:
                        c[k] = val
                        changed.append(f"{k}={val}")
                if changed:
                    events.append(f"npc: {slug} " + " ".join(changed))

        # enemies (ephemeral stat entries; die at HP 0)
        enemies = d.get("enemies")
        if isinstance(enemies, dict):
            ens = rpg.setdefault("enemies", {})
            for slug, spec in enemies.items():
                if not isinstance(spec, dict):
                    continue
                slug = slugify(str(slug))
                if not slug:
                    continue
                e = ens.get(slug)
                # Cap enemy HP: a hallucinated/huge hp_max would be an unkillable
                # enemy that soft-locks combat (the delta pools are already capped).
                if e is None:
                    hp_max = _clamp(_as_int(spec.get("hp_max", spec.get("hp", 10)),
                                            10), 1, _ENEMY_HP_CAP)
                    e = {"hp": hp_max, "hp_max": hp_max}
                if "hp_max" in spec:
                    e["hp_max"] = _clamp(_as_int(spec.get("hp_max"), e["hp_max"]),
                                         1, _ENEMY_HP_CAP)
                dmg = _as_int(spec.get("hp_delta"))
                if dmg:
                    e["hp"] = _clamp(_as_int(e.get("hp", e["hp_max"])) + dmg, 0, e["hp_max"])
                if e["hp"] <= 0:
                    ens.pop(slug, None)
                    events.append(f"enemy: {slug} defeated")
                else:
                    ens[slug] = e
                    events.append(f"enemy: {slug} HP {e['hp']}/{e['hp_max']}")

    store.set_rpg_state(rpg)
    return events


# --- rendering (context for the narrator + player display) ---
def render_sheet_lines(rpg: dict, world: dict | None = None) -> str:
    """The sheet as a vertical read-out — every value on its own line. Used by the
    GUI's pinned side panel; the CLI keeps the compact render_sheet(). Pass the
    world state to prepend the clock / weather / location (Wave 1)."""
    head: list[str] = []
    if isinstance(world, dict):
        t = world.get("time", {})
        if isinstance(t, dict):
            if t.get("day") is not None:
                head.append(f"Day    {t['day']}")
            if t.get("phase"):
                head.append(f"Time   {t['phase']}")
            if t.get("weather"):
                head.append(f"Sky    {t['weather']}")
        loc = (world.get("player") or {}).get("location", "") \
            if isinstance(world.get("player"), dict) else ""
        if loc:
            head.append(f"Place  {loc}")
        if head:
            head.append("")
    p = rpg.get("player", {})
    lines = head + [
        f"HP     {p.get('hp', '?')}/{p.get('hp_max', '?')}",
        f"Mana   {p.get('mana', '?')}/{p.get('mana_max', '?')}",
        f"Level  {p.get('level', 1)}",
        f"XP     {p.get('xp', 0)}",
    ]
    stats = p.get("stats", {})
    if stats:
        lines.append("")
        lines.append("— Stats —")
        lines += [f"{k.title():<13}{v:+d}" for k, v in stats.items()]
    gold = ((world or {}).get("player") or {}).get("gold") \
        if isinstance((world or {}).get("player"), dict) else None
    if gold is not None:
        lines.append(f"Gold   {gold}")
    if p.get("abilities"):
        lines.append("")
        lines.append("— Abilities —")
        lines += list(p["abilities"])
    if p.get("titles"):
        lines.append("")
        lines.append("— Titles —")
        lines += list(p["titles"])
    if p.get("conditions"):
        lines.append("")
        lines.append("— Conditions —")
        lines += list(p["conditions"])
    inv = rpg.get("inventory", {})
    if inv:
        lines.append("")
        lines.append("— Inventory —")
        lines += [f"{s} ×{it.get('qty', 1)}"
                  + ("  [E]" if it.get("equipped") else "")
                  for s, it in inv.items()]
    comps = rpg.get("companions", {})
    if comps:
        lines.append("")
        lines.append("— Companions —")
        for s, c in comps.items():
            lines.append(f"{s}  (trust {c.get('trust', 0)})")
            extra = "/".join(x for x in (c.get("mood"), c.get("disposition")) if x)
            if extra:
                lines.append(f"  {extra}")
    quests = (world or {}).get("quests") \
        if isinstance((world or {}).get("quests"), dict) else {}
    active = [s for s, st in (quests or {}).items() if st == "active"]
    if active:
        lines.append("")
        lines.append("— Quests —")
        lines += active
    ens = rpg.get("enemies", {})
    if ens:
        lines.append("")
        lines.append("— Enemies —")
        lines += [f"{s}  HP {e.get('hp')}/{e.get('hp_max')}" for s, e in ens.items()]
    lc = rpg.get("last_check")
    if isinstance(lc, dict):
        lines.append("")
        lines.append("— Last check —")
        who = f"{lc.get('actor')}: " if lc.get("actor") else ""
        lines.append(f"{who}{lc.get('stat')} vs DC{lc.get('dc')}")
        lines.append(f"rolled {lc.get('total')} → "
                     f"{'SUCCESS' if lc.get('success') else 'FAIL'}")
    return "\n".join(lines)


def render_sheet(rpg: dict, world: dict | None = None) -> str:
    p = rpg.get("player", {})
    lines = [
        f"HP {p.get('hp', '?')}/{p.get('hp_max', '?')}   "
        f"Mana {p.get('mana', '?')}/{p.get('mana_max', '?')}   "
        f"Level {p.get('level', 1)} (XP {p.get('xp', 0)})",
    ]
    stats = p.get("stats", {})
    if stats:
        lines.append("Stats: "
                     + ", ".join(f"{k.title()} {v:+d}" for k, v in stats.items()))
    if p.get("abilities"):
        lines.append("Abilities: " + ", ".join(p["abilities"]))
    if p.get("titles"):
        lines.append("Titles: " + ", ".join(p["titles"]))
    if p.get("conditions"):
        lines.append("Conditions: " + ", ".join(p["conditions"]))
    wp = (world or {}).get("player")
    if isinstance(wp, dict) and wp.get("gold") is not None:
        lines.append(f"Gold: {wp.get('gold')}")
    inv = rpg.get("inventory", {})
    if inv:
        lines.append("Inventory: "
                     + ", ".join(f"{s} ×{it.get('qty', 1)}"
                                 + (" [equipped]" if it.get("equipped") else "")
                                 for s, it in inv.items()))
    quests = (world or {}).get("quests")
    if isinstance(quests, dict):
        active = [s for s, st in quests.items() if st == "active"]
        if active:
            lines.append("Active quests: " + ", ".join(active))
    comps = rpg.get("companions", {})
    if comps:
        lines.append("Companions: "
                     + ", ".join(f"{s} (trust {c.get('trust', 0)}"
                                 + (f", {c['mood']}" if c.get("mood") else "")
                                 + ")"
                                 for s, c in comps.items()))
    ens = rpg.get("enemies", {})
    if ens:
        lines.append("Enemies: "
                     + ", ".join(f"{s} (HP {e.get('hp')}/{e.get('hp_max')})"
                                 for s, e in ens.items()))
    return "\n".join(lines)


def context_block(store, prompt_narrate: bool = True) -> str:
    """The live sheet + last-check outcome, injected into the narrator when enabled.
    `prompt_narrate=False` (quad mode) keeps the last check as plain info — the
    outcome was already narrated the turn it was rolled."""
    rpg = store.rpg_state()
    if not rpg.get("enabled"):
        return ""
    out = render_sheet(rpg, store.world_state())
    lc = rpg.get("last_check")
    if isinstance(lc, dict):
        out += (f"\nLast check: {lc.get('stat')} vs DC{lc.get('dc')} → "
                f"{'SUCCESS' if lc.get('success') else 'FAILURE'} "
                f"(rolled {lc.get('total')})."
                + (" Narrate this result now." if prompt_narrate else ""))
    pending = _as_int(rpg.get("pending_grant"))
    if pending > 0:
        out += (f"\nLEVEL-UP PENDING: {pending} grant(s) unspent — propose ONE "
                "new ability (`ability_add: [\"name (stat)\"]`) or title "
                "(`title_add`) that fits how the character has been played.")
    return out
