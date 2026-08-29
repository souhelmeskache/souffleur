"""The Quad pipeline (SPEC-V2 §1.1) — an opt-in multi-brain turn loop.

    Memory Manager  →  Logic Agent  →  Backend Validator  →  Narrator
      (code-first)      (Director)        (code, never       (Writer)
                                            an LLM)

- **Memory Manager** is code-first: context assembly (alias-gating, budget,
  retrieval) is deterministic and free. The Lore-keeper LLM pass — verify the plan
  against memory with lookup tools — is OPTIONAL (`trinity: lorekeeper: llm_pass:
  true`), for ambiguity checks on profiles where an extra call is cheap.
- **Logic Agent (Director)** decides what mechanically happens this turn and
  PROPOSES it as a v1 envelope (SPEC-V2 A.1): a check plus deltas. It never rolls
  dice and never writes prose.
- **Backend Validator** is pure code (`validator.py` via the engine's
  `apply_envelope`): schema + legality, one corrective re-ask on rejects, then the
  clean envelope is APPLIED — dice rolled, world deltas committed, events logged —
  BEFORE the Writer runs, so the prose narrates what actually happened.
- **Narrator (Writer)** streams prose only, with the plan + resolved mechanics
  injected as a POST-history instruction (instructions after the history bind
  hardest).

Single-brain stays the default; this runs only when generation.trinity_brain is
on. Recommended stage models (config `trinity:` block): lorekeeper = fast/cheap,
director = standard (reasoning model for tactical/branching stories), writer =
your best prose model.
"""
from __future__ import annotations

import json
import time

from . import rpg as rpg_mod
from .. import validator as validator_mod
from ..llm import LLM, PROSE_MIN_TOKENS, emit_json_ex, extract_json

DIRECTOR_SYS = """\
You are the LOGIC AGENT (director) of an interactive story. Given the story context
and the player's latest action, decide what happens THIS turn. Do not write prose.
Plan the beat, list what must stay consistent, and note anything to verify in memory.

CONVERSATION D'ACCORD (protocole des 4 fenêtres, D-219)

Certaines parties commencent par une conversation d'accord en 4 fenêtres
(origine, posture sociale, lien de tension, enjeu personnel) : le joueur
choisit ou reformule un trait de son personnage fenêtre par fenêtre. Cette
phase est gérée par un outillage dédié, pas par toi — si le contexte
indique qu'une conversation B est en cours, ne planifie AUCUN beat
mécanique (pas de check, pas de deltas) : ta seule tâche est de laisser la
phase se dérouler et de reprendre le planning normal une fois close.

Une fois la conversation d'accord close, tu reçois les jalons de destinée
acquis (passé/intention flous, jamais un événement futur — D-220) comme
des faits acquis à ajouter à must_stay_consistent au même titre que
n'importe quel autre fait de mémoire : ne les recrée jamais, ne les
contredis jamais, ne les devance jamais (D-220 : la destinée s'active par
le jeu, pas par anticipation de ta part).

Chaque trait acquis porte un statut invisible — négociable (le joueur l'a
choisi librement parmi des variantes) ou non-négociable (contrainte du
module, rare). Tu ne dois JAMAIS écrire ni laisser deviner ces mots ni
cette distinction — ni dans le beat_plan, ni dans les faits à vérifier.
Ce que tu peux faire, c'est transposer la différence en TONALITÉ narrative
plus tard dans la partie, sans jamais l'expliciter :

  - un trait non-négociable revient avec plus d'inertie : un PNJ peut le
    reconnaître sans qu'on le lui ait dit, un lieu peut y faire écho sans
    qu'on l'ait mentionné, il pèse comme une chose qui était déjà vraie
    avant que l'histoire ne commence — jamais présenté comme un choix.
  - un trait négociable reste un choix parmi d'autres qui aurait pu être
    différent : il peut être questionné, nuancé, réinterprété par les
    événements sans que cela sonne faux.

Ne cite jamais un identifiant technique (id de node, de tension, de
ressource, de secret, de jalon) dans le beat_plan ou les recall_queries —
seulement les faits en langage naturel qu'ils désignent. Cette règle
prolonge au niveau du planning la garde zéro-spoiler déjà appliquée à la
prose des 4 fenêtres elles-mêmes.

Return ONLY a JSON object:
{
  "beat_plan": "1-3 sentences: what happens this turn as a result of the action",
  "must_stay_consistent": ["specific facts/entities the prose must not contradict"],
  "recall_queries": ["names/keywords/events worth verifying in memory"]%s
}
"""
# The proposal envelope (SPEC-V2 A.1). Dice are engine-rolled; you only PROPOSE.
# World deltas are always available; the mechanics keys join them when RPG is on.
_ENV_WORLD = """,
  "envelope": {"v": 1,
    "deltas": {"time_advance": {"days": 0, "phase": "", "weather": ""},
               "flag_set": {}, "location": "", "reveal": [],
               "event_fired": []}}"""
