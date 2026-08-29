"""Phase 2: the fold pipeline.

After qualifying turns, fold the oldest short-term turns into a medium-tier scene
summary (memory/scenes.md), and fold accumulated scenes into the long-tier arc
(memory/arc.md). Following memory-rules.md, the summarizer also *promotes* durable
facts into their home files (characters, canon-events, threads, ...).

Reliability guards:
- the model emits strict JSON; we validate it before touching any file
- a pre-fold snapshot of the story folder (undo)
- slug dedupe via upsert (no duplicate entities)
- graceful degradation: an unparseable fold still advances (keeps a stub summary)
  so the pipeline never loops forever

D-260 lane (c) (Issue #131) — the SCENARIO stage: on a save WITH a projected
position/partition (`assembleur_position.eligible`), every scene fold also
appends one SHORT note to the open scenario stage (`memory/scenario-courant.md`,
`SCENARIO_STAGE_FILE`) — what that scene CHANGED for the current scenario, plus
semantic pointers (characters/locations/quests touched, source turns) that
orient a follow-up recall in the store rather than restating the detail. This is
never called a "delta" (D-118 reserves that word for the score⊥state gap, a
derivation never stored). `fermer_scenario()` is the explicit seam that closes
the stage: it promotes ONE compact entry to a minimal upper receptacle
(`memory/aventure.md`, `ADVENTURE_FILE` — the full adventure stage is out of
scope) and empties the stage, so a closed scenario becomes physically inert —
`assembleur_position` reads the OPEN stage only. Saves WITHOUT a partition never
touch this stage (same `eligible()` frontier as the lanes before this one) —
their scene->arc fold is byte-identical to before this lane."""
from __future__ import annotations

import re

from . import assembleur_position
from .llm import emit_json
from .memory import (ADVENTURE_FILE, Entry, KIND_FILE, MemoryStore,
                     SCENARIO_STAGE_FILE, trigger_hit)

SCENE_INSTRUCTION = """\
You are the story's memory keeper. Fold the TURNS below into ONE concise scene
summary and update durable memory, following the memory rules. You are given the
CURRENT versions of relevant entities — when one changes, REWRITE its full entry
(stable identity + all still-true facts + the change), do not just append. Always
restate every still-true relationship, status, and detail; omitting one means it
no longer holds.

Return ONLY a JSON object, no prose, with this shape:
{
  "scene_summary": "<= 150 words. Reference entities by [[type:slug]] only; do not restate their details.",
  "timeline": "<= 20 words. A terse one-line shorthand of this block for the timeline index. Reference entities by [[type:slug]].",
  "time": {"day": 3, "phase": "evening", "note": "optional"},
  "characters": ["slug of every character present in these turns"],
  "locations": ["slug of every location visited"],
  "quests": ["slug of every thread/quest these turns touched"],
  "state_changes": ["terse machine-readable change, e.g. quests.missing-daughter -> active"],
  "facts": ["timeless world truths established here (NOT events), e.g. The capital is Asterhold"],
  "promotions": [
    {"kind": "character|location|faction|item|canon-event",
     "slug": "kebab-case-id", "title": "Display Name",
     "aliases": ["alt name"], "importance": 1-5,
     "status": "one-line current state (optional)",
     "when": "in-world time this became true (optional)",
     "relationships": [{"with": "other-slug", "note": "ally / rival / owes debt"}],
     "detail": "FULL rewritten detail for this entity's home file",
     "origin": "player|narrator|inferred"}
  ],
  "new_threads": [
    {"slug": "kebab-id", "title": "Thread name", "importance": 1-5,
     "detail": "what is unresolved", "origin": "player|narrator|inferred"}
  ],
  "resolved_threads": [
    {"slug": "slug-of-resolved-thread", "origin": "player|narrator|inferred"}
  ]
}
"time" is optional — include it only if in-world time moved forward. "relationships"
only applies to characters. Only promote genuinely durable, story-relevant facts.

Every promotion, new thread, and resolved thread MUST carry an "origin": who is
responsible for this becoming true in the story, not who is reporting it —
"player" if the PLAYER's own turn explicitly declared, demanded, or performed the
action that made it so; "narrator" if a NARRATOR/NPC turn stated or revealed it
unprompted, with no player action requiring it; "inferred" if neither turn says it
outright and you are deducing/summarizing an implied consequence. Never default to
"narrator" for something the player turn actually forced — that mislabeling is
exactly what erases the player's agency once this scene is folded away.
"""

