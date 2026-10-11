"""Outils MCP — famille jets et combat (I-233, decoupe de mcp_server.py).

Point d'entree : `mcp_server.py`, qui importe ce module et reexporte ses
outils. Etat partage et helpers communs restent dans `mcp_server` (le module
commun) ; ce fichier y accede via `mcp_server.<nom>`, jamais de copie locale.
"""
from __future__ import annotations

import mcp_server

# I-28 : table par handle_id, posée à `start_combat`, lue par `end_combat`
# pour réconcilier la save avec les PV que le combat tactique a suivis.
# `enemy_hp_max` vient de la spec RÉSOLUE de chaque membre d'encounter, au
# moment où elle est connue (le pont `engine_bridge` n'a lui-même aucun
# accès à la save) — jamais deviné à la clôture.
_combat_rosters: dict[str, dict] = {}


def _player_slug(store) -> str:
    """Le slug du personnage joué.

    Même fiche que `_attack_fiche`/`skill_mod` : `player.md`, dont la
    section porte l'ancre explicite `{#slug}` ou, à défaut, le titre
    slugifié (`coderain/memory.py::parse_entries`, `m.group(2) or
    templates.slugify(title)`) — le gabarit par défaut écrit `## You
    {#player}`, donc "player" tant que personne n'a changé l'ancre. Repli
    sur "player" si `player.md` n'a aucune entrée."""
    try:
        entries = store.entries("player.md")
    except Exception:  # noqa: BLE001 — jamais casser end_combat sur une
                        # fiche illisible ; ce refus se prononce ailleurs
        entries = []
    return entries[0].slug if entries else "player"


# ── start_combat : le joueur passé par son nom (chantier 7a, I-28 suite) ──
# Décision Souhel : dans une partie D&D, le personnage joué est une vraie
# fiche 5e. `_resolve_party_member` ferme le même trou que
# `mcp_server._resolve_encounter_member` (Issue #317) côté `party` : un
# membre passé comme ``{"entity_id": "player", "zone_id": …}`` (ou
# ``pj:player``) est construit depuis la save, jamais une traduction
# devinée. `coderain/rules_engine/engine_bridge.py` ne gagne lui-même aucun
# accès à la save (consigne §2) — toute la lecture/validation reste ici.
def _is_player_entity(store, entity_id: str) -> bool:
    """Même convention que `_reconcile_combat_end` : `entity_id`, privé d'un
    préfixe `pj:`, désigne le joueur s'il vaut "player", "you" ou le slug
    de `player.md` (`_player_slug`)."""
    bare = entity_id[3:] if entity_id.startswith("pj:") else entity_id
    return bare.strip().lower() in ("player", "you", _player_slug(store).lower())


