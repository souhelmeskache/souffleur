"""Outils MCP — famille position et etat (I-233, decoupe de mcp_server.py).

Point d'entree : `mcp_server.py`, qui importe ce module et reexporte ses
outils. Etat partage et helpers communs restent dans `mcp_server` (le module
commun) ; ce fichier y accede via `mcp_server.<nom>`, jamais de copie locale.
"""
from __future__ import annotations

import mcp_server

@mcp_server.mcp.tool()
def get_world_state() -> dict:
    """Get the full world state: time, player location, flags, quests, RPG block
    (HP/mana/XP/inventory/companions/enemies) + the derived `combat` section
    (I-463: CA, bonus d'attaque et arme du joueur, recalculés à chaque lecture
    depuis la fiche — jamais stockés dans state.json)."""
    store = mcp_server._require_store()
    state = store.world_state()
    if store.rpg_enabled():
        state["combat"] = mcp_server._load_rpg().player_combat(store)
    return state


@mcp_server.mcp.tool()
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
    eng = mcp_server._require_engine()
    store = mcp_server._require_store()
    raw = store.opening_override()
    if not raw:
        return {"has_opening": False, "opening": ""}
    from coderain.sidecar import strip_sidecar
    visible, _ = strip_sidecar(raw)
    return {"has_opening": True, "opening": eng._expand_authored(visible).strip()}


@mcp_server.mcp.tool()
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
    return mcp_server._require_store().event_rules_block()


@mcp_server.mcp.tool()
def validate_envelope(envelope: str) -> dict:
    """Validate a proposed envelope JSON against game rules.

    The envelope shape is: {"v": 1, "check": {...}, "deltas": {...}}.
    Returns {"clean": {...}, "rejected": [{"delta", "value", "reason"}]}.
    Clean is safe to pass to apply_envelope."""
    store = mcp_server._require_store()
    env = mcp_server.json.loads(envelope) if isinstance(envelope, str) else envelope
    rpg_mod = mcp_server._load_rpg()
    stats = list(rpg_mod.cfg_get(mcp_server._rpg_cfg, "stats"))
    clean, rejected = mcp_server.validator_mod.validate(env, store, stats=stats)
    return {"clean": clean, "rejected": [dict(r) for r in rejected]}


@mcp_server.mcp.tool()
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
    store = mcp_server._require_store()
    env = mcp_server.json.loads(envelope) if isinstance(envelope, str) else envelope
    rpg_mod = mcp_server._load_rpg()
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
    if mcp_server._pending_log_mark is None:
        mcp_server._pending_log_mark = mcp_server._event_log_len(store)

    if mcp_server._engine is not None:
        # Match the engine's own convention: the log entry carries the index of
        # the NARRATOR turn this envelope belongs to — that is what branch()
        # filters on (memory.py:1891-1897). Native appends the player turn before
        # applying, so it advances by one; here record_turn appends BOTH turns
        # afterwards, so the count has to be advanced by two. It was +1, which
        # stamped the player turn: branching on that index handed the fork the
        # outcome of an action its transcript never narrated. record_turn
        # corrects the stamp once the real count is known.
        events = mcp_server._echo_checks(mcp_server._engine.apply_envelope(
            env, rpg_on and store.rpg_enabled(),
            log_turn=len(store.turns()) + 2))
        mcp_server._last_applied_events = events    # R1 signal for paquet_narrateur
        return events

    # Degraded path — engine unavailable. Plays, but writes no canon events.
    stats = list(rpg_mod.cfg_get(mcp_server._rpg_cfg, "stats"))
    clean, rejected = mcp_server.validator_mod.validate(env, store, stats=stats)
    events = [f"validator: dropped {r['delta']} — {r['reason']}" for r in rejected]
    events += mcp_server.validator_mod.apply_world(store, clean)
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
        events += rpg_mod.apply(store, clean, mcp_server._rpg_cfg)
    if clean.get("check") or clean.get("deltas"):
        store.append_event_log({"turn": len(store.turns()) + 1, "env": clean})
    events.append("note: moteur degrade — aucun canon-event ecrit")
    events = mcp_server._echo_checks(events)
    mcp_server._last_applied_events = events        # R1 signal for paquet_narrateur
    return events


