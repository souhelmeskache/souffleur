"""Outils MCP — famille auteur (I-233, decoupe de mcp_server.py).

Point d'entree : `mcp_server.py`, qui importe ce module et reexporte ses
outils. Etat partage et helpers communs restent dans `mcp_server` (le module
commun) ; ce fichier y accede via `mcp_server.<nom>`, jamais de copie locale.
"""
from __future__ import annotations

import mcp_server

@mcp_server.mcp.tool()
def auteur_bloc_cadre(acte_id: str, regime: str, actes_path: str = "") -> dict:
    """Le bloc cadre de l'Auteur pour UN acte, UN régime — CODE seul, aucune
    génération : la session LIT ce bloc et écrit elle-même le module.

    Rend {"bloc_cadre", "bloc_regime", "bloc_formes", "contraintes_transverses",
    "objectifs"} :
    - bloc_cadre : les trois lectures de l'acte (remplissage mesuré au vécu
      promu, pièces de divergence, raccord) — `acte.bloc_cadre`.
    - bloc_regime : les exigences du régime choisi (pont|rattrapage|
      aiguillage) — le régime est un JUGEMENT d'Auteur/Souhel fait par la
      session sur les lectures du cadre, jamais déduit ici.
    - bloc_formes : le stock de formes narratives (D-261), déclaration
      obligatoire.
    - contraintes_transverses : états/potentiels jamais une séquence
      imposée · texte de module source tel que le convertisseur sait
      l'ingérer (D-262 §2, transverse aux trois régimes).
    - objectifs : les objectifs du retour 2 pour ce régime, en TEXTE — ce que
      `auteur_valider_ecriture`/`auteur_verdicts_conformite` utiliseront
      ensuite ; posés en contexte de session par cet appel.

    `actes_path` : chemin explicite vers `actes.md`. Vide -> si une save est
    chargée (`load_save`), `<save>/actes.md` ; sinon erreur motivée
    (`actes.md` n'est pas encore câblé dans le moteur, acte.py:3-10)."""
    if regime not in mcp_server._AUTEUR_REGIMES:
        return {"error": f"régime inconnu : {regime!r} "
                         f"(attendu {mcp_server._AUTEUR_REGIMES})"}
    path = mcp_server._auteur_resolve_actes_path(actes_path)
    if path is None:
        return {"error": "actes_path vide et aucune save chargée — appeler "
                         "load_save d'abord ou passer actes_path explicitement"}
    if not path.exists():
        return {"error": f"actes.md introuvable : {path}"}
    actes = mcp_server.acte_mod.load_file(path)
    acte = actes.by_id(acte_id)
    if acte is None:
        return {"error": f"acte introuvable : {acte_id!r} ({path})",
                "actes_disponibles": [a.id for a in actes.actes]}

    cadre = mcp_server.acte_mod.bloc_cadre(acte, mcp_server._store)
    bloc_regime = mcp_server._auteur_bloc_regime(acte, regime)
    vocabulaire = mcp_server.formes_mod.charger_vocabulaire()
    bloc_formes = mcp_server.formes_mod.bloc_prompt(vocabulaire)
    objectifs = mcp_server._auteur_objectifs_regime(acte, regime)

    mcp_server._auteur_ctx = {"acte_id": acte.id, "regime": regime, "objectifs": objectifs}
    return {"bloc_cadre": cadre, "bloc_regime": bloc_regime,
            "bloc_formes": bloc_formes,
            "contraintes_transverses": mcp_server._AUTEUR_CONTRAINTES_TRANSVERSES,
            "objectifs": objectifs}