def _build_player_party_member(store, entity_id: str, zone_id: str) -> dict:
    """Lit la fiche 5e du joueur sur la save et rend un dict `PartyMemberSpec`
    (`coderain.rules_engine.party_builder`), prêt pour `party=[...]` de
    `start_combat`. N'inclut PAS `initiative` — voir `_resolve_party_member`.

    Un champ nécessaire absent (score, niveau, classe, espèce, PV) ou un
    identifiant de catalogue qui ne résout pas (`classe`/`espece`/le `srd:`
    d'un objet équipé, via `get_lib_loader()`) est un refus nommé
    `{"error": ...}` — jamais un combat ouvert à moitié construit
    (D-274 §1), jamais une valeur devinée."""
    from coderain.rules_engine import engine as _engine_fn
    from coderain.rules_engine.party_builder import (
        MissingFieldError, party_member_from_sheet)

    rpg_mod = mcp_server._load_rpg()
    cfg = mcp_server._rpg_cfg
    if not rpg_mod.scores_mode(cfg):
        return {"error": "start_combat({'entity_id': 'player', ...}) exige "
                         "une save réglée au vocabulaire 5e (rpg.stats = "
                         "strength/dexterity/constitution/intelligence/"
                         "wisdom/charisma) — cette save porte le vocabulaire "
                         "générique du socle, pas une fiche 5e"}

    rpg = store.rpg_state()
    player = rpg.get("player") or {}
    stats = player.get("stats")
    if not isinstance(stats, dict):
        return {"error": "fiche joueur sans 'stats' — impossible de "
                         "construire sa fiche 5e pour le combat"}

    def _score(name: str):
        got = rpg_mod.opt_int(stats.get(name))
        return None if got is False else got

    scores = {n: _score(n) for n in
             ("strength", "dexterity", "constitution",
              "intelligence", "wisdom", "charisma")}
    absents = sorted(n for n, v in scores.items() if v is None)
    if absents:
        return {"error": f"score(s) 5e manquant(s) ou illisible(s) sur la "
                         f"fiche joueur : {', '.join(absents)}"}

    level = rpg_mod.opt_int(player.get("level"))
    if level is None or level is False:
        return {"error": "champ 'level' manquant ou illisible sur la fiche joueur"}
    class_slug = str(player.get("classe") or "").strip()
    if not class_slug:
        return {"error": "champ 'classe' manquant sur la fiche joueur"}
    species_slug = str(player.get("espece") or "").strip()
    if not species_slug:
        return {"error": "champ 'espece' manquant sur la fiche joueur"}

    loader = _engine_fn().lib_loader.get_lib_loader()
    if loader.get_class(class_slug) is None:
        return {"error": f"classe inconnue du catalogue moteur : {class_slug!r}"}
    if loader.get_species(species_slug) is None:
        return {"error": f"espèce inconnue du catalogue moteur : {species_slug!r}"}

    hp_current = rpg_mod.opt_int(player.get("hp"))
    hp_max = rpg_mod.opt_int(player.get("hp_max"))
    if hp_current is None or hp_current is False or hp_max is None or hp_max is False:
        return {"error": "champ 'hp'/'hp_max' manquant ou illisible sur la "
                         "fiche joueur"}

    derived = rpg_mod.player_combat(store, cfg)
    if derived.get("error"):
        return {"error": derived["error"]}

    items: dict[str, dict] = {}
    try:
        for e in store.entries("items.md"):
            items[e.slug] = {str(k).strip().lower(): v
                             for k, v in e.attrs.items()}
    except Exception:  # noqa: BLE001 — un items.md illisible ne casse pas la fiche
        items = {}
    equipment: list[str] = []
    inv = rpg.get("inventory") or {}
    for slug in sorted(inv):
        held = inv.get(slug)
        if not isinstance(held, dict) or not held.get("equipped"):
            continue
        srd = str((items.get(slug) or {}).get("srd") or "").strip()
        if not srd:
            continue    # objet équipé sans `srd:` : hors du moteur, CA/dégâts
                        # déjà dérivés par `derived_combat` ci-dessus
        if loader.get_item(srd) is None:
            return {"error": f"objet '{slug}' équipé : srd '{srd}' inconnu "
                             f"du catalogue moteur"}
        equipment.append(srd)

    players = store.entries("player.md")
    name = players[0].title if players else "player"

    try:
        return party_member_from_sheet(
            entity_id=entity_id, name=name,
            strength=scores["strength"], dexterity=scores["dexterity"],
            constitution=scores["constitution"],
            intelligence=scores["intelligence"], wisdom=scores["wisdom"],
            charisma=scores["charisma"], hp_current=hp_current, hp_max=hp_max,
            ac=derived.get("ac"), attack_bonus=derived.get("attack_bonus"),
            level=level, class_slug=class_slug, species_slug=species_slug,
            equipment=tuple(equipment), zone_id=zone_id)
    except MissingFieldError as e:
        return {"error": str(e)}


