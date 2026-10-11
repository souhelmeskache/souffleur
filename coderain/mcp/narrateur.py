"""Outils MCP — famille narrateur (I-233, decoupe de mcp_server.py).

Point d'entree : `mcp_server.py`, qui importe ce module et reexporte ses
outils. Etat partage et helpers communs restent dans `mcp_server` (le module
commun) ; ce fichier y accede via `mcp_server.<nom>`, jamais de copie locale.
"""
from __future__ import annotations

import mcp_server

@mcp_server.mcp.tool()
def paquet_narrateur(directive_director: str, action_joueur: str,
                     sans_mecanique: bool = False) -> dict:
    """Issue #192 (D-269), chantier 4 (I-14) — LE péage du tour : l'unique
    canal vers le narrateur. Le Director l'appelle après résolution
    mécanique du tour ; l'outil compose le paquet, l'écrit dans un FICHIER,
    et ne retourne au Director que le chemin + des métadonnées — le contenu
    n'entre jamais dans SA fenêtre (même patron qu'`assemble_context_to_file`).

    ── D-110 (caméra) : filtre MOTEUR + visée DIRECTOR ──
    `directive_director` porte la VISÉE SEULE — plan du beat, angle/cadrage,
    croyance divergente, inflexion de ton du TOUR. Tout le reste, l'outil le
    COMPOSE lui-même depuis le moteur (jamais recopié par le Director), DANS
    CET ORDRE et rien d'autre (chantier 4 — réduit au STRICT nécessaire au
    narrateur, jamais la photo du Director) :

      1. Règles du narrateur (`coderain/roles/narrateur.md`, lu depuis le
         dossier du paquet, jamais le dossier courant) — en TÊTE, elles
         priment sur tout ce qui suit.
      2. « Personnage joué » — inchangée (`assembleur_position._player_section`).
      3. « Ce que le personnage perçoit de la scène » — le corps du nœud
         courant, les écarts actés de CE nœud (D-419) sous une formulation
         qui ne nomme jamais « nœud » ni « écart » au narrateur, puis une
         ligne Horloge (même valeur que la section Position du Director) —
         ou, sur une save sans partition (repli), le même contexte
         mots-clés+budget qu'avant (`_assemble_text`, inchangé). Jamais le
         brief, l'objectif, les débouchés, la Position, les Présences,
         l'état du monde ni la reprise de séance : décor réservé au
         Director (D-179/D-419, chantier 4).
      4. Derniers tours verbatim (la scène où l'on reprend).
      5. Mécaniques résolues CE TOUR — les événements réellement APPLIQUÉS
         (jets, patchs, `event_fired`, ou — Issue #200 — intents/dégâts/
         rounds de combat), lus au JOURNAL de l'outil (`apply_envelope`
         pour la mécanique coderain classique, `start_combat`/
         `submit_intent`/`monster_turn` pour le sous-système combat —
         voir `_record_combat_events`), jamais retapés par le Director.
      6. `rendu_md` du node courant (résout D-269) — section « DIRECTION DE
         RENDU », symétrique de `modules/trinity.py::_writer_directive` mais
         désormais servie sur le chemin PRODUIT. Absente si le node n'en
         porte pas.
      7. La directive du Director, verbatim, après le filet R2.

    ── Les trois refus ──
    R1 — mécanique avant prose : refuse si aucune mécanique n'a été résolue
    depuis le dernier tour (aucune enveloppe via `apply_envelope`, ni aucun
    combat via `start_combat`/`submit_intent`/`monster_turn` — Issue #200)
    et que `sans_mecanique` n'est pas déclaré à `True` — une déclaration
    explicite qu'aucune résolution n'a eu lieu ce tour (ex. un tour de pure
    parole).

    R2 — filet anti-fuite littéral : refuse si `directive_director` contient
    un slug ou un fragment de texte d'une entrée cachée non révélée, le
    slug/texte d'une règle d'événement (fired ou non) — et, chantier 4
    (D-419 pt C) — un identifiant de la partition chargée (nom de fichier
    de nœud ou de record, ex. « sortie vers para-12 » quand `para-12` est
    un nœud) ou un mot/une tournure qui parle des sources de la scène
    (« nœud », « flag », « le module », ... — `mcp_server._R2_SOURCE_WORDS`,
    sans exception même au sens propre). Nomme la garde déclenchée — le
    Director connaît déjà les coulisses, ce n'est jamais ce texte qui
    atteint le narrateur. La paraphrase reste permise (filet littéral, pas
    un classifieur de sens) — « il reste à l'écart », « sous la bannière »
    passent.

    R3 — pas de contenu en retour : le retour ne porte jamais le texte du
    paquet, ni `rendu_md` même en booléen de contenu — seulement le chemin,
    la taille, et les NOMS des sections écrites.

    Le fichier est écrasé à chaque tour et vit sous `.turn/` de la save
    CHARGÉE (`mcp_server._turn_dir()`, Issue #287 — même sentinel que
    `assemble_context_to_file`), jamais dans un dossier partagé par tout le
    worktree."""
    store = mcp_server._require_store()
    if mcp_server._last_applied_events is None and not sans_mecanique:
        raise ValueError(
            "R1 (mécanique avant prose) : aucune mécanique résolue depuis "
            "le dernier tour — appelle apply_envelope (ou start_combat/"
            "submit_intent/monster_turn en combat) d'abord, ou déclare "
            "sans_mecanique=True si ce tour ne résout explicitement aucune "
            "mécanique.")
    directive = str(directive_director or "")
    guard = mcp_server._r2_scan(store, directive)
    if guard:
        raise ValueError(
            f"R2 (filet anti-fuite) : directive_director contient la garde "
            f"« {guard} » — reformule sans slug/identifiant de la "
            "partition, sans mot de source, ni fragment littéral de "
            "matériau caché ou de règle d'événement (la paraphrase reste "
            "permise, ce filet est littéral).")

    state = store.world_state()
    pdir = mcp_server._partition_dir(store)
    history = store.turns()
    recent_turns = mcp_server._engine.short_term if mcp_server._engine is not None else 12

    regles_narrateur = (mcp_server.ROOT / "coderain" / "roles"
                        / "narrateur.md").read_text(encoding="utf-8").strip()
    parts = ["## Règles du narrateur (elles s'adressent à toi, narrateur, "
            "et priment sur tout ce qui suit)\n" + regles_narrateur]
    sections = ["Règles du narrateur"]

    rendu_md = ""
    if pdir is not None and mcp_server.assembleur_position.eligible(store, state):
        location = mcp_server.validator_mod.current_location(state)
        for s in mcp_server.assembleur_position.narrator_sections(store, location):
            rendered = s.render()
            if rendered:
                parts.append(rendered)
                sections.append(s.title)
        if recent_turns > 0 and history:
            lignes = []
            for t in history[-recent_turns:]:
                who = "JOUEUR" if t["role"] == "player" else "MJ"
                lignes.append(f"### {who}\n{t['text'].strip()}")
            parts.append(
                "# DERNIERS TOURS (verbatim — la scène où l'on reprend)\n\n"
                + "\n\n".join(lignes))
            sections.append("Derniers tours")
        rendu_md = mcp_server.assembleur_position.rendu_md_for(pdir, location)
    else:
        text, _info = mcp_server._assemble_text(
            action_joueur, 120000, recent_turns, 0, True, False,
            mcp_server.SECRETS_WINDOW_TURNS, False)
        parts.append(text)
        sections.append("Contexte perçu (scène + derniers tours)")

    outcome = [e for e in (mcp_server._last_applied_events or [])
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
    out_dir = mcp_server._turn_dir()
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "paquet-narrateur.md"
    out.write_text(full, encoding="utf-8")
    sections_chars = {s: len(p) for s, p in zip(sections, parts)}
    mcp_server._log_paquet(store, "paquet_narrateur", len(full), sections_chars)
    return {"path": str(out), "chars": len(full), "sections": sections}


@mcp_server.mcp.tool()
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
    store = mcp_server._require_store()
    pending_from = len(store.turns())
    if player_action and player_action.strip():
        store.append_turn("player", player_action.strip())
    if narration and narration.strip():
        store.append_turn("narrator", narration.strip())
    if mcp_server._slug:
        try:
            mcp_server._library().saves.touch(mcp_server._slug)   # last-played stamp, as the CLI does
        except Exception:  # noqa: BLE001
            pass
    n = len(store.turns())
    mcp_server._restamp_turn_log(store, pending_from, n)
    out = {"turns": n, "fold_due": mcp_server._fold_probe(n)}
    # The turn is closed: retire its rollback material and arm the next one.
    # This is what makes the arming automatic — it rides the one gesture the
    # loop is already forbidden to skip. The R1 signal closes with it — a new
    # turn starts with no envelope applied yet, exactly like a fresh session.
    mcp_server._arm_turn(retire=True)
    mcp_server._last_applied_events = None
    return out


# ── companion side-chat — the engine's prompt, our model ─────────
# A private conversation with a companion between story turns: advice, banter,
# strategy. It is logged to memory/companion-chat.md, never the transcript — no
# turn counter, no folds — and the story only ever sees a short digest of it,
# which assemble() already injects. The engine builds a genuinely specific
# system prompt for it (who the companion is, their current mood block, the last
# six story turns clipped, the earlier private talk). That prompt is engine work
# worth having; only the reply is ours to generate.

@mcp_server.mcp.tool()
def companions() -> list[str]:
    """Characters a private side-chat can target: those flagged `companion: true`
    plus anyone in the state's companions block. Empty is a normal answer — it
    means no character carries the flag in this save."""
    return mcp_server._require_engine().companions()


@mcp_server.mcp.tool()
def companion_prompt(name: str, user_text: str) -> dict:
    """Build the engine's side-chat prompt for one companion.

    Returns {"slug", "system", "user"} — speak AS that companion, following the
    system text exactly, then pass the reply to companion_log. Do not improvise
    the framing yourself: the prompt carries the companion's sheet, their current
    state, what just happened, and your earlier private talk."""
    from coderain.templates import slugify
    store = mcp_server._require_store()
    slug = slugify(str(name or ""))
    comp = next((e for e in store.entries("characters.md") if e.slug == slug),
                None)
    if comp is None:
        return {"error": f"no such character: {name}",
                "candidates": mcp_server._require_engine().companions()}
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


@mcp_server.mcp.tool()
def companion_log(slug: str, user_text: str, reply: str) -> dict:
    """Log one side-chat exchange where the engine keeps it: out of the
    transcript, out of the fold, out of the timeline. Skip this and the private
    conversation never happened as far as the story is concerned — the digest
    assemble() feeds back to the narrator comes from this file."""
    store = mcp_server._require_store()
    store.append_companion_chat(slug, user_text, reply)
    return {"logged": True, "digest_lines": len(
        store.companion_chat_tail(slug, lines=12).splitlines())}


# ── player screen (web UI) ───────────────────────────────────────
# See webui.py for the why. In short: the player reads the browser, not the
# terminal, so nothing has to be hidden from the main conversation any more —
# which is what buys back the one-hour prompt cache.

@mcp_server.mcp.tool()
def ui_open(port: int = 8787) -> dict:
    """Open the player's screen: start the local web server and return its URL.

    Idempotent — calling it twice returns the running server. Binds 127.0.0.1
    only. The player opens this URL in a browser and plays there; the terminal
    becomes a machine room nobody reads."""
    import webui
    return webui.start(port)


@mcp_server.mcp.tool()
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


@mcp_server.mcp.tool()
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


@mcp_server.mcp.tool()
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


@mcp_server.mcp.tool()
def ui_close() -> dict:
    """Stop the player's screen server."""
    import webui
    return webui.stop()


__all__ = ['paquet_narrateur', 'record_turn', 'companions', 'companion_prompt', 'companion_log', 'ui_open', 'ui_say', 'ui_wait', 'ui_panel', 'ui_close']