@mcp_server.mcp.tool()
def auteur_valider_ecriture(module_md: str, declaration_formes_json: str,
                            note_intention_md: str,
                            declaration_rendu_json: str = "") -> dict:
    """Enchaîne les gardes CODE sur ce que la session vient d'écrire, APRÈS
    un appel `auteur_bloc_cadre` (qui pose les objectifs du régime en
    contexte de session).

    Gardes : `module_md`/`note_intention_md` non vides · `declaration_formes_json`
    ancrée au vocabulaire de formes (`formes.valider_declaration` — id hors
    vocabulaire ou justification vide REFUSÉS). Refus motivés, jamais
    silencieux : {"ok": false, "rejets": [...]}.

    `declaration_rendu_json` (Issue #183, PRODUCTION) : OPTIONNEL — une
    couleur de rendu par scène (`[{"scene", "rendu_md"}, ...]`), présent/
    impératif, jamais un enchaînement d'événements. Vide -> `[]`, aucun
    rejet. Présent -> chaque entrée exige `scene`/`rendu_md` non vides
    (forme seulement ; la garde anti-rail D-065 elle-même reste au socle,
    `Node._check_rendu_md`, constatée à la conversion — pas dupliquée ici,
    même choix que le converter #182).

    Sur garde passée : {"ok": true, "formes_validees": [...],
    "declaration_rendu_validee": [...],
    "conformite_prompt": {"system", "payload", "objectifs"}} — le PROMPT de
    conformité du retour 2 (D-262/D-128), prêt à l'emploi. Le jugement de
    conformité (le texte remplit-il chaque objectif ?) reste un jugement LLM
    et se fait PAR LA SESSION : elle répond à ce prompt elle-même puis passe
    sa réponse à `auteur_verdicts_conformite` — aucun appel API ici."""
    if not mcp_server._auteur_ctx.get("objectifs"):
        return {"ok": False, "rejets": [{"champ": "regime",
                "raison": "aucun cadre en contexte — appeler auteur_bloc_cadre "
                         "(acte_id + régime) d'abord"}]}

    module_md = (module_md or "").strip()
    note_intention_md = (note_intention_md or "").strip()
    rejets: list[dict] = []
    if not module_md:
        rejets.append({"champ": "module_md", "raison": "module_md absent ou vide"})
    if not note_intention_md:
        rejets.append({"champ": "note_intention_md",
                       "raison": "note_intention_md absente ou vide"})

    try:
        declaration = (mcp_server.json.loads(declaration_formes_json)
                       if isinstance(declaration_formes_json, str)
                       else declaration_formes_json)
    except mcp_server.json.JSONDecodeError as e:
        rejets.append({"champ": "declaration_formes_json",
                       "raison": f"JSON invalide : {e}"})
        return {"ok": False, "rejets": rejets}
    if not isinstance(declaration, list):
        declaration = []

    try:
        declaration_rendu = (mcp_server.json.loads(declaration_rendu_json)
                             if declaration_rendu_json else [])
    except mcp_server.json.JSONDecodeError as e:
        rejets.append({"champ": "declaration_rendu_json",
                       "raison": f"JSON invalide : {e}"})
        return {"ok": False, "rejets": rejets}

    vocabulaire = mcp_server.formes_mod.charger_vocabulaire()
    validees, rejets_formes = mcp_server.formes_mod.valider_declaration(declaration, vocabulaire)
    for r in rejets_formes:
        rejets.append({"champ": "declaration_formes", **r})

    rendu_valide, rejets_rendu = mcp_server._auteur_valider_declaration_rendu(declaration_rendu)
    rejets.extend(rejets_rendu)

    if rejets:
        return {"ok": False, "rejets": rejets}

    objectifs = mcp_server._auteur_ctx["objectifs"]
    payload = mcp_server._auteur_payload_retour2(objectifs, module_md, validees)

    mcp_server._auteur_ctx = {**mcp_server._auteur_ctx, "module_md": module_md,
                   "declaration_formes": validees,
                   "declaration_rendu": rendu_valide,
                   "texte_normalise": mcp_server._auteur_normaliser_espaces(module_md)}
    return {"ok": True, "formes_validees": validees,
            "declaration_rendu_validee": rendu_valide,
            "conformite_prompt": {"system": mcp_server._AUTEUR_RETOUR2_SYS,
                                  "payload": payload, "objectifs": objectifs}}