def _resolve_party_member(store, member: dict) -> dict:
    """Comme `mcp_server._resolve_encounter_member` côté `encounter`
    (Issue #317) : un membre de `party` déjà complet (porte `strength`)
    traverse inchangé ; `{"entity_id": "player"|"you"|"pj:player"|…,
    "zone_id": …}` se construit depuis la save (`_build_player_party_member`,
    chantier 7a §5). Un membre qui ne désigne pas le joueur et n'est pas déjà
    complet traverse aussi inchangé — hors périmètre (seul le joueur se
    construit depuis son nom) ; un champ requis qui lui manquerait encore
    sera refusé par le moteur lui-même (validation pydantic de
    `PartyMemberSpec`), pas ici.

    Initiative (chantier 7a §6) : un membre qui n'en fournit pas en reçoit
    une JETÉE ici — d20 + mod Dextérité 5e, même discipline reproductible
    que `roll_check` (graine de la save, cran de `rpg["rolls"]`) — jamais
    une valeur inventée par l'appelant."""
    if "strength" in member:
        return member
    entity_id = str(member.get("entity_id") or "")
    if not _is_player_entity(store, entity_id):
        return member
    built = _build_player_party_member(store, entity_id, member.get("zone_id") or "")
    if built.get("error"):
        return built
    if member.get("initiative") is not None:
        built["initiative"] = int(member["initiative"])
        return built
    rpg_mod = mcp_server._load_rpg()
    rpg = store.rpg_state()
    dex_mod = rpg_mod.ability_mod(built["dexterity"])
    nonce = rpg.get("rolls", 0) + 1
    built["initiative"] = rpg_mod.roll_initiative(dex_mod, rpg.get("seed", 0), nonce)
    rpg["rolls"] = nonce
    store.set_rpg_state(rpg)
    return built


def _reconcile_combat_end(store, live: dict, roster: dict) -> dict:
    """Réconcilie `store.rpg_state()` avec la dernière vue du moteur (I-28).

    `live` = `get_bridge().live(handle_id)` pris JUSTE AVANT la clôture
    (`tracked_hp`, `dead_ids`). `roster` = table posée à `start_combat`
    (`party` : les entity_id bruts de la party ; `enemy_hp_max` : entity_id
    -> hp_max de la spec résolue de l'encounter). Une seule enveloppe
    `apply_envelope` (D-141) pour toute la réconciliation — jamais une
    écriture directe de `rpg_state`, exactement comme `attack`.

    Un membre de l'`encounter` est un ennemi sous son `entity_id` (slugifié
    — même fonction que `rpg.apply` applique déjà à la clé `enemies.<slug>`,
    donc le même entity_id retombe toujours sur le même slug). Un membre de
    la `party` est le joueur si son `entity_id`, privé d'un préfixe `pj:`,
    vaut "player", "you" ou `_player_slug(store)` ; tout autre membre de la
    party n'est pas écrit et revient sous `skipped`.

    Le delta écrit est PV du moteur à la clôture − PV de la save maintenant
    (hp_max de la spec résolue tenant lieu de "PV de la save maintenant"
    pour un ennemi encore inconnu — même convention que `attack` l.224-227 :
    un ennemi neuf entre dans `rpg.apply` à son hp_max, AVANT que le delta
    ne soit appliqué). Delta nul -> rien n'est écrit pour ce membre (un
    ennemi inconnu reçoit quand même son hp_max : c'est déjà une écriture).
    """
    from coderain.templates import slugify

    tracked_hp = live.get("tracked_hp") or {}
    dead_ids = set(live.get("dead_ids") or [])
    player_slug = _player_slug(store)

    def _hp_of(entity_id: str) -> int:
        # I-28 : `dead_ids` fait foi sur la mort, jamais une lecture brute
        # de `tracked_hp` qui pourrait rester positive ou filer en négatif
        # selon ce que le moteur choisit d'y laisser.
        return 0 if entity_id in dead_ids else int(tracked_hp[entity_id])

    rpg_avant = store.rpg_state()
    player_hp_avant = int((rpg_avant.get("player") or {}).get("hp", 0))
    enemies_avant = dict(rpg_avant.get("enemies") or {})

    player_entity_id = None
    skipped: list[str] = []
    for entity_id in roster.get("party") or []:
        reste = entity_id[3:] if entity_id.startswith("pj:") else entity_id
        if reste in ("player", "you", player_slug):
            player_entity_id = entity_id
        else:
            skipped.append(entity_id)

    env_deltas: dict = {}
    if player_entity_id is not None and player_entity_id in tracked_hp:
        player_delta = _hp_of(player_entity_id) - player_hp_avant
        if player_delta:
            env_deltas["hp_delta"] = player_delta

    enemy_before: dict[str, int] = {}
    env_enemies: dict = {}
    for entity_id, hp_max in (roster.get("enemy_hp_max") or {}).items():
        if entity_id not in tracked_hp or hp_max is None:
            continue
        slug = slugify(entity_id)
        hp_moteur = _hp_of(entity_id)
        known = enemies_avant.get(slug)
        if known is not None:
            hp_avant = int(known.get("hp", 0))
            delta = hp_moteur - hp_avant
            if delta:
                env_enemies[slug] = {"hp_delta": delta}
        else:
            hp_avant = int(hp_max)
            delta = hp_moteur - hp_avant
            spec = {"hp_max": int(hp_max)}
            if delta:
                spec["hp_delta"] = delta
            env_enemies[slug] = spec
        enemy_before[slug] = hp_avant
    if env_enemies:
        env_deltas["enemies"] = env_enemies

    if env_deltas:
        mcp_server.apply_envelope(mcp_server.json.dumps({"deltas": env_deltas}))

    rpg_apres = store.rpg_state()
    reconciled: dict = {"player": None, "enemies": {}, "skipped": skipped}
    if player_entity_id is not None and player_entity_id in tracked_hp:
        p_apres = rpg_apres.get("player") or {}
        reconciled["player"] = {
            "hp_before": player_hp_avant,
            "hp_after": int(p_apres.get("hp", player_hp_avant)),
        }
    enemies_apres = rpg_apres.get("enemies") or {}
    for slug, hp_avant in enemy_before.items():
        e = enemies_apres.get(slug)
        reconciled["enemies"][slug] = {
            "hp_before": hp_avant,
            "hp_after": int(e.get("hp", 0)) if e is not None else 0,
            "defeated": e is None,
        }
    return reconciled