_ENV_RPG = """,
  "envelope": {"v": 1,
    "check": {"stat": "strength|agility|intelligence|knowledge|willpower|charisma",
              "dc": 5-20, "skill": "optional trained skill",
              "actor": "optional npc slug when the check is theirs"},
    "deltas": {"hp_delta": 0, "mana_delta": 0, "xp_delta": 0, "gold_delta": 0,
               "inventory_add": [{"slug": "torch", "qty": 1}],
               "inventory_remove": [], "inventory_equip": [],
               "inventory_unequip": [],
               "status_add": [], "status_remove": [], "trust": {},
               "npc_state": {"slug": {"mood": "", "disposition": ""}},
               "enemies": {},
               "quest_update": {"thread-slug": "active|completed|failed"},
               "time_advance": {"days": 0, "phase": "", "weather": ""},
               "flag_set": {}, "location": "", "reveal": [],
               "event_fired": [], "beat_advance": false,
               "ability_add": [], "title_add": []}}"""

ENVELOPE_FIX_SYS = """\
You are correcting a proposal envelope for an interactive story engine. Some of its
deltas were rejected by the validator. Return ONLY the corrected envelope JSON object
(the {"v": 1, "check": ..., "deltas": ...} shape) — fix or omit the rejected parts
and keep the valid parts unchanged.
"""

LOREKEEPER_SYS = """\
You are the LORE-KEEPER (continuity). You are given the DIRECTOR'S PLAN and the story
context. Verify the plan against memory — use the lookup_memory and recall_turns tools
when you need a specific detail or the exact wording of an earlier moment. Then return
the facts the writer MUST honor and any correction to the plan.

Return ONLY a JSON object:
{
  "vetted_facts": ["exact facts the writer must honor this turn"],
  "patches": ["corrections to the plan where it would contradict canon (may be empty)"]
}
"""


