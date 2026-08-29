"""Garde de résolution INTER-modules (D-253.2, Issue #72).

Étage ajouté AU-DESSUS de la garde intra-module zéro-dangling
(`validate_form.validate_form`, inchangée — voir ce module pour le détail
primitive par primitive). Celle-ci reste bornée à UNE partition : une
référence qui pointe hors de son propre module y est un dangling, point.

`cross_module_report` prend un ENSEMBLE de partitions convertit d'une même
campagne (plusieurs modules) et vérifie que toute référence inter-modules
recensée — porte (`Node.heritage[].porte`), rattachement (`Personnage`,
`Fenetre`), et les autres références du même genre listées dans
`schemas.py` (débouché, lien, secret, patch, ressource, sort, événement) —
résout vers une entité existant QUELQUE PART dans l'ensemble fourni, pas
nécessairement dans la partition d'origine. Convention consignée dans
docs/identite-inter-modules-d253.md.

Deux catégories de constats, jamais confondues :
  - orpheline  : la référence ne résout dans AUCUNE des partitions fournies
                 → échec explicite (liste `orphelines`).
  - suspecte   : deux slugs distincts (pnj/faction/lieu) partagent le même
                 nom d'usage déclaré → SIGNALEMENT, pas un refus (liste
                 `slugs_suspects`) — l'entité récurrente a peut-être reçu
                 deux slugs différents en violation de la convention
                 « un slug pour toute la campagne », à trancher par l'auteur.

Rétrocompatibilité totale : fonction appelable, jamais invoquée
automatiquement par le pipeline existant (aucun crochet obligatoire,
`validate_form`/`emit` continuent de ne connaître qu'une partition à la
fois).
"""
from __future__ import annotations

# Classes de Record considérées comme des entités récurrentes potentielles
# au sens de l'Issue #72 (PNJ, faction, lieu) — creature/objet/sort sont hors
# périmètre du signalement "slug suspect" (identité de campagne, pas de
# matériel ponctuel).
CLASSES_RECURRENTES = ("pnj", "faction", "lieu")


def _module_label(partition, index: int) -> str:
    titre = getattr(partition, "manifest", None)
    if titre is not None:
        titre = titre.fields.get("titre") if hasattr(titre, "fields") else None
    return titre or f"module#{index}"


def _iter_references(partition):
    """Itère les références de `partition` pouvant viser une entité hors de
    son propre module — mêmes champs que ceux résolus intra-module par
    `validate_form.validate_form` (schemas.py, cf. Issue #72 point 1),
    réutilisés ici contre un espace de résolution élargi (l'ensemble de la
    campagne, pas la seule partition d'origine).

    Rend des tuples (kind, source_desc, ref_id).
    """
    for n in partition.nodes:
        for l in n.liens:
            cid = l.get("cible_id")
            if cid:
                yield ("lien", f"node {n.id}", cid)
        for d in getattr(n, "debouches", []):
            if d.get("cible_id"):
                yield ("debouche.cible_id", f"node {n.id} debouche {d['id']}",
                       d["cible_id"])
        for h in getattr(n, "heritage", []):
            for pid in h.get("porte", []):
                yield ("heritage.porte", f"node {n.id}", pid)
    for s in partition.secrets:
        nc = s.revelation.get("node_cible")
        if nc:
            yield ("secret.revelation.node_cible", f"secret {s.id}", nc)
        for p in s.porteurs:
            if p:
                yield ("secret.porteurs", f"secret {s.id}", p)
    for p in partition.patches:
        if p.cible_id:
            yield ("patch.cible_id", f"patch {p.id}", p.cible_id)
    ress_list = (getattr(partition, "ressources", []) or []) \
        + (getattr(partition, "resources", []) or [])
    seen_ress = set()
    for r in ress_list:
        if r.id in seen_ress:
            continue
        seen_ress.add(r.id)
        if getattr(r, "node_id", None):
            yield ("ressource.node_id", f"ressource {r.id}", r.node_id)
        if getattr(r, "porteur_ou_emplacement", None):
            yield ("ressource.porteur_ou_emplacement", f"ressource {r.id}",
                   r.porteur_ou_emplacement)
        if getattr(r, "condition_remise_secret_id", None):
            yield ("ressource.condition_remise_secret_id", f"ressource {r.id}",
                   r.condition_remise_secret_id)
    for pers in getattr(partition, "personnages", []) or []:
        for j in getattr(pers, "destinee", []):
            ratt = j.get("rattachement")
            if ratt:
                yield ("personnage.destinee.rattachement",
                       f"personnage {pers.id} jalon {j.get('id', '?')}", ratt)
    for fen in getattr(partition, "fenetres", []) or []:
        if getattr(fen, "rattachement", None):
            yield ("fenetre.rattachement", f"fenetre {fen.id}", fen.rattachement)
        if getattr(fen, "tension_id", None):
            yield ("fenetre.tension_id", f"fenetre {fen.id}", fen.tension_id)
    for r in partition.records:
        for sid in getattr(r, "sorts_connus", []) or []:
            yield ("record.sorts_connus", f"record {r.id}", sid)
        sec_id = getattr(r, "stats_5e", {}).get("secret_lie_id")
        if sec_id:
            yield ("record.secret_lie_id", f"record {r.id}", sec_id)
        for fid in getattr(r, "fonctions_aval", []) or []:
            yield ("record.fonctions_aval", f"record {r.id}", fid)
    if partition.aventure is not None:
        for e in partition.aventure.events():
            for p in e.perturbations:
                pid = p.get("porteur_cible_id")
                if pid:
                    yield ("evenement.perturbation.porteur_cible_id",
                           f"evenement {e.id}", pid)