@mcp_server.mcp.tool()
def roll_check(stat: str, dc: int = 12, skill: str = "",
               actor: str = "player") -> dict:
    """Roll a d20 + stat modifier vs DC. Engine-rolled, deterministic (seed + nonce).

    The LLM NEVER rolls dice — it proposes a check, this tool resolves it.
    A `skill` outside the actor's sheet + the canonical rules list (I-213
    corollary 3) is refused: {"error": "unknown skill ..."}. A known skill
    resolves either way, with `trained` saying whether the actor is proficient.
    An `actor` that is neither "player"/"you" nor a known entry of
    characters.md is refused (I-19): {"error": "unknown actor ..."} naming
    the admitted values — nothing is rolled, nothing borrowed.
    A stat absent from the actor's sheet is looked up in `rpg.provisoire`
    (D-275) before being refused (I-19): {"error": "unknown stat ..."}
    naming the sheet's own stats — a check NEVER silently rolls at mod 0 for
    a stat nobody wrote. A provisoire match still resolves, flagged
    `provisoire: true`, exactly as before.
    Returns {dc, mod, roll, total, success, win_chance, skill?, trained?,
    provisoire?, provisoire_ids?} | {"error": ...}."""
    store = mcp_server._require_store()
    rpg_mod = mcp_server._load_rpg()
    from coderain.templates import slugify
    from coderain.validator import fold_skill, known_skills
    rpg = store.rpg_state()
    actor_slug = slugify(actor) if actor and actor not in ("player", "you") else "player"
    sk_mod = 0
    if skill:
        valid = known_skills(store, actor_slug)
        if fold_skill(skill) not in valid:
            return {"error": f"unknown skill '{skill}' "
                              f"(use one of: {', '.join(sorted(valid))})"}
        sk_mod = rpg_mod.skill_mod(store, actor_slug, skill, mcp_server._rpg_cfg)
    if actor_slug == "player":
        actor_stats = rpg.get("player", {}).get("stats", {})
    else:
        npc = next((e for e in store.entries("characters.md")
                    if e.slug == actor_slug), None)
        # I-19 : un acteur ni "player"/"you" ni trouvé dans characters.md ne
        # se jette plus silencieusement à 0 — refus nommant les valeurs
        # admises, même forme que le refus de compétence inconnue ci-dessus.
        if npc is None:
            known = sorted(e.slug for e in store.entries("characters.md"))
            return {"error": f"unknown actor '{actor}' "
                              f"(use one of: player, {', '.join(known)})"}
        actor_stats = npc.stats()
    # D-275 : le modificateur absent de la fiche se cherche dans
    # `rpg.provisoire` APRÈS la fiche — et le jet DIT qu'il l'a emprunté.
    stat_key = stat.strip().lower()
    pose = None
    if stat_key in actor_stats:
        base = int(actor_stats[stat_key])
    else:
        from coderain import bouchage as bouchage_mod
        pose, valeur = bouchage_mod.valeur_provisoire(rpg, actor_slug, stat_key)
        # I-19 : une stat ni sur la fiche ni posée en valeur provisoire ne se
        # jette plus silencieusement à 0 — même refus nommé que ci-dessus.
        if pose is None:
            valides = sorted(actor_stats) or ["(aucune sur cette fiche)"]
            return {"error": f"unknown stat '{stat}' for '{actor_slug}' "
                              f"(use one of: {', '.join(valides)})"}
        base = bouchage_mod.entier(valeur) or 0
    mod = base + sk_mod
    seed = rpg.get("seed", 0)
    nonce = rpg.get("rolls", 0) + 1
    result = rpg_mod.roll_check(mod, dc, seed, nonce)
    rpg["rolls"] = nonce
    store.set_rpg_state(rpg)
    if skill:
        result["skill"] = skill
        result["trained"] = sk_mod > 0
    if pose is not None:
        result["provisoire"] = True
        result["provisoire_ids"] = [pose]
    return result


