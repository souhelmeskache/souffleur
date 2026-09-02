"""Outils MCP — famille bouchage (D-275, Issue #253).

L'organe de bouchage est en TROIS pièces, et cette découpe n'est pas un
détail d'implémentation :

  1. `demander_bouchage` PRÉPARE un dossier — aucun appel réseau, aucun
     import de `coderain/llm.py` (D-263 : le moteur ne parle à personne) ;
  2. un sous-agent du harnais JUGE (voir `tools/prompts/banc-mj.md`,
     § Trou de règle) — le Director, lui, ne fabrique jamais un nombre
     (D-274 §1) ;
  3. `enregistrer_bouchage` ENREGISTRE la valeur rendue, dans
     `rpg.provisoire` et nulle part ailleurs.

Ce que ces outils n'écrivent JAMAIS : une fiche, un record de module,
`items.md`, une règle du moteur. La valeur reste provisoire et tracée
jusqu'à ce que l'Auteur de l'entre-deux (#97, hors périmètre) l'entérine
ou la rejette à l'inter-scénario.

Point d'entrée : `mcp_server.py`, qui importe ce module et réexporte ses
outils — même convention que les autres familles (I-233).
"""
from __future__ import annotations

import mcp_server

from coderain import bouchage as organe


def _trou_normalise(trou: object) -> tuple[dict, str]:
    """Le trou tel qu'il sera tracé, ou `({}, motif de refus)`."""
    if isinstance(trou, str):
        try:
            trou = mcp_server.json.loads(trou)
        except ValueError:
            return {}, "trou must be an object (type, champ, fiche, contexte)"
    if not isinstance(trou, dict):
        return {}, "trou must be an object (type, champ, fiche, contexte)"
    type_ = organe.normaliser(trou.get("type"))
    if type_ not in organe.TYPES:
        return {}, f"unknown trou type {trou.get('type')!r} " \
                   f"(use one of: {', '.join(organe.TYPES)})"
    if not str(trou.get("champ") or "").strip():
        return {}, "missing 'champ' on trou (what number or rule is absent)"
    if not str(trou.get("contexte") or "").strip():
        return {}, ("missing 'contexte' on trou (one sentence: what is being "
                    "attempted) — the dossier IS the judge's whole prompt")
    propre = {"type": type_, "champ": str(trou["champ"]).strip(),
              "fiche": (str(trou["fiche"]).strip()
                        if str(trou.get("fiche") or "").strip() else None),
              "contexte": str(trou["contexte"]).strip()}
    if str(trou.get("modifie") or "").strip():
        propre["modifie"] = str(trou["modifie"]).strip()
    return propre, ""


def _champ_deja_present(store, trou: dict) -> bool:
    """Le champ visé est-il DÉJÀ écrit sur la fiche ? Alors ce n'est pas un
    trou (D-275 §5) — la fiche fait foi, on ne bouche pas par-dessus.

    Lit la fiche de combat (`_attack_fiche` : `ca`/`pv`/`attaque_bonus`/
    `degats` normalisés) ET les attributs bruts (stats du joueur, entrée de
    `characters.md`) — une stat absente de la fiche de combat est un trou
    tout aussi légitime qu'une CA absente."""
    fiche_dem = trou.get("fiche")
    slug = organe.fiche_canon(fiche_dem)
    if not slug:
        return False        # trou sans fiche : rien à confronter
    champ = organe.champ_canon(trou["champ"])
    fiche = mcp_server._attack_fiche(store, fiche_dem or "player")
    if not fiche.get("error"):
        cle = organe.CHAMPS_FICHE.get(champ)
        if cle and fiche.get(cle) not in (None, ""):
            return True
    bruts: dict[str, object] = {}
    if slug == "player":
        joueur = store.rpg_state().get("player")
        if isinstance(joueur, dict):
            bruts.update(joueur)
            if isinstance(joueur.get("stats"), dict):
                bruts.update(joueur["stats"])
    else:
        for e in store.entries("characters.md"):
            if e.slug == slug:
                bruts.update(e.attrs or {})
                break
    for cle, valeur in bruts.items():
        if organe.champ_canon(cle) != champ:
            continue
        if valeur not in (None, "", [], {}):
            return True
    return False