@mcp_server.mcp.tool()
def assemble_context(player_action: str, budget_tokens: int = 120000,
                     recent_turns: int | None = None, max_secrets: int = 0,
                     wide_lore: bool = True, event_rules: bool = True,
                     secrets_window: int = mcp_server.SECRETS_WINDOW_TURNS,
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
    text, _info = mcp_server._assemble_text(player_action, budget_tokens, recent_turns,
                                 max_secrets, wide_lore, event_rules,
                                 secrets_window, secrets,
                                 lore_include=(set(lore_include)
                                               if lore_include is not None
                                               else None))
    return text


@mcp_server.mcp.tool()
def assemble_context_to_file(player_action: str, budget_tokens: int = 120000,
                             recent_turns: int | None = None,
                             max_secrets: int = 0, wide_lore: bool = True,
                             event_rules: bool = False,
                             secrets_window: int = mcp_server.SECRETS_WINDOW_TURNS,
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
    store = mcp_server._require_store()
    state = store.world_state()
    pdir = mcp_server._partition_dir(store)
    if pdir is not None and mcp_server.assembleur_position.eligible(store, state):
        if recent_turns is None:
            recent_turns = mcp_server._engine.short_term if mcp_server._engine is not None else 12
        history = store.turns()
        text, info = mcp_server._position_context_text(
            store, pdir, state, history, player_action, recent_turns,
            event_rules, secrets)
    else:
        text, info = mcp_server._assemble_text(player_action, budget_tokens, recent_turns,
                                    max_secrets, wide_lore, event_rules,
                                    secrets_window, secrets,
                                    lore_include=(set(lore_include)
                                                  if lore_include is not None
                                                  else None))
    out_dir = mcp_server.ROOT / ".turn"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "context.md"
    out.write_text(text, encoding="utf-8")
    return {"path": str(out), "chars": len(text), **info}


@mcp_server.mcp.tool()
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
    store = mcp_server._require_store()
    rows = store.lore_candidates(mcp_server._wide_history(store), player_action,
                                 budget_tokens=budget_tokens)
    visible = [r for r in rows if not r.get("hidden")]
    hidden = [r for r in rows if r.get("hidden")]
    return {"candidates": rows,
            "n_visible": len(visible),
            "n_forced": sum(1 for r in visible if r.get("forced")),
            "chars_if_all_served": sum(r["chars"] for r in visible),
            "n_hidden_activated": len(hidden),
            "hidden_chars": sum(r["chars"] for r in hidden)}


@mcp_server.mcp.tool()
def ui_sheet() -> dict:
    """Render the player's full character sheet from the loaded save and
    pin it to the right rail of the player's screen. Call it after load_save
    and after any mechanical change (HP, gold, inventory)."""
    import webui
    if not webui.is_running():
        return {"error": "écran non ouvert — appeler ui_open d'abord"}
    try:
        from coderain.modules import rpg as rpg_mod
        store = mcp_server._require_store()
        # La section Combat est DÉRIVÉE (I-463) : elle se passe en argument,
        # elle ne se lit pas dans le bloc rpg — rien ne l'y stocke.
        sheet = rpg_mod.render_sheet_lines(
            store.rpg_state(),
            combat=rpg_mod.player_combat(store) if store.rpg_enabled() else None)
    except Exception as e:  # noqa: BLE001
        return {"error": f"feuille non rendue: {e}"}
    webui.set_sheet(sheet)
    return {"ok": True, "lines": sheet.count("\n") + 1}


@mcp_server.mcp.tool()
def module_index() -> dict:
    """Index of the loaded save's converted module — the discovery
    primitive (SPEC-P4 §8): ids/types of nodes, records, tables and
    secrets ({id, statut} only — bodies stay out) + aventure summary.
    Read-only, no path argument: sealed to the loaded save."""
    try:
        from coderain.converter.aval import load_partition
        return load_partition(mcp_server._module_partition())
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp_server.mcp.tool()
def module_list_nodes() -> list[dict]:
    """List every node of the loaded save's converted module (id/type/altitude)."""
    try:
        from coderain.converter.aval import load_partition
        return load_partition(mcp_server._module_partition())["nodes"]
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)}]