@mcp_server.mcp.tool()
def death_save() -> dict:
    """Resolve ONE death saving throw for the player at 0 HP (I-213, D-271 §1
    — straight 5e: d20, no modifier, success >= 10; 3 successes -> stabilized,
    3 failures -> dead; natural 20 revives at 1 HP; natural 1 counts as two
    failures). Engine-rolled, deterministic. Refuses (returns {"error": ...})
    when the player isn't `downed`, is already `stabilized`, or already
    `dead` — check the sheet (ui_sheet / get_world_state) first.

    Damage taken while already downed at 0 HP counts as an automatic failure
    on its own (apply_envelope's hp_delta path) — this tool is only for the
    deliberate once-a-turn save, not for damage resolution.

    Writes state.json directly (rpg.death_save -> store.set_rpg_state); unlike
    apply_envelope this does not append to events.jsonl — same precedent as
    roll_check/roll_damage's nonce bookkeeping (see rpg.death_save docstring).
    Returns {roll, dc, outcome, death_saves: {successes, failures},
    transition: "stabilized"|"dead"|"revived"|None, hp, conditions}."""
    store = mcp_server._require_store()
    rpg_mod = mcp_server._load_rpg()
    return rpg_mod.death_save(store, mcp_server._rpg_cfg)


@mcp_server.mcp.tool()
def roll_damage(formula: str) -> dict:
    """Roll a damage formula ('1d8+3', or a stat block's full 'degats' field
    like '9 (1d8+3) slashing') — engine-rolled, deterministic (seed + nonce),
    same RNG discipline as roll_check.

    The LLM never rolls damage either: a scripted attack (e.g. a monster
    fiche's `degats`) proposes the formula, this tool resolves it. Feed the
    result's `total` into apply_envelope as a negative `hp_delta` (player) or
    `deltas.enemies.<slug>.hp_delta` (monster) — the guichet (D-141) already
    validates and clamps that delta; this tool only produces the number.
    Returns {formula, dice, modifier, total}. Raises on a formula with no
    recognizable dice notation."""
    store = mcp_server._require_store()
    rpg_mod = mcp_server._load_rpg()
    rpg = store.rpg_state()
    seed = rpg.get("seed", 0)
    nonce = rpg.get("rolls", 0) + 1
    result = rpg_mod.roll_damage(formula, seed, nonce)
    rpg["rolls"] = nonce
    store.set_rpg_state(rpg)
    return result