class TrinityBrain:
    def __init__(self, base, store, config, rpg_cfg, dispatch_tool, tools,
                 apply_envelope=None):
        self.store = store
        self.gen = config.generation
        self.rpg_cfg = rpg_cfg
        self.dispatch = dispatch_tool
        self.tools = tools
        # The engine's Backend Validator seam (validate + apply + event-log). A
        # fallback keeps standalone/test construction working without an engine.
        self._apply_envelope = apply_envelope or self._apply_fallback
        # `base` is a CALLABLE returning the engine's *current* client. Unpinned
        # stages resolve it per call, so swapping engine.llm after construction
        # (tests, Settings rebuild) reaches them — capturing the instance here
        # silently bypassed such swaps (found the hard way: a test stub was ignored
        # and the suite called the live model).
        self._base = base if callable(base) else (lambda: base)
        # Per-stage clients: each stage may pin its own profile (endpoint/key) and/or
        # model via the `trinity:` config block; None = inherit the base client.
        tcfg = config.raw.get("trinity") or {}
        self._director = _stage_llm(config, tcfg.get("director"))
        self._lorekeeper = _stage_llm(config, tcfg.get("lorekeeper"))
        self._writer = _stage_llm(config, tcfg.get("writer"))
        # Memory Manager is code-first (SPEC-V2 §1.1): the per-turn Lore-keeper LLM
        # pass is opt-in — retrieval itself is deterministic assembly, already done.
        lk = tcfg.get("lorekeeper")
        self.lore_llm_pass = bool(lk.get("llm_pass", False)) \
            if isinstance(lk, dict) else False

    # Stage clients resolve to the pinned client or the engine's current base.
    # Setters keep the "swap in a stub" test/debug idiom working.
    @property
    def director_llm(self):
        return self._director or self._base()

    @director_llm.setter
    def director_llm(self, v):
        self._director = v

    @property
    def lorekeeper_llm(self):
        return self._lorekeeper or self._base()

    @lorekeeper_llm.setter
    def lorekeeper_llm(self, v):
        self._lorekeeper = v

    @property
    def writer_llm(self):
        return self._writer or self._base()

    @writer_llm.setter
    def writer_llm(self, v):
        self._writer = v

    def stage_models(self) -> str:
        """One-line engagement banner: which model each stage runs on."""
        def name(client):
            prof = getattr(client, "profile", None)
            return getattr(prof, "model", "?") if prof else "?"
        lore = name(self.lorekeeper_llm) if self.lore_llm_pass else "code"
        return (f"Quad: memory={lore} director={name(self.director_llm)} "
                f"validator=code writer={name(self.writer_llm)}")

    # --- Logic Agent ---
    def _direct(self, messages, rpg_on: bool,
                event_rules: str = "") -> tuple[dict, str | None]:
        schema_tail = _ENV_RPG if rpg_on else _ENV_WORLD
        sys = DIRECTOR_SYS % schema_tail
        # Scenario event rules are DIRECTOR-ONLY (Wave 4): the Writer never sees
        # them, so an unfired trap or twist can't leak into prose.
        if event_rules:
            sys += "\n\n" + event_rules
        # Full assembled context INCLUDING the conversation history — the Director
        # plans the beat, so it must see how the story actually got here.
        director_msgs = [{"role": "system",
                          "content": sys + "\n\n" + messages[0]["content"]},
                         *messages[1:]]
        obj, err = emit_json_ex(self.director_llm, "", messages=director_msgs)
        return obj or {}, err

    def _redirect(self, env: dict, rejected: list) -> dict | None:
        """The Validator's one corrective re-ask: show the Director its rejected
        deltas and get a corrected envelope back. None = re-ask failed."""
        payload = ("REJECTED deltas:\n" + validator_mod.rejection_text(rejected)
                   + "\n\nORIGINAL ENVELOPE:\n" + json.dumps(env))
        obj, _err = emit_json_ex(self.director_llm, ENVELOPE_FIX_SYS, payload,
                                 retry=0)
        if not isinstance(obj, dict):
            return None
        # Accept either the bare envelope or a {"envelope": {...}} wrapper.
        inner = obj.get("envelope")
        return inner if isinstance(inner, dict) else obj

    # --- optional Lore-keeper LLM pass ---
    def _keep_lore(self, messages, plan: dict) -> tuple[dict, str | None]:
        payload = ("DIRECTOR'S PLAN:\n" + _plan_text(plan)
                   + "\n\nSTORY CONTEXT:\n" + messages[0]["content"]
                   + "\n\nPLAYER ACTION:\n" + _tail_user(messages))
        convo = [{"role": "system", "content": LOREKEEPER_SYS},
                 {"role": "user", "content": payload}]
        try:
            raw = self.lorekeeper_llm.complete_with_tools(
                convo, self.tools, self.dispatch)
        except Exception as e:  # noqa: BLE001 — continuity is best-effort, never fatal
            return {}, f"model call failed: {e}"
        obj = extract_json(raw)
        if obj is None:
            return {}, "no valid JSON in lore-keeper output"
        return obj, None

    # --- Narrator ---
    def _writer_context(self, messages: list[dict]) -> list[dict]:
        """The Writer's OWN copy of the assembled context, with the Director-
        only material explicitly retiré (Issue #108) — same vocabulary and
        intent as mcp_server.py's `assemble_context_to_file(event_rules=False,
        secrets=False)` on the director-de-table side:
          - event_rules: needs no strip here — `_direct` above concatenates
            SCENARIO EVENT RULES only into `director_msgs`, a local copy never
            reinjected into `messages`, so this method never receives it in
            the first place. DECLARED behaviour now (this docstring + the
            guard test), not an accident of Python scope.
          - secrets: `store.assemble()` may have appended a "Secrets you know"
            section for the Director; stripped from the Writer's copy below.
        A no-op text-wise when neither ever applied — the common case."""
        if not messages:
            return messages
        stripped = self.store.strip_secrets_section(messages[0]["content"])
        return [{**messages[0], "content": stripped}, *messages[1:]]

    def _writer_messages(self, messages, plan: dict, facts: dict,
                         outcome: list[str]) -> list[dict]:
        directive = _writer_directive(plan, facts, outcome)
        writer_context = self._writer_context(messages)
        # Post-history instruction: appended AFTER the player's action so it carries
        # the most weight on the model's next tokens (the SillyTavern lesson).
        return [*writer_context, {"role": "system", "content": directive}]

    def generate(self, messages, rpg_on: bool, on_stage, out_chunks: list,
                 skip_logic: bool = False, event_rules: str = ""):
        """Run the Quad passes. Yields the Writer's visible prose (also collected
        into `out_chunks` for storage) and RETURNS the list of applied event
        strings — mechanics are validated and RESOLVED before the Writer runs, so
        the prose narrates actual outcomes. Every stage reports timing (and
        failure) via on_stage — a silent stage is indistinguishable from
        single-brain, which is exactly the bug this telemetry exists to catch.
        `skip_logic=True` (Simple Story mode) goes straight to the Narrator."""
        def note(m):
            if on_stage:
                on_stage(m)

        note(self.stage_models())
        plan: dict = {}
        err = None
        if skip_logic:
            note("Simple mode: Logic Agent skipped (prose only)")
        else:
            t0 = time.monotonic()
            note("Director planning")
            plan, err = self._direct(messages, rpg_on, event_rules)
            if err:
                note(f"Director FAILED ({time.monotonic() - t0:.1f}s): {err} — "
                     "continuing without a plan")
            else:
                note(f"Director done ({time.monotonic() - t0:.1f}s)")

        facts: dict = {}
        if self.lore_llm_pass and not skip_logic:
            t1 = time.monotonic()
            note("Continuity check")
            facts, err = self._keep_lore(messages, plan)
            if err:
                note(f"Lore-keeper FAILED ({time.monotonic() - t1:.1f}s): {err} — "
                     "continuing unvetted")
            else:
                note(f"Lore-keeper done ({time.monotonic() - t1:.1f}s)")

        # Backend Validator: one corrective re-ask on rejects, then apply. The
        # envelope arrives under "envelope" (or legacy "rpg" from older prompts).
        events: list[str] = []
        env = plan.get("envelope")
        if not isinstance(env, dict):
            env = plan.get("rpg") if isinstance(plan.get("rpg"), dict) else None
        if env:
            # Same stats list the apply pass uses — validating without it here
            # meant an invented stat never triggered the re-ask it was built for.
            stats = list(rpg_mod.cfg_get(self.rpg_cfg, "stats"))
            _clean, rejected = validator_mod.validate(env, self.store, stats=stats)
            if rejected:
                note(f"Validator: {len(rejected)} delta(s) rejected — re-asking "
                     "Director")
                fixed = self._redirect(env, rejected)
                if fixed is not None:
                    env = fixed
            events = self._apply_envelope(env, rpg_on)
            for e in events:
                note(e)

        note("Writing")
        # Simple mode (skip_logic, no envelope) skips the plan directive but the
        # retrait above still applies: `_writer_context` (Issue #108) either way.
        writer_msgs = self._writer_context(messages) if (skip_logic and not events) \
            else self._writer_messages(messages, plan, facts, events)
        hidden: list[str] = []
        # Reasoning-model headroom (real client only — stubs keep bare stream()):
        # without the floor, server-side thinking can eat the whole budget and
        # yield ZERO prose (caught live on qwen3:4b at max_tokens 2500).
        overrides = {}
        if hasattr(self.writer_llm, "gen"):
            overrides["max_tokens"] = max(
                PROSE_MIN_TOKENS,
                int(self.writer_llm.gen.get("max_tokens", 0) or 0))
        # The writer is told not to emit a sidecar; strip one defensively anyway so a
        # stray block never leaks into the prose. Mechanics come from the Director.
        raw = self.writer_llm.stream(writer_msgs, **overrides)
        stream = rpg_mod.filter_sidecar(raw, hidden) if rpg_on else raw
        for piece in stream:
            out_chunks.append(piece)
            yield piece
        # An empty Writer is a real failure mode (a silent one cost a live run):
        # say WHICH way it was empty — everything diverted as a stray sidecar
        # fence, or the model produced nothing visible at all (think-only/empty).
        if not "".join(out_chunks).strip():
            stray = "".join(hidden).strip()
            if stray:
                note(f"Writer FAILED: prose was swallowed by a stray sidecar fence "
                     f"({len(stray)} chars hidden) — head: {stray[:120]!r}")
            else:
                note("Writer FAILED: no visible prose (empty or think-only output)")

        return events

    def _apply_fallback(self, env: dict, rpg_on: bool) -> list[str]:
        """Validate + apply without an engine (standalone/test construction): same
        semantics as Engine.apply_envelope minus the events-log write and the
        undo-tracked reveal/canon logging."""
        stats = list(rpg_mod.cfg_get(self.rpg_cfg, "stats"))
        clean, rejected = validator_mod.validate(env, self.store, stats=stats)
        events = [f"validator: dropped {r['delta']} — {r['reason']}"
                  for r in rejected]
        events += validator_mod.apply_world(self.store, clean)
        for slug in (clean.get("deltas") or {}).get("reveal", []):
            e = self.store.set_hidden(slug, False)
            if e is not None:
                events.append(f"revealed: {e.title}")
        try:
            rules = {e.slug: e for e in self.store.event_rules()}
        except AttributeError:
            rules = {}
        for slug in (clean.get("deltas") or {}).get("event_fired", []):
            rule = rules.get(slug)
            if rule is None:
                continue
            once = str(rule.attrs.get("once", "")).strip().lower() in \
                ("true", "yes", "1", "on")
            if once and self.store.mark_event_consumed(slug):
                events.append(f"event: {rule.title} fired (once — consumed)")
            else:
                events.append(f"event: {rule.title} fired")
        if rpg_on:
            events += rpg_mod.apply(self.store, clean, self.rpg_cfg)
        return events