@mcp_server.mcp.tool()
def auteur_verdicts_conformite(verdicts_json: str) -> dict:
    """La garde de forme du retour 2 (D-262/D-128) sur les verdicts rendus
    PAR LA SESSION en réponse au `conformite_prompt` d'`auteur_valider_ecriture`.

    Forme attendue : `{"verdicts": [{"objectif_id", "verdict", "justification",
    "extraits"}], "verdicts_formes": [{"forme_id", "correspond",
    "justification", "extraits"}]}` — même contrat que le prompt le demande.

    Rejeté, jamais accepté sur parole : objectif_id/forme_id hors de ceux
    transmis · verdict hors du vocabulaire fermé (conforme|non-conforme|
    absent, ou conforme|non-conforme pour une forme) · justification vide ·
    extrait introuvable dans le texte (sous-chaîne, tolérance espaces).

    Rend un `RapportConformite` en dict : verdicts validés, verdicts_formes
    validés, rejets motivés, `conforme_total`, `ecarts`. ⛔ AUCUN score
    agrégé, aucune note chiffrée (D-131/D-118) : `ecarts` est une LISTE
    d'écarts nommés — l'Auteur (ou Souhel) tranche sur cette liste, jamais
    sur un chiffre."""
    if "texte_normalise" not in mcp_server._auteur_ctx:
        return {"error": "aucune écriture validée en contexte — appeler "
                         "auteur_valider_ecriture d'abord"}
    try:
        obj = (mcp_server.json.loads(verdicts_json) if isinstance(verdicts_json, str)
              else verdicts_json)
    except mcp_server.json.JSONDecodeError as e:
        return {"error": f"JSON invalide : {e}"}
    if not isinstance(obj, dict):
        return {"error": "verdicts_json doit être un objet "
                         "{verdicts: [...], verdicts_formes: [...]}"}

    objectifs = mcp_server._auteur_ctx["objectifs"]
    formes_declarees = mcp_server._auteur_ctx.get("declaration_formes") or []
    ids_objectifs = {o["id"] for o in objectifs}
    ids_formes = {d["id"] for d in formes_declarees}
    texte_normalise = mcp_server._auteur_ctx["texte_normalise"]

    bruts = obj.get("verdicts")
    if not isinstance(bruts, list):
        return {"error": "sortie sans champ 'verdicts' (liste)"}

    verdicts: list[dict] = []
    rejets: list[dict] = []
    for raw in bruts:
        v, raison = mcp_server._auteur_valider_verdict(raw, ids_objectifs, texte_normalise)
        if v is not None:
            verdicts.append(v)
        else:
            rejets.append({"verdict": raw, "raison": raison})

    verdicts_formes: list[dict] = []
    if formes_declarees:
        bruts_formes = obj.get("verdicts_formes")
        if not isinstance(bruts_formes, list):
            rejets.append({"verdict": None, "raison": "sortie sans champ "
                          "'verdicts_formes' (liste) alors que des formes "
                          "étaient déclarées"})
        else:
            for raw in bruts_formes:
                v, raison = mcp_server._auteur_valider_verdict_forme(raw, ids_formes,
                                                          texte_normalise)
                if v is not None:
                    verdicts_formes.append(v)
                else:
                    rejets.append({"verdict": raw, "raison": raison})

    conforme_total, ecarts = mcp_server._auteur_synthese(objectifs, verdicts,
                                              formes_declarees, verdicts_formes)
    return {"verdicts": verdicts, "verdicts_formes": verdicts_formes,
            "rejets": rejets, "conforme_total": conforme_total,
            "ecarts": ecarts}


__all__ = ['auteur_bloc_cadre', 'auteur_valider_ecriture', 'auteur_verdicts_conformite']