@mcp_server.mcp.tool()
def attack(attacker: str = "player", target: str = "monstre") -> dict:
    """Résoudre UNE attaque de bout en bout : toucher, dégâts, application.

    Le LLM choisit l'action, jamais les chiffres. Cet outil lit les DEUX
    fiches — bonus d'attaque et dés de dégâts de l'attaquant, CA (et PV) de la
    cible —, jette le d20 + bonus contre la CA puis les dégâts sur touche (même
    discipline RNG que roll_check/roll_damage : seed + nonce, un cran de
    `rpg["rolls"]` par jet), et APPLIQUE la perte de PV par le guichet
    (D-141, `apply_envelope`) : `hp_delta` sur le joueur — avec le `downed`/
    `dead` de D-271 — ou `deltas.enemies.<slug>.hp_delta` sur la cible.

    `attacker`/`target` : "player", ou un slug (entrée de `characters.md`,
    sinon record de créature du module).

    UN NOMBRE ABSENT EST UN REFUS (D-274 §1) : pas de CA sur la cible, pas de
    dés sur l'attaquant, pas de PV sur une cible que le combat ne connaît pas
    encore → {"error": "missing <champ> on <fiche>"}. Rien n'est jeté ni
    appliqué dans ce cas, et aucun défaut n'est emprunté à qui que ce soit.

    SAUF si le trou a déjà été bouché (D-275) : `rpg.provisoire` est consulté
    APRÈS la fiche et AVANT le refus ; une valeur provisoire enregistrée pour
    ce champ et cette fiche s'applique, et le retour la signale
    (`provisoire: true`, `provisoire_ids`). Un même trou ne se demande donc
    pas deux fois — voir `demander_bouchage`/`enregistrer_bouchage`.

    Rend {attacker, target, roll, attack_bonus, total, target_ac, hit,
    damage: {formula, dice, total}|null, applied: {...}|null,
    provisoire?: true, provisoire_ids?: [...]}."""
    store = mcp_server._require_store()
    rpg_mod = mcp_server._load_rpg()
    if not store.rpg_enabled():
        return {"error": "rpg mechanics are disabled on this save"}
    atk = mcp_server._attack_fiche(store, attacker)
    if atk.get("error"):
        return {"error": atk["error"]}
    tgt = mcp_server._attack_fiche(store, target)
    if tgt.get("error"):
        return {"error": tgt["error"]}
    if atk["slug"] == tgt["slug"]:
        return {"error": f"'{atk['slug']}' cannot attack itself"}

    # --- refus AVANT tout jet : un dé consommé sur une attaque impossible
    # décalerait le nonce pour rien.
    if atk.get("attack_bonus") is None:
        return {"error": f"missing attaque_bonus on {atk['slug']}"}
    if not atk.get("damage"):
        return {"error": f"missing degats on {atk['slug']}"}
    if tgt.get("ac") is None:
        return {"error": f"missing ca on {tgt['slug']}"}
    rpg = store.rpg_state()
    known_enemy = tgt["slug"] in (rpg.get("enemies") or {})
    if tgt["kind"] == "npc" and not known_enemy and tgt.get("hp_max") is None:
        return {"error": f"missing pv on {tgt['slug']} "
                         f"(the encounter does not know its HP yet)"}

    seed = rpg.get("seed", 0)
    nonce = rpg.get("rolls", 0) + 1
    hit_roll = rpg_mod.roll_check(atk["attack_bonus"], tgt["ac"], seed, nonce)
    rpg["rolls"] = nonce
    store.set_rpg_state(rpg)

    out = {"attacker": atk["slug"], "target": tgt["slug"],
           "roll": hit_roll["roll"], "attack_bonus": atk["attack_bonus"],
           "total": hit_roll["total"], "target_ac": tgt["ac"],
           "hit": bool(hit_roll["success"]), "damage": None, "applied": None}
    # D-275 : si un des nombres vient d'un bouchage, l'attaque le DIT — la
    # valeur est provisoire jusqu'à l'entre-deux (#97), jamais canonique.
    poses = list(atk.get("provisoire_ids") or []) + \
        list(tgt.get("provisoire_ids") or [])
    if poses:
        out["provisoire"] = True
        out["provisoire_ids"] = poses
    if not out["hit"]:
        return out

    rpg = store.rpg_state()
    nonce = rpg.get("rolls", 0) + 1
    try:
        dmg = rpg_mod.roll_damage(atk["damage"], seed, nonce)
    except ValueError as e:
        return {"error": f"unreadable degats on {atk['slug']}: {e}"}
    rpg["rolls"] = nonce
    store.set_rpg_state(rpg)
    out["damage"] = dmg

    # --- application par le guichet, jamais une écriture directe.
    if tgt["kind"] == "player":
        env = {"deltas": {"hp_delta": -dmg["total"]}}
    else:
        spec = {"hp_delta": -dmg["total"]}
        if not known_enemy:
            spec["hp_max"] = tgt["hp_max"]     # lu sur la fiche, pas deviné
        env = {"deltas": {"enemies": {tgt["slug"]: spec}}}
    events = mcp_server.apply_envelope(mcp_server.json.dumps(env))

    after = store.rpg_state()
    if tgt["kind"] == "player":
        p = after.get("player") or {}
        applied = {"events": events, "target_hp": p.get("hp"),
                   "target_hp_max": p.get("hp_max"),
                   "conditions": list(p.get("conditions") or [])}
    else:
        e = (after.get("enemies") or {}).get(tgt["slug"])
        applied = {"events": events,
                   "target_hp": (e or {}).get("hp", 0),
                   "target_hp_max": (e or {}).get("hp_max", tgt.get("hp_max")),
                   "defeated": e is None}
    out["applied"] = applied
    return out