@mcp_server.mcp.tool()
def module_get_node(node_id: str) -> dict:
    """Read ONE node of the module: its typed links + verbatim body."""
    try:
        from coderain.converter.aval import get_node
        return get_node(mcp_server._module_partition(), node_id)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp_server.mcp.tool()
def module_get_record(record_id: str) -> dict:
    """Read one stat block (creature/pnj/...) of the module, already 5e."""
    try:
        from coderain.converter.aval import get_record
        return get_record(mcp_server._module_partition(), record_id)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp_server.mcp.tool()
def module_roll_table(table_id: str, die_result: int | None = None) -> dict:
    """Read a rollable table; pass die_result to fetch the matching row.
    Rolling the die stays the engine's job — this only resolves the row."""
    try:
        from coderain.converter.aval import roll_table
        return roll_table(mcp_server._module_partition(), table_id, die_result)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp_server.mcp.tool()
def module_get_aventure() -> dict:
    """Read the AVENTURE stage of the loaded save's module (D-178): default
    trajectory + disturbances, world conditions with triggers, exit hinge.
    Read it BEFORE directing — it is what happens if the player does nothing."""
    try:
        from coderain.converter.aval import _split_front
        raw = (mcp_server._module_partition() / "aventure.md").read_text(encoding="utf-8")
        front, body = _split_front(raw)
        meta = mcp_server.json.loads(front) if front else {}
        return {**meta, "charniere_md":
                body.replace("## Charnière de sortie", "").strip()}
    except FileNotFoundError:
        return {"error": "cette partition ne porte pas d'étage aventure"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp_server.mcp.tool()
def set_evolution_interne(vecteurs: list[dict]) -> dict:
    """Set the character's evolution_interne vectors (I-200, performatif).

    The player DECIDES the vectors — this is not a state report (D-100).
    Each vector: {id, label, valeur (-5..+5), source: "interoception"|"journal"}.
    At least 2 vectors required (D-125: graduated axes, not 9-alignment grid).

    D-090 guard: labels matching D&D alignments are REJECTED. Source
    'interoception' means the player declared in-character; 'journal' means
    derived from acts via journal2vecteur."""
    store = mcp_server._require_store()
    try:
        clean = mcp_server._validate_evolution_interne(vecteurs)
    except ValueError as e:
        return {"error": str(e)}
    rpg = store.rpg_state()
    if "evolution_interne" not in rpg:
        rpg["evolution_interne"] = {}
    rpg["evolution_interne"]["vecteurs"] = clean
    store.set_rpg_state(rpg)
    return {"ok": True, "vecteurs": clean,
            "count": len(clean),
            "schema": str(mcp_server._EVOLUTION_INTERNE_SCHEMA)}


@mcp_server.mcp.tool()
def derive_evolution_interne(acte: str, vecteur_id: str) -> dict:
    """Derive a vector delta from a role-play act (journal2vecteur, I-200).

    The act describes what the CHARACTER did — not what the player feels or
    thinks (D-090: interoception in-character, never meta-probed). Returns
    the delta and, if applied, the new vector value.

    Use after set_evolution_interne has created the vectors."""
    store = mcp_server._require_store()
    result = mcp_server.journal2vecteur(acte, vecteur_id)
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
    new = max(mcp_server._EVOLUTION_INTERNE_MIN,
              min(mcp_server._EVOLUTION_INTERNE_MAX, old + result["delta"]))
    target["valeur"] = new
    target["source"] = "journal"
    ei["vecteurs"] = vecteurs
    rpg["evolution_interne"] = ei
    store.set_rpg_state(rpg)
    return {**result, "vecteur_id": vecteur_id,
            "old_valeur": old, "new_valeur": new}


__all__ = ['get_world_state', 'opening_scene', 'get_event_rules', 'validate_envelope', 'apply_envelope', 'assemble_context', 'assemble_context_to_file', 'context_candidates', 'ui_sheet', 'module_index', 'module_list_nodes', 'module_get_node', 'module_get_record', 'module_roll_table', 'module_get_aventure', 'set_evolution_interne', 'derive_evolution_interne']