def _stage_llm(config, stage_cfg):
    """Build a stage's pinned LLM client, or None when the stage config doesn't pin
    a `profile` (endpoint/key) or `model` — None means inherit the engine's current
    client dynamically."""
    if not isinstance(stage_cfg, dict):
        return None
    profile_name = (stage_cfg.get("profile") or "").strip()
    model = (stage_cfg.get("model") or "").strip()
    if not profile_name and not model:
        return None
    from ..config import build_profile
    profile = build_profile(config.raw, profile_name or config.profile.name,
                            model or None)
    return LLM(profile, config.generation)


def _tail_user(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m["role"] == "user":
            return m["content"]
    return ""


def _plan_text(plan: dict) -> str:
    lines = [str(plan.get("beat_plan", "")).strip()]
    for f in plan.get("must_stay_consistent", []) or []:
        lines.append(f"- consistent: {f}")
    return "\n".join(x for x in lines if x.strip())


def _writer_directive(plan: dict, facts: dict, outcome: list[str] | None = None) -> str:
    beat = str(plan.get("beat_plan", "")).strip() \
        or "(no plan received — improvise a natural continuation of the action)"
    out = ["# DIRECTOR'S PLAN (enact this beat)", beat]
    honor = list(plan.get("must_stay_consistent", []) or []) \
        + list(facts.get("vetted_facts", []) or [])
    patches = list(facts.get("patches", []) or [])
    if honor:
        out.append("\n# FACTS TO HONOR")
        out += [f"- {h}" for h in honor]
    if patches:
        out.append("\n# CONTINUITY CORRECTIONS")
        out += [f"- {p}" for p in patches]
    if outcome:
        out.append("\n# RESOLVED MECHANICS (already rolled and applied — narrate "
                   "these results as fact; never contradict them)")
        out += [f"- {e}" for e in outcome if not e.startswith("validator:")]
    out.append("\nWrite the narration prose ONLY. Do not output JSON, mechanics, or a "
               "```rpg block — the engine handles mechanics.")
    return "\n".join(out)