ARC_INSTRUCTION = """\
Update the long-term ARC synopsis by folding in the older SCENE summaries below.
Keep it terse (<= 200 words total), chronological, and reference entities and
events by [[type:slug]] only.

Return ONLY a JSON object: {"arc": "<the updated synopsis>"}
"""


# How many existing entries _existing_context shows the model. The list is NOT
# ranked by importance before the cut, so past this count an entry can be
# rewritten by a model that was never shown it. The number is unchanged; it is
# named here so the instrumentation and the truncation can never drift apart.
EXISTING_ENTITIES_CAP = 12


def _as_day(v) -> int:
    """Current day as an int for the monotonic guard; anything unusable = 0."""
    if isinstance(v, bool) or not isinstance(v, int):
        return 0
    return v


def _turns_text(turns: list[dict]) -> str:
    out = []
    for t in turns:
        who = "PLAYER" if t["role"] == "player" else "NARRATOR"
        out.append(f"[{who}] {t['text']}")
    return "\n\n".join(out)


class Summarizer:
    def __init__(self, config, store: MemoryStore, llm):
        self.cfg = config
        self.store = store
        self.llm = llm
        m = config.memory
        # Clamp >=2: retry/undo drop up to the last 2 turns, and the fold invariant
        # "folded turns are never in the droppable tail" only holds while at least
        # 2 turns stay verbatim after every fold (guards a pathological config).
        self.medium_after = max(2, int(m.get("medium_fold_after", 12)))
        # Sizes clamp >=1: size 0 would never advance the fold counter while
        # the due-condition stays true — an infinite loop of LLM calls.
        self.medium_size = max(1, int(m.get("medium_fold_size", 6)))
        # Snapshot retention bounds how far back a clean branch can reach
        # (SPEC-V2 §4.2) — each pre-fold snapshot is a branch restore point.
        self.snapshot_keep = max(1, int(m.get("snapshot_keep", 5)))
        # Clamp >=0 for the same infinite-loop reason as the sizes: now that the
        # arc counter advances by len(chunk), a negative "after" would make the
        # due-condition true with an empty chunk and never advance.
        self.long_after = max(0, int(m.get("long_fold_after", 8)))
        self.long_size = max(1, int(m.get("long_fold_size", 4)))
        # Forensic side channels, written by _existing_context/_apply_promotions
        # and read by _fold_scene. They never feed a prompt.
        self._last_triggered: list[str] = []
        self._last_cut: list[str] = []
        self._last_rewritten: list[str] = []

    # --- LLM call: thinking ON, JSON out, one retry ---
    def _emit_json(self, instruction: str, payload: str) -> dict | None:
        rules = self.store.read("memory-rules.md").strip()
        return emit_json(self.llm, rules + "\n\n" + instruction, payload)

    # --- apply validated promotions ---
    def _apply_promotions(self, obj: dict) -> list[str]:
        events: list[str] = []
        self._last_rewritten = []
        for p in obj.get("promotions", []) or []:
            if not isinstance(p, dict):
                continue
            kind = str(p.get("kind", "")).strip().lower()
            rel = KIND_FILE.get(kind)
            slug = _slugify(str(p.get("slug", "")))
            title = str(p.get("title", "")).strip() or slug
            detail = str(p.get("detail", "")).strip()
            if not rel or not slug or not detail:
                continue
            attrs = {}
            if p.get("status"):
                attrs["status"] = str(p["status"]).strip()
            if p.get("when"):
                attrs["when"] = str(p["when"]).strip()
            rel_pairs = []
            for r in p.get("relationships", []) or []:
                if isinstance(r, dict) and r.get("with"):
                    rel_pairs.append(f"{_slugify(str(r['with']))}: "
                                     f"{str(r.get('note', '')).strip()}")
            if rel_pairs:
                attrs["relationships"] = "; ".join(rel_pairs)
            # I-462 (D-107): always stamped, never conditional on p.get(...) like
            # the optional attrs above — a MISSING origin is itself the failure
            # mode this guards against, so it must land as "inferred", not vanish.
            attrs["origin"] = _origin(p.get("origin"))
            aliases = p.get("aliases", [])
            if isinstance(aliases, str):
                # A bare string would iterate CHARACTER by character — every
                # one-letter alias then triggers on everything.
                aliases = [aliases]
            entry = Entry(title=title, slug=slug,
                          aliases=[str(a).strip() for a in aliases
                                   if a and str(a).strip()],
                          importance=_clamp_int(p.get("importance", 3)),
                          attrs=attrs, body=detail)
            # rewrite=True: the model was shown the current entry and returns the
            # full rewritten body, so replace (not append) it.
            self.store.merge_entry(rel, entry, rewrite=True)
            # rewrite=True is the destructive half of the truncation risk: this
            # is the set to intersect with what the cut dropped.
            self._last_rewritten.append(slug)
            events.append(f"memory: promoted [[{kind}:{slug}]]")

        for t in obj.get("new_threads", []) or []:
            if not isinstance(t, dict):
                continue
            slug = _slugify(str(t.get("slug", "")))
            detail = str(t.get("detail", "")).strip()
            if not slug or not detail:
                continue
            self.store.merge_entry("threads.md", Entry(
                title=str(t.get("title", "")).strip() or slug, slug=slug,
                importance=_clamp_int(t.get("importance", 3)),
                attrs={"status": "open", "origin": _origin(t.get("origin"))},
                body=detail))
            events.append(f"memory: new thread [[thread:{slug}]]")

        for r in obj.get("resolved_threads", []) or []:
            # Graceful degradation (D-107 marking is new, older/partial fold
            # output may still hand back a bare slug string): accept both
            # shapes, an origin-less string just stamps "inferred".
            if isinstance(r, dict):
                slug, origin = _slugify(str(r.get("slug", ""))), r.get("origin")
            else:
                slug, origin = _slugify(str(r)), None
            existing = {e.slug: e for e in self.store.entries("threads.md")}
            if slug in existing:
                e = existing[slug]
                e.attrs["status"] = "resolved"
                # Distinct key from the thread's creation "origin": who closed
                # it is not necessarily who opened it.
                e.attrs["resolved_origin"] = _origin(origin)
                self.store.upsert_entry("threads.md", e)
                events.append(f"memory: resolved [[thread:{slug}]]")
        return events

    def _apply_time(self, obj: dict) -> list[str]:
        t = obj.get("time")
        if not isinstance(t, dict):
            return []
        state = self.store.world_state()
        tm = state.get("time")
        if not isinstance(tm, dict):
            tm = {}
            state["time"] = tm
        changed = False
        day = t.get("day")
        # Fold-time time is a FALLBACK (Wave 1): the per-turn time_advance delta
        # is the driver now, so a fold summarizing OLDER turns must never rewind
        # the clock. Day applies only monotonically; phase/note only when the
        # fold's day is at (or past) the live one — a Day-2 fold running after
        # play reached Day 3 must not drag the phase back to "evening".
        cur_day = _as_day(tm.get("day"))
        fold_day = day if isinstance(day, int) and not isinstance(day, bool) \
            else None
        if fold_day is not None and fold_day >= cur_day:
            tm["day"], changed = fold_day, True
        current_or_later = fold_day is None or fold_day >= cur_day
        if t.get("phase") and current_or_later:
            tm["phase"], changed = str(t["phase"]).strip(), True
        if "note" in t and current_or_later:
            note = str(t.get("note", "")).strip()
            if note != tm.get("note", ""):
                tm["note"], changed = note, True
        if not changed:
            return []
        self.store.set_world_state(state)
        return [f"memory: time -> {self.store.clock_str()}"]

    def _existing_context(self, turns: list[dict]) -> str:
        """Show the model the current entries for entities mentioned in the turns,
        so it can rewrite (not append) them."""
        text = _turns_text(turns).lower()
        matched = [e for _, e in self.store.index().entries.values()
                   if any(trigger_hit(tok, text) for tok in e.triggers())]
        hits = [e.render() for e in matched]
        # Forensics only — the two lines below read the same list in the same
        # order and change nothing the model sees.
        self._last_triggered = [e.slug for e in matched]
        self._last_cut = [e.slug for e in matched[EXISTING_ENTITIES_CAP:]]
        if not hits:
            return "EXISTING ENTITIES: (none relevant)"
        return ("EXISTING ENTITIES (rewrite in full if they change):\n\n"
                + "\n\n".join(hits[:EXISTING_ENTITIES_CAP]))

    # --- the folds ---
    def _fold_scene(self, turns: list[dict], scene_no: int,
                    start_turn: int) -> list[str]:
        events = [f"memory: folded scene {scene_no}"]
        # A failed emission skips _apply_promotions, so clear the side channels
        # here or this fold would inherit the previous fold's rewrite set.
        self._last_triggered, self._last_cut, self._last_rewritten = [], [], []
        payload = self._existing_context(turns) + "\n\nTURNS:\n" + _turns_text(turns)
        obj = self._emit_json(SCENE_INSTRUCTION, payload)
        summary = ""
        shorthand = ""
        if obj:
            summary = str(obj.get("scene_summary", "")).strip()
            shorthand = str(obj.get("timeline", "")).strip()
            events += self._apply_promotions(obj)
            events += self._apply_time(obj)  # update clock before stamping the scene
        if not summary:
            summary = "(scene summary unavailable)"
        when = self.store.clock_str()
        # Source-turn range this block covers (1-based inclusive) — the pointer the
        # timeline shorthand hands back for on-demand detail recall.
        end_turn = start_turn + len(turns) - 1
        attrs = {"turns": f"{start_turn}-{end_turn}"}
        if when:
            attrs["when"] = when
        # Wave 2 episode metadata — OPTIONAL: a truncated/failed emission still
        # folds as prose (a fold NEVER blocks on metadata); the entity/quest
        # indexes simply skip this episode.
        if obj:
            for key in ("characters", "locations", "quests"):
                vals = obj.get(key)
                if isinstance(vals, list) and vals:
                    slugs = [_slugify(str(v)) for v in vals if str(v).strip()]
                    if slugs:
                        attrs[key] = ", ".join(dict.fromkeys(slugs))
            changes = obj.get("state_changes")
            if isinstance(changes, list) and changes:
                attrs["state_changes"] = "; ".join(
                    " ".join(str(c).split()) for c in changes if str(c).strip())
            day = self.store.world_state().get("time", {}).get("day")
            if isinstance(day, int) and not isinstance(day, bool):
                attrs["day"] = str(day)
            new_facts = obj.get("facts")
            if isinstance(new_facts, list) and new_facts:
                n = self.store.add_facts([str(f) for f in new_facts])
                if n:
                    events.append(f"memory: +{n} established fact(s)")
        entry = Entry(title=f"Scene {scene_no}", slug=f"scene-{scene_no}",
                      attrs=attrs, body=summary)
        self.store.upsert_entry("memory/scenes.md", entry)
        self._append_timeline(start_turn, end_turn, when, shorthand or summary)
        self._log_fold(scene_no, start_turn, end_turn)
        # D-260 (c) : sur le chemin partition SEUL (même frontière que les lanes
        # précédentes) — jamais pour une save sans position/partition, dont le
        # repliement doit rester octet-identique à avant cette lane.
        if assembleur_position.eligible(self.store, self.store.world_state()):
            events += self._append_scenario_note(scene_no, attrs, summary)
        return events

    def _append_scenario_note(self, scene_no: int, scene_attrs: dict,
                              summary: str) -> list[str]:
        """Ajoute UNE entrée courte à l'étage scénario OUVERT
        (`SCENARIO_STAGE_FILE`) — la trace de ce que cette scène a CHANGÉ pour
        le scénario en cours, jamais un doublon de arc.md (D-129). Le corps
        préfère les `state_changes` (déjà machine-readable, déjà courts) et ne
        retombe sur un extrait du résumé de scène que s'il n'y en a aucun.
        Les attrs `characters`/`locations`/`quests`/`turns` sont réutilisés
        TELS QUELS depuis l'entrée scenes.md déjà construite : ce sont les
        indices sémantiques qui orientent une recherche complémentaire dans
        le store (`recall_entity`/`recall_quest`/`recall_turns`) — l'index
        dit aussi ce qu'il ne dit pas, il ne recopie pas le détail."""
        note = _collapse(scene_attrs.get("state_changes") or summary, cap=140)
        attrs = {k: scene_attrs[k] for k in
                ("turns", "when", "characters", "locations", "quests")
                if scene_attrs.get(k)}
        n = len(self.store.entries(SCENARIO_STAGE_FILE)) + 1
        entry = Entry(title=f"Scène {scene_no}",
                      slug=f"scenario-note-{n}", attrs=attrs, body=note)
        self.store.upsert_entry(SCENARIO_STAGE_FILE, entry)
        return [f"memory: étage scénario +1 (scène {scene_no})"]

    def _log_fold(self, scene_no: int, start_turn: int, end_turn: int) -> None:
        """One forensic line per scene fold. `bit` is the whole point: an entry
        the cut hid from the model AND that the same pass rewrote — the only
        shape in which the truncation actually destroys something. Counts are
        carried alongside the slugs so the file can be answered from without
        reading the identities.

        Never raises: a fold must not fail because a log line could not."""
        try:
            cut, rewritten = list(self._last_cut), list(self._last_rewritten)
            bit = sorted(set(cut) & set(rewritten))
            self.store.append_fold_log({
                "kind": "scene_fold",
                "scene": scene_no,
                "turns": f"{start_turn}-{end_turn}",
                "triggered": len(self._last_triggered),
                "cap": EXISTING_ENTITIES_CAP,
                "cut": len(cut),
                "rewritten": len(rewritten),
                "bit": len(bit),
                "cut_slugs": cut,
                "rewritten_slugs": rewritten,
                "bit_slugs": bit,
            })
        except Exception:  # noqa: BLE001 — forensics never break a fold
            pass

    def _append_timeline(self, start: int, end: int, when: str, text: str) -> None:
        """Append one fold-aligned shorthand line, tagged with its source-turn range
        so `store.recall_turns` can fetch the exact turns on demand."""
        line = " ".join(str(text).split())          # collapse to a single line
        if len(line) > 160:
            line = line[:157].rstrip() + "…"
        stamp = f"{when}: " if when else ""
        existing = self.store.read("memory/timeline.md") \
            or "# Timeline (turn index)\n"
        self.store.write("memory/timeline.md",
                         existing.rstrip("\n") + f"\n- [T{start}-{end}] {stamp}{line}\n")

    def _fold_arc(self, scenes: list[Entry]) -> list[str]:
        payload = "CURRENT ARC:\n" + (self.store.read("memory/arc.md")) \
            + "\n\nOLDER SCENES:\n" + "\n\n".join(e.render() for e in scenes)
        obj = self._emit_json(ARC_INSTRUCTION, payload)
        if obj and str(obj.get("arc", "")).strip():
            self.store.write("memory/arc.md",
                             "# Arc synopsis (long-term)\n\n"
                             + str(obj["arc"]).strip() + "\n")
            return ["memory: updated arc"]
        return []

    def maybe_fold(self) -> list[str]:
        """Run any due folds; returns human-readable event strings."""
        events: list[str] = []
        turns = self.store.turns()
        state = self.store.state()
        folded = int(state.get("folded_turns", 0))
        snapped = False

        while len(turns) - folded > self.medium_after:
            if not snapped:
                self.store.snapshot(keep=self.snapshot_keep)
                snapped = True
            chunk = turns[folded:folded + self.medium_size]
            scene_no = len(self.store.entries("memory/scenes.md")) + 1
            events += self._fold_scene(chunk, scene_no, folded + 1)  # 1-based start
            # Advance by the ACTUAL chunk length, never the configured size — a
            # short tail chunk (or a hand-edited size > after) must not overshoot
            # and silently drop the turns in between.
            folded += len(chunk)
            state["folded_turns"] = folded
            self.store.write_state(state)

        scenes = self.store.entries("memory/scenes.md")
        folded_sc = int(state.get("folded_scenes", 0))
        while len(scenes) - folded_sc > self.long_after:
            if not snapped:
                self.store.snapshot(keep=self.snapshot_keep)
                snapped = True
            chunk = scenes[folded_sc:folded_sc + self.long_size]
            events += self._fold_arc(chunk)
            # Same rule as the turn loop above: advance by the ACTUAL chunk
            # length, never the configured size, or a size > after silently
            # drops the scenes in between.
            folded_sc += len(chunk)
            state["folded_scenes"] = folded_sc
            self.store.write_state(state)

        return events