def _evenement_ids(partition) -> set[str]:
    if partition.aventure is None:
        return set()
    return {e.id for e in partition.aventure.events()}


def _campagne_ids(partitions) -> set[str]:
    """Espace de résolution inter-modules : union des ids de partition
    (`Partition.ids()`) ET des ids d'événement/débouché (hors `ids()`, cf.
    `validate_form.scenario_report`) de TOUTES les partitions fournies."""
    union: set[str] = set()
    for p in partitions:
        union |= p.ids()
        union |= _evenement_ids(p)
        union |= {d["id"] for n in p.nodes for d in getattr(n, "debouches", [])}
    return union


def _slugs_suspects(partitions) -> list[str]:
    """Deux slugs distincts (classe pnj/faction/lieu, CLASSES_RECURRENTES)
    partageant le même nom d'usage déclaré (`Record.nom`, comparaison
    insensible à la casse/aux espaces superflus) — signalement, pas refus
    (convention D-253.2 : « un slug par entité pour toute la campagne »)."""
    par_nom: dict[str, dict[str, str]] = {}  # nom_normalise -> {id: module}
    for i, p in enumerate(partitions):
        module = _module_label(p, i)
        for r in p.records:
            if r.classe not in CLASSES_RECURRENTES:
                continue
            nom_norm = " ".join(r.nom.split()).casefold()
            if not nom_norm:
                continue
            par_nom.setdefault(nom_norm, {})[r.id] = module
    suspects = []
    for nom_norm, ids_modules in sorted(par_nom.items()):
        if len(ids_modules) < 2:
            continue
        detail = ", ".join(f"{rid} ({mod})" for rid, mod in
                            sorted(ids_modules.items()))
        suspects.append(f"nom d'usage {nom_norm!r} porté par {len(ids_modules)} "
                        f"slugs distincts : {detail} — même entité, deux "
                        "identités ? (D-253.2, signalement)")
    return suspects


def cross_module_report(partitions) -> dict:
    """Garde de résolution inter-modules (D-253.2).

    `partitions` : liste de `schemas.Partition`, une par module converti de
    la même campagne (≥ 1 ; avec une seule partition, équivaut à un
    contrôle no-op côté orphelines puisque `validate_form` a déjà couvert
    ce cas — l'intérêt apparaît à partir de 2 modules).

    Retour : {"orphelines": [...], "slugs_suspects": [...]} — deux listes de
    chaînes, chacune ancrée sur sa source (module/primitive/id). Listes
    vides des deux côtés = vert. Ne modifie rien, ne lève pas : c'est un
    rapport, à l'appelant de décider (CI, script, revue manuelle).
    """
    union = _campagne_ids(partitions)
    orphelines: list[str] = []
    for i, p in enumerate(partitions):
        module = _module_label(p, i)
        for kind, source, ref_id in _iter_references(p):
            if ref_id not in union:
                orphelines.append(f"{module}: {source} -> {kind} référence "
                                  f"orpheline {ref_id!r} (absente de tous les "
                                  "modules fournis — D-253.2)")
    return {"orphelines": orphelines, "slugs_suspects": _slugs_suspects(partitions)}
