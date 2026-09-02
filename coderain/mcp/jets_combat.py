"""Outils MCP — famille jets et combat (I-233, decoupe de mcp_server.py).

Point d'entree : `mcp_server.py`, qui importe ce module et reexporte ses
outils. Etat partage et helpers communs restent dans `mcp_server` (le module
commun) ; ce fichier y accede via `mcp_server.<nom>`, jamais de copie locale.
"""
from __future__ import annotations

import mcp_server

@mcp_server.mcp.tool()
def roll_check(stat: str, dc: int = 12, skill: str = "",
               actor: str = "player") -> dict:
    """Roll a d20 + stat modifier vs DC. Engine-rolled, deterministic (seed + nonce).

    The LLM NEVER rolls dice — it proposes a check, this tool resolves it.
    A `skill` outside the actor's sheet + the canonical rules list (I-213
    corollary 3) is refused: {"error": "unknown skill ..."}. A known skill
    resolves either way, with `trained` saying whether the actor is proficient.
    A stat absent from the actor's sheet is looked up in `rpg.provisoire`
    (D-275) before falling back to 0 — a borrowed modifier is flagged
    `provisoire: true`.
    Returns {dc, mod, roll, total, success, win_chance, skill?, trained?,
    provisoire?, provisoire_ids?}."""
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
        actor_stats = npc.stats() if npc else {}
    # D-275 : le modificateur absent de la fiche se cherche dans
    # `rpg.provisoire` APRÈS la fiche — et le jet DIT qu'il l'a emprunté.
    stat_key = stat.strip().lower()
    pose = None
    if stat_key in actor_stats:
        base = int(actor_stats[stat_key])
    else:
        from coderain import bouchage as bouchage_mod
        pose, valeur = bouchage_mod.valeur_provisoire(rpg, actor_slug, stat_key)
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
    """
    result = await mcp_server.get_bridge().start_combat(
        session_id=session_id, party=party, encounter=encounter,
        rng_seed=rng_seed, zones=zones)
    mcp_server._record_combat_events(result.get("events", []))
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
    flee|forced, morts, XP). Le handle est ensuite invalidé côté pont."""
    return await mcp_server.get_bridge().end_combat(handle_id)


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