# I-462 (D-107): the three actors a fold may attribute a scenario influence to.
# Anything the fold LLM emits outside this set (or omits) degrades to
# "inferred" rather than dropping the promotion — a fold must still advance on
# a partial/malformed emission (see module docstring), it just can no longer
# claim a player action or a narrator reveal it didn't actually see.
ORIGINS = {"player", "narrator", "inferred"}


def _origin(v) -> str:
    o = str(v or "").strip().lower()
    return o if o in ORIGINS else "inferred"


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _clamp_int(v, lo: int = 1, hi: int = 5) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return 3


def _collapse(text: str, cap: int) -> str:
    """Une seule ligne courte — pour une note d'étage scénario, jamais un
    paragraphe (D-129 : l'étage accumule des traces COURTES)."""
    line = " ".join(str(text).split())
    return line if len(line) <= cap else line[:cap - 1].rstrip() + "…"


def scenario_stage_chars(store: MemoryStore) -> int:
    """Chars de l'étage scénario OUVERT — la mesure imprimée par les tests :
    la borne structurelle (durée du scénario, jamais un retrait) se constate
    au fil des folds sur cette valeur (D-129, critère d'acceptation #4)."""
    return sum(len(e.render()) for e in store.entries(SCENARIO_STAGE_FILE))


