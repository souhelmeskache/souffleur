"""The turn loop: assemble context, generate, persist, and fold memory.

Generation has two modes:
- default: stream prose (fast, works on any model)
- lookup-tool: when config generation.use_memory_tool is on, the model can call
  lookup_memory(query) mid-generation to pull details on demand. Meant for
  capable/hosted (big-context) models; not streamed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

from . import assembleur_position
from . import features
from . import input_processor
from . import sidecar as sidecar_mod
from . import templates
from . import validator as validator_mod
from .config import Config, context_budget
from .input_processor import ProcessedInput
from .llm import LLM
from .memory import Entry, MemoryStore, safe_output_regex
from .summarizer import Summarizer

LOOKUP_TOOL = [{
    "type": "function",
    "function": {
        "name": "lookup_memory",
        "description": "Search the story's memory (characters, locations, factions, "
                       "items, canon events, threads) for details before writing. "
                       "Use when you need to recall something specific.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "name, alias, or keyword to look up"},
            },
            "required": ["query"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "recall_turns",
        "description": "Fetch the exact past turns behind a timeline entry, VERBATIM. "
                       "Use ONLY when you need the fine detail of an earlier moment "
                       "the timeline shorthand references — not for every mention. "
                       "Accepts an event/keyword, a scene like 'scene-2', or a turn "
                       "range like 'T6-10'.",
        "parameters": {
            "type": "object",
            "properties": {
                "reference": {"type": "string",
                              "description": "event/keyword, scene slug, or 'T6-10'"},
            },
            "required": ["reference"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "recall_entity",
        "description": "Entity index: 'what happened with X?' — the entry plus "
                       "every past episode whose metadata names that character or "
                       "location, with turn pointers for verbatim drill-down.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "character/location name or slug"},
            },
            "required": ["name"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "recall_quest",
        "description": "Quest index: 'what advanced this quest?' — the thread "
                       "entry, its live status, and every episode that touched it.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "quest/thread name or slug"},
            },
            "required": ["name"],
        },
    },
}]


def _any_applied(events: list[str]) -> bool:
    """True when at least one REAL delta landed — validator rejection warnings
    are UI events, not applied state, and must not keep an orphan player turn."""
    return any(not e.startswith("validator:") for e in events)


class Engine:
    def __init__(self, config: Config, store: MemoryStore):
        self.cfg = config
        self.store = store
        self.llm = LLM(config.profile, config.generation)
        self.summarizer = Summarizer(config, store, self.llm)
        self.short_term = int(config.memory.get("short_term_turns", 12))
        # Explicit number, or `auto`/0 = fill the profile's window (long-context
        # cloud models get everything above the reply reserve).
        self.budget = context_budget(config)
        self.scenes_tail = 4
        # Open-core seam: premium modules resolve through coderain.features —
        # None when a module is trimmed from the build, and every use below
        # degrades gracefully (core must run fully without them).
        self.rpg_mod = (features.module("rpg")
                        if features.enabled("rpg") else None)
        self.use_tool = bool(config.generation.get("use_memory_tool", False)) \
            and features.enabled("memory_tool")
        # Opt-in Trinity Brain (Director -> Lore-keeper -> Writer). Off by default;
        # single-brain path below is untouched when disabled.
        # Base is a callable so unpinned Trinity stages track engine.llm swaps
        # (tests / Settings rebuild) instead of capturing a stale client.
        # Quad applies the envelope BEFORE the narrator turn is appended, so its
        # events-log record must carry the index the narrator turn is ABOUT to
        # get — otherwise the ledger's numbering diverges from the single-brain
        # convention (narrator index) and branch replay filters break.
        trinity_mod = (features.module("trinity")
                       if features.enabled("multi_brain") else None)
        self.trinity = (trinity_mod.TrinityBrain(
                            lambda: self.llm, store, config, config.rpg,
                            self._dispatch_tool, LOOKUP_TOOL,
                            apply_envelope=lambda env, rpg_on:
                            self.apply_envelope(
                                env, rpg_on,
                                log_turn=len(store.turns()) + 1))
                        if trinity_mod is not None
                        and config.generation.get("trinity_brain", False)
                        else None)
        self._rpg_events: list[str] = []
        self._swipes = None            # ST-02 alternates for the last narrator turn
        self._pre_turn_rpg = None
        # D-260 branchement (Issue #128) : posé par `_messages()`, consulté par
        # `_produce()` pour savoir si le paquet vient de l'assembleur position
        # (auquel cas les règles d'événement sont déjà en queue volatile — ne
        # jamais les réinjecter entre DIRECTOR_SYS et le contexte, ce que fait
        # `trinity._direct`, ni les dupliquer en queue single-brain).
        self._partition_active = False
        # Issue #181 : rendu_md du node courant, posé par `_messages()`,
        # consulté par `_produce()` — voir cette méthode.
        self._current_rendu_md = ""
        # I-373: the last turn's routing result (input_processor.process),
        # consulted by _augment_pack to surface LE PACK's propositions to the
        # Director. None before the first routed turn.
        self._last_route: ProcessedInput | None = None
        # Md mutations aren't covered by the state.json snapshot, so undo/retry
        # reverts them explicitly: reveals get re-hidden, canon events added by
        # this turn get removed, consumed event rules get un-consumed.
        self._pre_turn_reveals: list[str] = []
        self._pre_turn_canon: list[str] = []
        self._pre_turn_events: list[str] = []
        # Optional Phase 5 semantic recall (off unless retrieval.enabled + Pro).
        # Reuses the chat client so it's provider-agnostic; None keeps assembly
        # unchanged.
        self.retriever = None
        vector_mod = (features.module("vector")
                      if features.enabled("vector_recall") else None)
        if vector_mod is not None:
            try:
                self.retriever = vector_mod.build_retriever(
                    store, self.llm.client, config.retrieval)
            except Exception:  # noqa: BLE001 — retrieval setup never breaks the engine
                self.retriever = None

    def _partition_dir(self) -> Path | None:
        """D-260 branchement (Issue #128) : résout le partition_dir depuis le
        pointeur save->partition posé par `converter/install.py` à
        l'installation (`module.json`, clé "partition") — jamais une
        convention de chemin devinée. `converter/projection.py` lui-même
        n'écrit PAS ce pointeur (seul `install.py` le fait avant d'appeler
        `derive()`) ; une save projetée sans être passée par `install()`
        (ex. `derive()` appelé à la main) n'a pas de module.json et retombe
        donc sur `store.assemble()` — cohabitation assumée (épic #124)."""
        p = self.store.dir / "module.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        partition = data.get("partition")
        return Path(partition) if partition else None

    def _rpg_rules_served(self) -> str:
        """D-260 post-mesure (a) (Issue #162, suite de l'arbitrage #144) :
        `rpg-rules.md` se découpe en SOCLE toujours servi + section
        « Level-ups and grants » servie seulement sur déclencheur d'état
        vérifiable par le moteur (`rpg.pending_grant > 0` — même info que
        "LEVEL-UP PENDING" dans `rpg_mod.context_block`, jamais du texte
        parsé côté modèle). `templates.split_rpg_rules` porte le garde-fou de
        l'arbitrage : toute section sans déclencheur identifiable reste au
        socle, et un fichier édité par l'utilisateur sans l'en-tête attendu
        retombe sur "texte entier au socle" — jamais une règle silencieusement
        perdue. Les deux appelants (`_messages`/partition et `_augment_rpg`/
        non-partition) passent par ici pour ne jamais diverger."""
        text = self.store.read("rpg-rules.md").strip()
        socle, levelup = templates.split_rpg_rules(text)
        if not levelup:
            return socle
        try:
            pending = int(self.store.rpg_state().get("pending_grant") or 0)
        except (TypeError, ValueError):
            pending = 0
        if pending > 0:
            return (socle.rstrip() + "\n\n" + levelup).strip()
        return socle

    def _messages(self, history, player_input):
        state = self.store.world_state()
        partition_dir = (self._partition_dir()
                         if assembleur_position.eligible(self.store, state)
                         else None)
        self._partition_active = partition_dir is not None
        # Issue #181 : la COULEUR de rendu du node courant, HORS du paquet
        # servi au Director (jamais dans `assembleur_position.build_sections`)
        # — `_produce()` la fait suivre jusqu'au Writer seul via
        # `trinity.generate(rendu_md=...)`. Chaîne vide hors chemin partition.
        self._current_rendu_md = (
            assembleur_position.rendu_md_for(partition_dir,
                                             str(state.get("location", "")))
            if partition_dir is not None else "")
        if partition_dir is not None:
            rpg_on = self.store.rpg_enabled()
            char_sheet = (self.rpg_mod.context_block(
                             self.store, prompt_narrate=self.trinity is None)
                         if rpg_on and self.rpg_mod is not None else "")
            # D-260 post-mesure (Issue #144, arbitrage (b) : "les deux,
            # indépendamment") : rpg-rules.md et la directive response_length
            # sont CONSTANTS par story (jamais liés à la position ni au tour)
            # — on les fait porter par `assembleur_position` comme sections
            # STABLES, aux côtés du reste du préfixe cachable, au lieu de les
            # servir après les sections volatiles comme le faisait
            # `_augment_rpg`/`_augment_style` sur ce chemin. Pur correctif
            # d'ordre : même contenu, même formulation, ailleurs dans le
            # paquet — voir docs/mesure-d260-boucle-neuve.md. D-260 post-mesure
            # (a) (Issue #162) : ce contenu est désormais le socle (+ section
            # Level-ups sur déclencheur, `_rpg_rules_served`) plutôt que le
            # fichier entier — voir cette méthode.
            rpg_rules = self._rpg_rules_served() if rpg_on else ""
            messages = assembleur_position.assemble(
                partition_dir, self.store, state, history, player_input,
                scenes_tail=self.scenes_tail, char_sheet=char_sheet,
                rpg_on=rpg_on, rpg_rules=rpg_rules,
                response_length=self._response_length_directive())
            messages = self._augment_pack(
                self._augment_style(messages, include_length=False))
            return self._augment_event_rules(messages, history, player_input)
        messages = self.store.assemble(history, player_input,
                                       scenes_tail=self.scenes_tail,
                                       budget_tokens=self.budget,
                                       retriever=self.retriever)
        return self._augment_pack(self._augment_style(self._augment_rpg(messages)))

    def _augment_event_rules(self, messages, history, player_input):
        """D-260 branchement (Issue #128) : sur le chemin partition, le bloc
        de règles d'événement candidat (lane b, #127,
        `event_rule_verdicts_block`) rejoint la QUEUE VOLATILE du paquet —
        jamais entre DIRECTOR_SYS et le contexte comme le fait
        `trinity._direct` (`modules/trinity.py::_direct`), ce qui casserait
        la stabilité de préfixe visée par le cache. Le chemin NON-partition
        ne passe jamais ici : `_direct` garde son insertion actuelle
        (single-brain l'ajoute déjà en queue dans `_produce()`, quad
        l'insère avant le contexte)."""
        ev_block = self.store.event_rule_verdicts_block(history, player_input)
        if not ev_block or not messages:
            return messages
        return [{**messages[0],
                "content": messages[0]["content"] + "\n\n" + ev_block},
               *messages[1:]]

    def route_input(self, player_input: str) -> ProcessedInput:
        """Le processeur d'entrée v-min (I-373) : route `player_input` vers les
        3 registres D-092 (parole/intériorité/action) + la ligne PAROLE (trou
        N4) + les commandes méta (I-237) — voir coderain/input_processor.py
        pour la table complète. Effet de bord : chaque segment 'interiorite'
        est extrait vers le support biographique D-233b (réceptacle stub tant
        qu'il n'existe pas). Ne génère rien et n'appelle pas le Director;
        c'est `turn()` qui dispatche une commande vers son propriétaire
        déclaré au lieu d'un tour normal. Le résultat est mémorisé sur
        self._last_route pour que _augment_pack sache quoi remonter."""
        processed = input_processor.process(player_input)
        interior = [s for s in processed.segments if s.registre == "interiorite"]
        if interior:
            input_processor.extraire_interiorite(
                self.store, interior, len(self.store.turns()) + 1)
        self._last_route = processed
        return processed

    def _augment_pack(self, messages):
        """I-373 : LE PACK — tout ce que le processeur d'entrée n'a pas su
        router monte au Director en un objet unique, chaque pièce avec une
        PROPOSITION de lecture, jamais une décision (le processeur propose,
        le Director tranche). Zéro fait n'est écrit à partir de ces
        propositions : elles ne quittent jamais ce bloc de prompt."""
        processed = self._last_route
        if not messages or processed is None or not processed.pack:
            return messages
        lines = [f'- "{item.text}" — proposition : {item.proposition}'
                 for item in processed.pack]
        add = ("\n\n# PACK D'ENTRÉE NON ROUTÉ (I-373)\nPropositions de "
               "lecture ci-dessous, PAS des faits établis — à toi de "
               "trancher :\n" + "\n".join(lines))
        return [{**messages[0], "content": messages[0]["content"] + add},
               *messages[1:]]

    def _authors_note_cfg(self) -> tuple[str, int]:
        """ST-21: per-save author's-note placement — depth ('system' | 'tail') and
        frequency ('every' N turns). Stored in state.json under authors_note."""
        ws = self.store.world_state()
        an = ws.get("authors_note") if isinstance(ws.get("authors_note"), dict) else {}
        depth = an.get("depth") if an.get("depth") in ("system", "tail") else "system"
        try:
            every = max(1, int(an.get("every", 1)))
        except (TypeError, ValueError):
            every = 1
        return depth, every

    def _response_length_directive(self) -> str:
        """The response_length knob's text, extracted so it can be served either
        inline by `_augment_style` (legacy/non-partition path) or as its own
        STABLE section by `assembleur_position` (partition path, D-260 post-mesure,
        Issue #144, arbitrage (b)) — same text, constant per session config,
        never re-derived from the turn. Empty string for the default 'medium'
        (no directive needed)."""
        length = str(self.cfg.generation.get("response_length", "medium")).lower()
        if length == "short":
            return "Keep narration TIGHT: 1-2 short paragraphs per turn."
        if length == "long":
            return ("Write fuller scenes: 4-6 paragraphs; linger on detail, "
                    "dialogue, and atmosphere.")
        return ""

    def _augment_style(self, messages, include_length: bool = True):
        """Wave 4 response controls + ST-21 author's note. The length knob always
        rides the system prompt; the save's custom instructions (the author's note)
        obey their depth + frequency: 'system' appends to the system prompt, 'tail'
        injects just before the player's latest action (binds harder); 'every N'
        only injects on turns whose number is a multiple of N.
        `include_length=False` (Issue #144, arbitrage (b)) : the partition path
        already served the length directive as a STABLE section (`_messages()`),
        so it must not be repeated here — only the author's note logic runs."""
        if not messages:
            return messages
        parts = []
        if include_length:
            note = self._response_length_directive()
            if note:
                parts.append(note)
        custom = self.store.custom_instructions()
        if custom:
            custom = self._expand_authored(custom)   # ST-20 macros in the note too
        depth, every = self._authors_note_cfg()
        # Frequency counts EXCHANGES (narrator turns), 1-based on the one we're about
        # to write — independent of player/narrator parity. every=1 → every turn;
        # the opening (0 narrator turns so far) is exchange 1, so it isn't a spurious
        # multiple for every>1.
        exchange = sum(1 for t in self.store.turns()
                       if t.get("role") == "narrator") + 1
        note_now = bool(custom) and (exchange % every == 0)
        if custom and depth == "system" and note_now:
            parts.append(custom)
        out = messages
        if parts:
            add = "\n\n# STYLE DIRECTIVES\n" + "\n".join(f"- {p}" for p in parts)
            out = [{**messages[0], "content": messages[0]["content"] + add},
                   *messages[1:]]
        # tail: only when there's an actual last action to sit in front of (>=2
        # messages), else the note would land before the system prompt.
        if custom and depth == "tail" and note_now and len(out) >= 2:
            note = {"role": "system", "content": "# AUTHOR'S NOTE\n" + custom}
            out = out[:-1] + [note, out[-1]]     # right before the player's action
        return out

    def _augment_rpg(self, messages, include_sheet: bool = True):
        """When RPG mechanics are on for this story, append the rpg rules + the live
        character sheet to the system prompt. No-op (and zero overhead) when off.
        `include_sheet=False` (D-260 branchement, Issue #128) : le chemin partition
        a déjà passé `rpg_mod.context_block(...)` à l'assembleur position comme
        section volatile dédiée — ne jamais servir la fiche perso deux fois.
        The rules text itself comes from `_rpg_rules_served()` (D-260 post-mesure
        (a), Issue #162) : socle + section « Level-ups and grants » only when a
        grant is pending, not the file wholesale anymore."""
        if not messages or not self.store.rpg_enabled():
            return messages
        rules = self._rpg_rules_served()
        # Quad mode narrates check outcomes the same turn they resolve, so the
        # "narrate this now" nudge would cause a re-narration next turn.
        sheet = (self.rpg_mod.context_block(
                     self.store, prompt_narrate=self.trinity is None)
                 if include_sheet and self.rpg_mod is not None else "")
        add = "\n\n# RPG MODULE (mechanics ON)\n\n" + rules
        if sheet:
            add += "\n\n## Your character sheet\n" + sheet
        return [{**messages[0], "content": messages[0]["content"] + add},
                *messages[1:]]

    def _snapshot_rpg(self):
        """Deep-copy the WHOLE mutable state before a turn — with Wave 1's world
        deltas (time/flags/location) in play, retry/undo must roll back everything
        a turn applied, not just the rpg block (SPEC-V2 §1.4)."""
        return validator_mod.snapshot_state(self.store)

    def restore_pre_turn_rpg(self) -> None:
        """Undo the state changes of the turn about to be retried/undone. Call
        before re-running the last action; no-op when nothing was captured. Note:
        this restores the full state.json, so a fold's fallback time write that
        landed AFTER the snapshot is reverted too — acceptable, since the per-turn
        time_advance delta (re-applied on retry) is the clock's driver now."""
        snap = getattr(self, "_pre_turn_rpg", None)
        if snap is not None:
            self.store.set_world_state(snap)
            # One snapshot covers ONE turn: a second consecutive undo must not
            # re-apply this (now stale) state on top of an older transcript.
            self._pre_turn_rpg = None
        for slug in getattr(self, "_pre_turn_reveals", []):
            self.store.set_hidden(slug, True)
        for slug in getattr(self, "_pre_turn_canon", []):
            self.store.remove_entry("canon-events.md", slug)
        for slug in getattr(self, "_pre_turn_events", []):
            self.store.mark_event_consumed(slug, False)
        self._pre_turn_reveals = []
        self._pre_turn_canon = []
        self._pre_turn_events = []
        # The undone turn's envelope must leave the replay ledger too (callers
        # truncate the transcript first), or a later branch re-applies it.
        self.store.truncate_event_log(len(self.store.turns()))

    def opening(self, on_stage=None) -> Iterator[str]:
        self._rpg_events = []
        self._pre_turn_rpg = self._snapshot_rpg()
        self._pre_turn_reveals = []
        self._pre_turn_canon = []
        self._pre_turn_events = []
        # Wave 4: an authored '## Opening' in premise.md is used VERBATIM as the
        # first scene — no model call (FictionLab's greeting message).
        override = self.store.opening_override()
        if override:
            # A card's first_mes can carry a ```rpg block; drop it so it never
            # reaches the reader (the live-gen path already strips it).
            override, _ = sidecar_mod.strip_sidecar(override)
            override = self._expand_authored(override)   # ST-20 macros in greeting
            if on_stage:
                on_stage("Opening: authored greeting (no generation)")
            self.store.append_turn("narrator", override)
            yield override
            return
        opening_input = "Begin the story. Set the opening scene and place me in it."
        messages = self._messages([], opening_input)
        yield from self._generate_and_store(messages, [], opening_input, on_stage)

    def turn(self, player_input: str, on_stage=None) -> Iterator[str]:
        # I-373: route BEFORE anything else lands in the transcript. A meta
        # command (annuler/rejouer) never becomes a player turn and never
        # reaches the Director — it dispatches straight to its declared
        # owner (undo_last/swipe_generate), reusing their logic verbatim.
        processed = self.route_input(player_input)
        if processed.commande is not None:
            self._rpg_events = []
            if processed.commande.proprietaire == "undo_last":
                self.undo_last()
            elif processed.commande.proprietaire == "swipe_generate":
                yield from self.swipe_generate(on_stage=on_stage)
            return
        self._rpg_events = [
            f"input: {processed.pack_ratio:.0%} transmis brut au Director "
            f"({input_processor.classify_pack_ratio(processed.pack_ratio)}) "
            "(I-373)"]
        self._pre_turn_rpg = self._snapshot_rpg()
        self._pre_turn_reveals = []
        self._pre_turn_canon = []
        self._pre_turn_events = []
        self.store.append_turn("player", player_input)
        history = self.store.recent_turns(self.short_term)[:-1]
        messages = self._messages(history, player_input)
        stored = yield from self._generate_and_store(
            messages, history, player_input, on_stage)
        if not stored:
            # Model produced nothing visible (e.g. only <think>). Don't leave an
            # orphan player turn dangling in the transcript.
            self.store.drop_last_turns(1)

    def continue_story(self, on_stage=None) -> Iterator[str]:
        """Carry the prose forward with NO player action — the 'Continue' button.
        Unlike `turn`, nothing is appended to the transcript as a player line; the
        model simply extends the last scene, so the pipeline is otherwise identical
        (Director plan → validate → Writer)."""
        self._rpg_events = []
        self._pre_turn_rpg = self._snapshot_rpg()
        self._pre_turn_reveals = []
        self._pre_turn_canon = []
        self._pre_turn_events = []
        history = self.store.recent_turns(self.short_term)
        continue_input = (
            "Continue the narration from exactly where it left off. Do not "
            "repeat what was already written and do not summarize — push the "
            "current scene forward with fresh action or detail.")
        messages = self._messages(history, continue_input)
        yield from self._generate_and_store(
            messages, history, continue_input, on_stage)

    def _ensure_swipes(self) -> dict | None:
        """Swipe state for the LAST narrator turn (ST-02). Seeds from the current
        text on first swipe. None when the tail isn't a narrator turn."""
        turns = self.store.turns()
        if not turns or turns[-1]["role"] != "narrator":
            return None
        if self._swipes is None:
            self._swipes = {"variants": [turns[-1]["text"]], "idx": 0}
        return self._swipes

    def swipe_browse(self, direction: int) -> dict | None:
        """Move within already-generated variants — NO model call. Rewrites the
        last narrator turn to the selected variant. {text, idx, count} or None."""
        sw = self._ensure_swipes()
        if sw is None:
            return None
        sw["idx"] = max(0, min(len(sw["variants"]) - 1, sw["idx"] + direction))
        text = sw["variants"][sw["idx"]]
        self.store.update_turn(len(self.store.turns()) - 1, text)
        return {"text": text, "idx": sw["idx"], "count": len(sw["variants"])}

    def swipe_generate(self, on_stage=None) -> "Iterator[str]":
        """Generate a NEW alternative for the last narrator turn and select it
        (swipe past the end of the list). Reuses the retry rollback so mechanics
        don't stack; prior variants are kept for browsing."""
        sw = self._ensure_swipes()
        if sw is None:
            return
        turns = self.store.turns()
        n = len(turns)
        if n >= 2 and turns[-2]["role"] == "player":
            player_input = turns[-2]["text"]
            self.store.drop_last_turns(2)
            self.restore_pre_turn_rpg()
            gen = self.turn(player_input, on_stage=on_stage)
        elif n == 1:
            self.store.drop_last_turns(1)
            self.restore_pre_turn_rpg()
            gen = self.opening(on_stage=on_stage)
        else:
            self.store.drop_last_turns(1)
            self.restore_pre_turn_rpg()
            gen = self.continue_story(on_stage=on_stage)
        yield from gen
        tail = self.store.turns()
        if tail and tail[-1]["role"] == "narrator":
            sw["variants"].append(tail[-1]["text"])
            sw["idx"] = len(sw["variants"]) - 1

    def impersonate(self) -> str:
        """Draft the PLAYER's next action in first person (ST 'Impersonate',
        ST-04). Returns a short suggestion; stores nothing — the UI drops it in
        the composer for the player to edit or send."""
        history = self.store.recent_turns(self.short_term)
        messages = self._messages(
            history,
            "Suggest MY next move as the player: first person, 1-2 sentences, "
            "only the action or dialogue I take — do NOT narrate any outcomes "
            "or write as the narrator.")
        if not self.cfg.generation.get("think", False) and messages:
            messages = [{**messages[0],
                         "content": messages[0]["content"] + "\n\n/no_think"},
                        *messages[1:]]
        raw = "".join(self.llm.stream(messages))     # stream() filters <think>
        visible, _ = sidecar_mod.strip_sidecar(raw)  # drop any ```rpg block
        return visible.strip()

    def undo_last(self) -> dict:
        """Remove the last exchange WITHOUT regenerating — the player is left at the
        prior state to try a different action. Mirrors the retry rollback (drop the
        last narrator + its player turn, roll back this turn's RPG mechanics) but does
        not call the model. Returns {"undone": bool, "mechanics_restored": bool}.

        Single-level within the session: `restore_pre_turn_rpg` holds one snapshot, so
        a second consecutive undo won't further rewind mechanics (multi-level undo
        would need per-turn persisted snapshots). Only ever touches the retry-able tail
        (turns not yet folded/timelined), so timeline pointers stay valid.

        When the pattern is [narrator, narrator] (opening after resume), only the
        opening narrator is dropped and mechanics_restored is False (no player turn
        to rollback)."""
        turns = self.store.turns()
        if turns and turns[-1]["role"] == "narrator" and len(turns) >= 2:
            if turns[-2]["role"] == "player":
                self.store.drop_last_turns(2)
                self.restore_pre_turn_rpg()
                return {"undone": True, "mechanics_restored": True}
            else:
                self.store.drop_last_turns(1)
                return {"undone": True, "mechanics_restored": False}
        elif turns and turns[-1]["role"] == "player":
            self.store.drop_last_turns(1)  # orphan player turn (empty generation)
            return {"undone": True, "mechanics_restored": False}
        else:
            return {"undone": False, "mechanics_restored": False}

    def maybe_fold(self) -> list[str]:
        """Run due memory folds after a turn. Returns event strings for the UI —
        RPG mechanics events (from this turn's sidecar) first, then fold events."""
        events = self._rpg_events + self.summarizer.maybe_fold()
        self._rpg_events = []
        return events

    def _expand_authored(self, text: str) -> str:
        """ST-20: expand macros in a verbatim authored string (the opening), with
        the same context assemble() uses so results match."""
        from .macros import expand_macros
        ws = self.store.world_state()
        tm = ws.get("time") if isinstance(ws.get("time"), dict) else {}
        rpg = ws.get("rpg") if isinstance(ws.get("rpg"), dict) else {}
        try:
            seed = int(rpg.get("seed", 0))
        except (TypeError, ValueError):
            seed = 0
        player = self.store.entries("player.md")
        return expand_macros(text, player=(player[0].title if player else "you"),
                             clock=self.store.clock_str(),
                             day=str(tm.get("day", "")), seed=seed,
                             turn=len(self.store.turns()))

    def _apply_output_regex(self, text: str) -> str:
        """ST-31: run the save's persistent find/replace rules over narrator output.
        A bad pattern is skipped; a pattern that could catastrophically backtrack
        (ReDoS — a real risk since rules ride inside shared/imported worlds) is
        rejected by safe_output_regex, never executed."""
        rules = self.store.world_state().get("regex_rules")
        if not isinstance(rules, list):
            return text
        for r in rules:
            if not isinstance(r, dict):
                continue
            find = r.get("find")
            if not isinstance(find, str) or not safe_output_regex(find):
                continue
            fl = 0
            for ch in str(r.get("flags", "")).lower():
                fl |= {"i": re.I, "m": re.M, "s": re.S}.get(ch, 0)
            # Accept SillyTavern/JS-style $1 backreferences (Python re wants \1).
            repl = re.sub(r"\$(\d)", r"\\\1", str(r.get("replace", "")))
            try:
                text = re.sub(find, repl, text, flags=fl)
            except re.error:
                continue        # invalid rule -> leave the text unchanged
        return text

    def _reply_prefix(self) -> str:
        """ST-22 'Start reply with': a persistent literal prefix every generated
        narrator turn begins with (e.g. a quote, an asterisk, a name). Cross-provider
        because we prepend it rather than relying on backend prefix-continuation."""
        v = self.cfg.generation.get("start_reply_with", "")
        return v if isinstance(v, str) else ""    # ignore a malformed non-string

    def _generate_and_store(self, messages, history, player_input,
                            on_stage=None) -> "Iterator[str]":
        """Stream a narrator turn. The reply prefix (ST-22) is injected lazily — just
        before the first real prose chunk — so it only appears when a turn is actually
        produced. An empty/sidecar-only turn stores nothing AND shows nothing, so the
        streamed text always equals the stored text. Returns True iff a turn stored.
        `history`/`player_input` : même assiette que `_messages()`, servie à
        l'évaluateur de règles d'événement (D-260 lane b, #127) — jamais
        `messages` ré-analysé, pour rester indépendant de ses augmentations."""
        prefix = self._reply_prefix()
        inner = self._produce(messages, history, player_input, prefix, on_stage)
        if not prefix:
            return (yield from inner)     # no prefix -> unchanged passthrough
        sent = False
        while True:
            try:
                piece = next(inner)
            except StopIteration as done:
                return done.value
            if not sent:
                # Swallow leading whitespace-only chunks and emit the prefix only
                # once REAL prose arrives (so a sidecar-only turn that streams a
                # stray space/newline before the ```rpg fence shows no orphan
                # prefix). lstrip the first real chunk so the streamed prefix hugs
                # the prose exactly like the stored narration (which is stripped).
                if not piece.strip():
                    continue
                piece = piece.lstrip()
                yield prefix
                sent = True
            yield piece

    def _produce(self, messages, history, player_input, prefix,
                on_stage=None) -> "Iterator[str]":
        """The generation body (all three paths). Yields raw prose chunks and prepends
        `prefix` to the STORED narration so storage matches what was streamed."""
        rpg_on = self.store.rpg_enabled()
        sidecar = None
        trinity_events = None
        if self.trinity is None and not self._partition_active:
            # Single-brain: the one model IS the logic agent, so it gets the
            # event rules (in quad mode only the Director sees them). D-260
            # lane (b) (#127) : bloc CANDIDAT du tour, jamais l'ensemble
            # constant (I-158) — event_rules_block() reste disponible ailleurs
            # (pont MCP get_event_rules, etc.), inchangé. Chemin partition :
            # déjà en queue volatile via `_augment_event_rules()` dans
            # `_messages()` (D-260 branchement, #128) — pas de second ajout.
            ev_block = self.store.event_rule_verdicts_block(history, player_input)
            if ev_block and messages:
                messages = [{**messages[0],
                             "content": messages[0]["content"] + "\n\n" + ev_block
                             + "\n\n(Enforce these silently; NEVER reveal an "
                               "unfired rule in prose.)"},
                            *messages[1:]]
        if self.trinity is not None:
            # Quad pipeline: the Logic Agent's envelope is validated and RESOLVED
            # before the Narrator writes (so prose narrates the actual outcome);
            # trinity returns the already-applied events, not a sidecar.
            # Simple Story mode = the FAST mode: no mechanics to plan, so the
            # Logic Agent is skipped entirely — one LLM call per turn. Authored
            # event rules are the exception: only the Director can fire them, so
            # their presence forces the full pipeline even in simple mode.
            simple = (not rpg_on and self.store.mode() == "simple"
                      and not self.store.event_rules())
            chunks: list[str] = []
            # D-260 branchement (Issue #128) : chemin partition -> event_rules
            # déjà servi en queue volatile par `_augment_event_rules()`, ne
            # jamais le repasser ici (trinity._direct l'insérerait avant le
            # contexte, ce qui casserait la stabilité de préfixe).
            trinity_events = yield from self.trinity.generate(
                messages, rpg_on, on_stage, chunks, skip_logic=simple,
                event_rules="" if self._partition_active else
                            self.store.event_rule_verdicts_block(
                                history, player_input),
                rendu_md=self._current_rendu_md)
            narration = "".join(chunks).strip()
        elif self.use_tool:
            raw = self._generate_with_tool(messages)
            # Strip/parse the sidecar in EVERY mode: world/lore deltas are valid
            # with RPG off (only mechanics are gated, in apply_envelope), and a
            # stray ```rpg block must never reach the reader verbatim.
            narration, sidecar = sidecar_mod.strip_sidecar(raw)
            if narration:
                yield narration
        else:
            # Qwen3 soft switch: /no_think for fast prose. Copy the system message
            # so we never mutate the caller's assembled context.
            if not self.cfg.generation.get("think", False) and messages:
                messages = [{**messages[0],
                             "content": messages[0]["content"] + "\n\n/no_think"},
                            *messages[1:]]
            chunks: list[str] = []
            hidden: list[str] = []
            stream = self.llm.stream(messages)
            # Filter in EVERY mode (see the tool path above): never leak a
            # ```rpg block, and keep the world/lore delta channel open.
            stream = sidecar_mod.filter_sidecar(stream, hidden)
            for piece in stream:
                chunks.append(piece)
                yield piece
            narration = "".join(chunks).strip()
            if hidden:
                sidecar = sidecar_mod.parse_sidecar("".join(hidden))
        if narration:
            # ST-31 scrubs the MODEL's output; the ST-22 prefix is prepended AFTER
            # so a cleanup rule can't eat it (the prefix always begins the turn).
            narration = self._apply_output_regex(narration)
            if prefix:
                narration = prefix + narration
            if narration.strip():        # a rule that empties the turn stores nothing
                self.store.append_turn("narrator", narration)
            else:
                narration = ""
        # Apply mechanics even when the model emitted ONLY a sidecar (no visible
        # prose) — otherwise a terse mechanical turn would silently lose its check
        # and deltas. A turn counts as "stored" if it produced prose OR mechanics,
        # so the player's action isn't dropped as an orphan when it had an effect.
        applied = False
        if trinity_events is not None:
            # Quad path already validated + applied inside trinity.generate.
            self._rpg_events += trinity_events
            applied = _any_applied(trinity_events)
        elif sidecar:
            events = self.apply_envelope(sidecar, rpg_on)
            self._rpg_events += events
            applied = _any_applied(events)
        return bool(narration) or applied

    def apply_envelope(self, env: dict, rpg_on: bool,
                       log_turn: int | None = None) -> list[str]:
        """The Backend Validator seam (SPEC-V2 §1.4), shared by both producers:
        validate the proposed envelope, surface every dropped delta loudly, apply
        world deltas (always) + reveals + mechanics (when RPG is on), and append
        the clean envelope to the events log for undo/branch replay. The record's
        turn index is the NARRATOR turn the envelope belongs to — pass `log_turn`
        when applying before that turn is appended (the quad pipeline does)."""
        stats = list(sidecar_mod.cfg_get(self.cfg.rpg, "stats"))
        clean, rejected = validator_mod.validate(env, self.store, stats=stats)
        events = [f"validator: dropped {r['delta']} — {r['reason']}"
                  for r in rejected]
        events += validator_mod.apply_world(self.store, clean)
        events += self._apply_reveals(clean)
        events += self._apply_quest_canon(clean)
        events += self._apply_event_rules(clean)
        if rpg_on:
            if self.rpg_mod is not None:
                events += self.rpg_mod.apply(self.store, clean, self.cfg.rpg)
            else:
                # RPG save opened on a free install: prose continues, the
                # mechanics are skipped LOUDLY (never silently absorb deltas).
                events.append("rpg: mechanics skipped — the RPG module is "
                              "not present in this build")
        if clean.get("check") or clean.get("deltas"):
            self.store.append_event_log(
                {"turn": len(self.store.turns()) if log_turn is None
                 else log_turn, "env": clean})
        return events

    def _apply_reveals(self, clean: dict) -> list[str]:
        """Flip validated `reveal` slugs public — the one sanctioned Markdown
        mutation (SPEC-V2 §2.3): logged as a canon event, tracked per turn so
        undo/retry re-hides them (state snapshots don't cover md)."""
        events = []
        for slug in (clean.get("deltas") or {}).get("reveal", []):
            e = self.store.set_hidden(slug, False)
            if e is None:
                continue
            self._pre_turn_reveals.append(slug)
            self._pre_turn_canon.append(f"revealed-{slug}")
            self.store.merge_entry("canon-events.md", Entry(
                title=f"Revealed: {e.title}", slug=f"revealed-{slug}",
                importance=min(5, e.importance),
                attrs={"when": self.store.clock_str()},
                body=f"The truth about [[{slug}]] came to light."))
            events.append(f"revealed: {e.title}")
        return events

    def _apply_event_rules(self, clean: dict) -> list[str]:
        """Mark fired once-rules consumed (validated already: exists + not yet
        consumed). Undo-tracked — retry/undo un-consumes."""
        events = []
        rules = {e.slug: e for e in self.store.event_rules()}
        for slug in (clean.get("deltas") or {}).get("event_fired", []):
            rule = rules.get(slug)
            if rule is None:
                continue
            once = str(rule.attrs.get("once", "")).strip().lower() in \
                ("true", "yes", "1", "on")
            if once and self.store.mark_event_consumed(slug):
                self._pre_turn_events.append(slug)
                events.append(f"event: {rule.title} fired (once — consumed)")
            else:
                events.append(f"event: {rule.title} fired")
        return events

    def _apply_quest_canon(self, clean: dict) -> list[str]:
        """A quest reaching completed/failed is story canon — log it as a canon
        event (undo-tracked, like reveals). The quests dict itself was already
        committed by apply_world; the thread entry stays for the summarizer to
        resolve narratively at the next fold."""
        events = []
        for slug, new in ((clean.get("deltas") or {}).get("quest_update")
                          or {}).items():
            if new not in ("completed", "failed"):
                continue
            thread = next((e for e in self.store.entries("threads.md")
                           if e.slug == slug), None)
            title = thread.title if thread else slug
            canon_slug = f"quest-{slug}-{new}"
            self._pre_turn_canon.append(canon_slug)
            self.store.merge_entry("canon-events.md", Entry(
                title=f"Quest {new}: {title}", slug=canon_slug,
                importance=4, attrs={"when": self.store.clock_str()},
                body=f"[[thread:{slug}]] ended: {new}."))
            events.append(f"quest {new}: {title}")
        return events

    def companions(self) -> list[str]:
        """Slugs a side-chat can target: characters flagged `companion: true`
        plus anyone already in the state's companions block."""
        marked = [e.slug for e in self.store.entries("characters.md")
                  if str(e.attrs.get("companion", "")).strip().lower()
                  in ("true", "yes", "1", "on")]
        state = list(self.store.rpg_state().get("companions", {}))
        return list(dict.fromkeys(marked + state))

    def conversation_b_start(self, partition_data: dict,
                             nom: str = "Vahn") -> dict:
        """Start a conversation B (D-219 §Spécification, I-144).

        Takes partition data (nodes, tensions, resources, secrets) and drives
        the 4-window character creation protocol. Returns the F1 state.
        Delegates to webui.ConversationB — the webui holds the session state.
        """
        from webui import conv_b_start
        return conv_b_start(partition_data, nom)

    def conversation_b_submit(self, player_text: str) -> dict:
        """Submit a player choice/reformulation to the active conversation B."""
        from webui import conv_b_submit
        return conv_b_submit(player_text)

    def conversation_b_personnage(self, pid: str | None = None,
                                  nom: str | None = None) -> dict:
        """Build the Personnage record from the completed conversation B."""
        from webui import conv_b_personnage
        return conv_b_personnage(pid, nom)

    def companion_chat(self, name: str, user_text: str) -> Iterator[str]:
        """Out-of-band side-chat with a companion (SPEC-V2 §3.4): a private
        conversation between story turns — advice, banter, strategy. Streams the
        reply; logs to memory/companion-chat.md (NEVER the transcript: no turn
        counter, no folds). The story sees only a short digest via assemble."""
        from .templates import slugify
        slug = slugify(str(name or ""))
        comp = next((e for e in self.store.entries("characters.md")
                     if e.slug == slug), None)
        if comp is None:
            yield f"(no such character: {name})"
            return
        cstate = self.store.rpg_state().get("companions", {}).get(slug, {})
        mood = ", ".join(f"{k}: {v}" for k, v in cstate.items() if v)
        tail = self.store.recent_turns(6)
        story = "\n".join(f"[{t['role'].upper()}] {t['text'][:400]}"
                          for t in tail)
        prior = self.store.companion_chat_tail(slug, lines=12)
        sys = (f"You ARE {comp.title}, a companion travelling with the player in "
               "an interactive story. This is a PRIVATE conversation between "
               "story turns — speak in first person, fully in character (see "
               "your Voice). Give opinions, advice, warnings, banter; ask "
               "questions back. Do NOT narrate story events, do NOT advance the "
               "plot, do NOT speak for the player. Keep replies short and "
               "conversational (2-6 sentences).\n\n# WHO YOU ARE\n"
               + comp.render()
               + (f"\n# YOUR CURRENT STATE\n{mood}" if mood else "")
               + (f"\n\n# WHAT JUST HAPPENED IN THE STORY\n{story}" if story
                  else "")
               + (f"\n\n# YOUR EARLIER PRIVATE TALK\n{prior}" if prior else ""))
        messages = [{"role": "system", "content": sys},
                    {"role": "user", "content": user_text}]
        chunks: list[str] = []
        for piece in self.llm.stream(messages):
            chunks.append(piece)
            yield piece
        reply = "".join(chunks).strip()
        if reply:
            self.store.append_companion_chat(slug, user_text, reply)

    def _generate_with_tool(self, messages) -> str:
        return self.llm.complete_with_tools(
            messages, LOOKUP_TOOL, self._dispatch_tool).strip()

    def _dispatch_tool(self, name, args):
        """Resolve a memory tool call (shared by the lookup path and Trinity's
        Lore-keeper). recall_turns is the on-demand pointer-back into the full
        transcript behind a timeline shorthand."""
        if name == "lookup_memory":
            return self.store.lookup(str(args.get("query", "")))
        if name == "recall_turns":
            return self.store.recall_turns(str(args.get("reference", "")))
        if name == "recall_entity":
            return self.store.recall_entity(str(args.get("name", "")))
        if name == "recall_quest":
            return self.store.recall_quest(str(args.get("name", "")))
        return f"unknown tool: {name}"