@mcp_server.mcp.tool()
def demander_bouchage(trou: dict) -> dict:
    """PRÉPARER le dossier d'un petit trou de règle (D-275) — ne juge rien,
    n'appelle personne, n'écrit aucune valeur.

    `trou` = {"type": "nombre"|"regle", "champ": "<le champ absent>",
    "fiche": "player"|<slug>|null, "contexte": "<une phrase : ce qui est
    tenté>"}. Un trou de type `regle` qui demanderait de modifier une fiche,
    un record ou une règle du moteur le DIT dans `modifie` — la garde lit
    cette déclaration et refuse, elle ne juge pas le fond.

    REFUSE ({"error": ...}) quand le trou n'est PAS petit au sens D-275 §5 :
    un `type: nombre` dont le champ est déjà écrit sur la fiche (ce n'est pas
    un trou), un `type: regle` de portée déclarée interdite, un trou déjà
    bouché (l'entrée provisoire existe : on ne demande pas deux fois), ou le
    seuil de bouchages du scénario atteint — c'est alors l'amont qu'il faut
    réparer, pas la partie qu'il faut rafistoler.

    Sinon rend le DOSSIER — et ce dossier est, tel quel, le prompt ENTIER du
    sous-agent juge : {id, trou, scene (résumé mécanique, aucune prose),
    repli (table de repli du save, si présente), regles (extrait du
    vocabulaire fermé de docs/couverture-moteur.md), consigne (texte fixe)}.
    Le dossier est journalisé dans `events.jsonl` (type `bouchage_demande`).
    """
    store = mcp_server._require_store()
    propre, motif = _trou_normalise(trou)
    if motif:
        return {"error": motif}

    rpg = store.rpg_state()
    if organe.nb_scenario(rpg) >= organe.SEUIL_SCENARIO:
        return {"error": f"seuil D-275 atteint ({organe.SEUIL_SCENARIO}) : "
                         f"réparer l'amont"}

    if propre.get("modifie") and organe.normaliser(propre["modifie"]) in \
            tuple(organe.normaliser(p) for p in organe.PORTEES_INTERDITES):
        return {"error": f"trou hors D-275 §5 : le dossier déclare modifier "
                         f"{propre['modifie']!r} — une fiche, un record ou "
                         f"une règle du moteur ne se bouche pas en partie"}

    ident = organe.id_trou(propre)
    if ident in organe.entrees(rpg):
        return {"error": f"trou déjà bouché ({ident}) : une valeur provisoire "
                         f"est enregistrée, elle s'applique déjà"}

    if propre["type"] == "nombre" and _champ_deja_present(store, propre):
        return {"error": f"'{propre['champ']}' est déjà écrit sur "
                         f"{propre['fiche'] or 'player'} : ce n'est pas un trou"}

    dossier = {
        "id": ident,
        "trou": propre,
        "scene": organe.resume_scene(store),
        "repli": organe.table_repli(store, propre),
        "regles": organe.regles_concernees(propre),
        "consigne": organe.CONSIGNE,
    }
    store.append_event_log({"turn": len(store.turns()),
                            "type": "bouchage_demande", "id": ident,
                            "trou": propre})
    return dossier


@mcp_server.mcp.tool()
def enregistrer_bouchage(id: str, valeur: str, justification: str) -> dict:
    """ENREGISTRER la valeur rendue par le sous-agent juge, telle quelle.

    `id` = celui du dossier rendu par `demander_bouchage` (sans dossier, pas
    d'enregistrement : la trace commence au dossier). `valeur` = la valeur ou
    la micro-règle rendue ; `justification` = les deux lignes du juge. Le
    Director ne reformule ni ne complète ni l'une ni l'autre.

    Écrit `rpg.provisoire[<id>] = {trou, valeur, justification, tour, scene}`
    par le chemin d'application de `state.json` (D-141/I-94), incrémente
    `rpg.provisoire.nb_scenario`, et journalise `events.jsonl` (type
    `bouchage_enregistre`). RIEN d'autre n'est touché : ni une fiche, ni un
    record, ni `items.md`, ni une règle du moteur.

    La valeur s'applique ensuite d'elle-même : `attack`, `derived_combat` et
    `roll_check` consultent `rpg.provisoire` après la fiche et avant de
    refuser, et marquent `provisoire: true` dans leur retour."""
    store = mcp_server._require_store()
    ident = str(id or "").strip()
    if not ident:
        return {"error": "missing id (the one demander_bouchage returned)"}
    if not str(valeur).strip():
        return {"error": "missing valeur (what the judge returned)"}
    if not str(justification or "").strip():
        return {"error": "missing justification (the judge's two lines)"}

    trou = _trou_du_dossier(store, ident)
    if trou is None:
        return {"error": f"no bouchage dossier for '{ident}' — call "
                         f"demander_bouchage first (D-275: the trace starts "
                         f"at the dossier)"}

    rpg = store.rpg_state()
    deja = organe.entrees(rpg)
    if ident not in deja and organe.nb_scenario(rpg) >= organe.SEUIL_SCENARIO:
        return {"error": f"seuil D-275 atteint ({organe.SEUIL_SCENARIO}) : "
                         f"réparer l'amont"}

    entree = {"trou": trou, "valeur": str(valeur).strip(),
              "justification": str(justification).strip(),
              "tour": len(store.turns()), "scene": organe.resume_scene(store)}
    prov = dict(organe.bloc(rpg))
    prov[ident] = entree
    prov[organe.CLE_COMPTEUR] = organe.nb_scenario(rpg) + (
        0 if ident in deja else 1)
    rpg["provisoire"] = prov
    store.set_rpg_state(rpg)
    store.append_event_log({"turn": len(store.turns()),
                            "type": "bouchage_enregistre", "id": ident,
                            "trou": trou, "valeur": entree["valeur"],
                            "justification": entree["justification"]})
    return {"id": ident, "provisoire": entree,
            "nb_scenario": prov[organe.CLE_COMPTEUR],
            "seuil": organe.SEUIL_SCENARIO}


def _trou_du_dossier(store, ident: str) -> dict | None:
    """Le `trou` du dernier dossier préparé pour cet id, relu dans
    `events.jsonl` — la trace du dossier est ce qui autorise
    l'enregistrement, et c'est elle qui porte la description du trou (l'outil
    d'enregistrement ne la redemande pas au Director, qui la reformulerait)."""
    trouve = None
    for ligne in store.read("memory/events.jsonl").splitlines():
        try:
            rec = mcp_server.json.loads(ligne)
        except ValueError:
            continue
        if (isinstance(rec, dict) and rec.get("type") == "bouchage_demande"
                and rec.get("id") == ident
                and isinstance(rec.get("trou"), dict)):
            trouve = rec["trou"]
    return trouve


__all__ = ['demander_bouchage', 'enregistrer_bouchage']