def fermer_scenario(store: MemoryStore, snapshot_keep: int = 5) -> list[str]:
    """Seam explicite (D-260 lane c, Issue #131) : ferme l'étage scénario
    OUVERT. Le déclencheur mécanique est fourni par l'APPELANT (côté
    partition : la charnière de sortie de l'aventure, `aventure.md`) — la
    détection automatique de fin de scénario est HORS périmètre.

    Promeut UNE entrée compacte vers le réceptacle d'étage supérieur
    (ADVENTURE_FILE, v0 : simple réceptacle, pas l'étage aventure complet),
    puis VIDE l'étage : un scénario fermé devient physiquement inerte — plus
    aucun paquet de `assembleur_position` ne le sert, qui ne lit que l'étage
    OUVERT (`SCENARIO_STAGE_FILE`).

    Déterministe, sans appel LLM : les notes de l'étage sont déjà des traces
    courtes posées par chaque fold de scène ; fermer le scénario les
    concatène, il ne les résume pas — recompresser ici referait `arc.md`
    (garde D-129, hors périmètre de cette lane)."""
    notes = store.entries(SCENARIO_STAGE_FILE)
    if not notes:
        return []
    store.snapshot(keep=snapshot_keep)
    n = len(store.entries(ADVENTURE_FILE)) + 1
    body = "\n".join(f"- {note.body.strip()}" for note in notes
                     if note.body.strip())
    entry = Entry(title=f"Scénario {n}", slug=f"scenario-{n}", body=body)
    store.upsert_entry(ADVENTURE_FILE, entry)
    # Étage fermé = physiquement inerte : aucune entrée '## ' à parser, donc
    # store.entries(SCENARIO_STAGE_FILE) revient vide dès ce point.
    store.write(SCENARIO_STAGE_FILE,
               "# Étage scénario (courant)\n\n"
               "(scénario précédent clos — voir memory/aventure.md)\n")
    return [f"memory: scénario {n} clos, promu vers {ADVENTURE_FILE}"]