@mcp_server.mcp.tool()
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


@mcp_server.mcp.tool()
async def start_combat(session_id: str, party: list[dict],
                       encounter: list[dict], rng_seed: int,
                       zones: list[str] | None = None) -> dict:
    """Ouvre un combat détenu par dnd5e-engine ; retourne handle_id.

    party/encounter = specs du moteur (PartyMemberSpec / EncounterMemberSpec :
    entity_id, name, initiative, hp_current, hp_max, ac, zone_id... ; un monstre
    jouable porte monster_template_slug ex. "goblin-warrior"). rng_seed rend le
    combat déterministe : mêmes graines ⇒ mêmes dés.

    Retour: ... "warnings": [{entity_id, monster_template_slug, reason}, ...]
    — un membre d'encounter dont le monster_template_slug ne résout à rien
    (absent ou pas dans dnd5e-srd-data) n'a aucun comportement de combat ; le
    moteur le résout en pass mais CET avertissement le signale explicitement
    (I-205), il revient aussi sur chaque monster_turn tant que le combat
    dure. Pont minimal pour mapper un record de module vers un comportement
    jouable : coderain.rules_engine.monster_bridge.

    Un membre d'`encounter` sans `monster_template_slug` est résolu par son
    `entity_id` — même chemin de lecture que `attack` (`characters.md`, à
    défaut record de module) — et construit par `encounter_member_from_record`
    (Issue #317) : le record absent est un refus explicite, `{"error": ...}`,
    avant toute ouverture de combat, jamais un membre sans comportement.

    Un membre de `party` passé par son nom — `{"entity_id": "player", "zone_id":
    …}` (ou `pj:player`) — est construit depuis la fiche 5e de la save par
    `_build_player_party_member` (chantier 7a, D&D réel) : scores, PV/PV max,
    CA et bonus d'attaque dérivés, niveau/classe/espèce, équipement (les
    `srd:` des objets équipés). Un champ requis absent ou un identifiant de
    catalogue (classe/espèce/`srd:`) qui ne résout pas est un refus explicite,
    avant toute ouverture de combat. Une initiative non fournie est JETÉE
    (d20 + mod Dextérité, graine de la save) plutôt qu'inventée par
    l'appelant — `"initiatives_rolled"` du retour dit ce qui a été jeté.
    """
    store = None
    resolved_party = []
    rolled_initiatives: dict[str, int] = {}
    for member in party:
        if "strength" in member:
            resolved_party.append(member)
            continue
        if store is None:
            store = mcp_server._require_store()
        avait_initiative = member.get("initiative") is not None
        m = _resolve_party_member(store, member)
        if m.get("error"):
            return {"error": m["error"]}
        if not avait_initiative and "initiative" in m:
            rolled_initiatives[str(m.get("entity_id"))] = m["initiative"]
        resolved_party.append(m)
    resolved = []
    for member in encounter:
        if member.get("monster_template_slug"):
            resolved.append(member)
            continue
        if store is None:
            store = mcp_server._require_store()
        m = mcp_server._resolve_encounter_member(store, member)
        if m.get("error"):
            return {"error": m["error"]}
        resolved.append(m)
    result = await mcp_server.get_bridge().start_combat(
        session_id=session_id, party=resolved_party, encounter=resolved,
        rng_seed=rng_seed, zones=zones)
    mcp_server._record_combat_events(result.get("events", []))
    if rolled_initiatives:
        result["initiatives_rolled"] = rolled_initiatives
    handle_id = result.get("handle_id")
    if handle_id:
        # I-28 : posé ICI, pas à `end_combat` — `resolved` porte le hp_max
        # de la spec résolue de chaque membre d'encounter (lu sur le record
        # module/characters.md avant toute ouverture), jamais deviné à la
        # clôture.
        _combat_rosters[handle_id] = {
            "party": [str(p.get("entity_id")) for p in resolved_party
                     if p.get("entity_id") is not None],
            "enemy_hp_max": {str(m.get("entity_id")): m.get("hp_max")
                             for m in resolved
                             if m.get("entity_id") is not None},
        }
    return result


@mcp_server.mcp.tool()
async def submit_intent(handle_id: str, actor_id: str, intent: dict) -> dict:
    """Soumet l'intention du personnage dont c'est le tour (PlayerIntent).

    intent = {"intent_type": "attack"|"move"|"pass"|..., target_id?,
    weapon_id?, target_zone_id?, ...}. Une attaque exige weapon_id résolvable
    du corpus. Refus du moteur (mauvais tour...) => IntentRejectedError brute.
    """
    result = await mcp_server.get_bridge().submit_intent(handle_id, actor_id, intent)
    mcp_server._record_combat_events(result.get("events", []))
    return result


@mcp_server.mcp.tool()
async def monster_turn(handle_id: str) -> dict:
    """Fait jouer par l'IA du moteur le tour du monstre courant.

    "warnings" porte un avertissement explicite si l'acteur dont c'est le
    tour n'a jamais eu de monster_template_slug résolu (I-205) : le tour se
    joue quand même (pass), mais jamais silencieusement.
    """
    result = await mcp_server.get_bridge().monster_turn(handle_id)
    mcp_server._record_combat_events(result.get("events", []))
    return result


@mcp_server.mcp.tool()
async def end_combat(handle_id: str) -> dict:
    """Clôt le combat : issue du moteur (ended_reason victory|defeat_tpk|
    flee|forced, morts, XP). Le handle est ensuite invalidé côté pont.

    I-28 : juste avant de clore, lit la DERNIÈRE vue du moteur
    (`tracked_hp`, `dead_ids` — `get_bridge().live`), puis clôt, puis
    réconcilie `store.rpg_state()` avec elle par le guichet `apply_envelope`
    (D-141) — jamais une écriture directe, exactement comme `attack`. Le
    moteur fait foi pour tout ce qu'il a suivi pendant le combat (docstring
    du pont : « pendant un combat, l'état mécanique vit dans le moteur »).

    Un membre de l'`encounter` est un ennemi sous son `entity_id` (slugifié).
    Un membre de la `party` est le joueur si son `entity_id`, privé d'un
    préfixe "pj:", vaut "player"/"you" ou le slug du personnage joué
    (`store.entries("player.md")[0].slug`) ; tout autre membre de la party
    n'est pas écrit — il revient sous `skipped`.

    Rend {outcome, events, reconciled}. `reconciled` =
    {"player": {"hp_before", "hp_after"} | null,
     "enemies": {slug: {"hp_before", "hp_after", "defeated"}},
     "skipped": [entity_id, ...]} | null — null si aucune save n'est
    chargée (`_store` nul) : la clôture est inchangée, sans erreur."""
    bridge = mcp_server.get_bridge()
    live_avant_cloture = bridge.live(handle_id)
    result = await bridge.end_combat(handle_id)
    roster = _combat_rosters.pop(handle_id, None)
    reconciled = None
    if mcp_server._store is not None:
        reconciled = _reconcile_combat_end(
            mcp_server._store, live_avant_cloture, roster or {})
    result["reconciled"] = reconciled
    return result


@mcp_server.mcp.tool()
async def narration_events(handle_id: str) -> dict:
    """Événements de combat pendants depuis le dernier fetch (drain non
    bloquant). Même file que l'itérateur narration_events du moteur : premier
    arrivé premier servi ; MCP étant requête/réponse, on ne bloque jamais sur
    une file vide — rappeler après chaque action.
    """
    bridge = mcp_server.get_bridge()
    return {"events": bridge.drain_events(handle_id),
            "live": bridge.live(handle_id)}


__all__ = ['roll_check', 'death_save', 'roll_damage', 'attack', 'resolve_check', 'start_combat', 'submit_intent', 'monster_turn', 'end_combat', 'narration_events']
