"""Formal validator (SPEC-P4 §7, level 1) — pure structure, zero reading.

Checks: dangling links zero · orphan records zero · well-formed tables
(re-checked at load) · secrets not exposed in common prose · manifest sane.
Returns a list of findings; empty list = green.
"""
from __future__ import annotations


def validate_form(partition, partition_dir=None) -> list[str]:
    errors: list[str] = []
    ids = partition.ids()

    # 1) every referenced id exists (links, secret revelation/porteurs, patches)
    for n in partition.nodes:
        for l in n.liens:
            if l.get("cible_id") not in ids:
                errors.append(f"dangling link: node {n.id} -> {l.get('cible_id')}")
    for s in partition.secrets:
        if s.revelation["node_cible"] not in ids:
            errors.append(f"dangling revelation: secret {s.id} -> "
                          f"{s.revelation['node_cible']}")
        for p in s.porteurs:
            if p and p not in ids:
                errors.append(f"secret {s.id}: unknown porteur {p}")
    for p in partition.patches:
        if p.cible_id not in ids:
            errors.append(f"dangling patch target: {p.cible_id}")

    # 2) records orphans zero — a creature/pnj record must be anchored by some
    #    node's prose or a table result referencing it; v0 proxy: every record
    #    id must appear in at least one node body or table result.
    corpus = "\n".join(n.corps_md for n in partition.nodes)
    corpus += "\n".join(e["resultat_md"] for t in partition.tables
                        for e in t.entrees)
    for r in partition.records:
        if r.id not in corpus and r.nom not in corpus:
            errors.append(f"orphan record: {r.id} ({r.classe}) never referenced")

    # 3) secrets hors prose commune — a secret id/content marker must not leak
    #    into any non-secret node body
    for s in partition.secrets:
        if s.contenu_md.strip() and s.contenu_md.strip()[:40] in corpus:
            errors.append(f"secret leak: secret {s.id} content appears in common prose")

    # 4) duplicate ids across primitives
    all_ids = [n.id for n in partition.nodes] + [r.id for r in partition.records] \
        + [t.id for t in partition.tables] + [s.id for s in partition.secrets]
    dupes = sorted({i for i in all_ids if all_ids.count(i) > 1})
    if dupes:
        errors.append(f"duplicate ids: {dupes}")

    # 5) altitude mandatory on nodes (schemas already enforces; belt & braces)
    for n in partition.nodes:
        if not n.altitude:
            errors.append(f"node {n.id}: missing altitude")

    # 6) D-177: the directing brief is a standard Partition piece
    if partition_dir is not None:
        from pathlib import Path
        if not (Path(partition_dir) / "directeur.md").exists():
            errors.append("directeur.md absent — pièce standard (MRPG-D-177)")

    # 7) D-178 étage aventure — extensions de la fiche méta 2026-08-23
    if partition.aventure is None:
        if partition.nodes:
            errors.append("étage aventure absent (trajectoire/conditions/"
                          "charnière) — non négociable pour P2 "
                          "(rapport conformité §2.1)")
    else:
        ev_ids = {e.id for e in partition.aventure.events()}
        # 7.1 tout evenement est ancré
        for e in partition.aventure.events():
            if not e.anchors:
                errors.append(f"evenement {e.id}: sans ancre source (§6.1)")
            for p in e.perturbations:
                pid = p.get("porteur_cible_id")
                if pid and pid not in ids and pid not in ev_ids:
                    errors.append(f"evenement {e.id}: porteur_cible_id "
                                  f"inconnu {pid}")
                if not p.get("issue"):
                    errors.append(
                        f"evenement {e.id}: perturbation sans issue valide "
                        "(garde anti-rail D-120 §5.1)")
        # 7.4 fonctions_aval référencés existent
        for r in partition.records:
            for fid in getattr(r, "fonctions_aval", []):
                if fid not in ev_ids:
                    errors.append(f"record {r.id}: fonctions_aval inconnu "
                                  f"{fid}")
        # 7.3 LE DERNIER node (ordre de partition) sans charniere_sortie
        #     ni lien sortant ⇒ rouge (fiche §6.3 / D-123 §6)
        if partition.nodes:
            last = partition.nodes[-1]
            if not last.liens \
                    and not getattr(last, "charniere_sortie", None):
                errors.append(
                    f"node {last.id}: dernier node sans lien sortant ni "
                    "charniere_sortie (D-123 §6)")
        # charnière d'aventure obligatoire — au niveau de l'étage OU portée
        # par un node terminal (fiche D-178 §4, D-123 §6)
        has_charniere_node = any(getattr(n, "charniere_sortie", None)
                                 for n in partition.nodes)
        if not partition.aventure.charniere_md.strip() \
                and not has_charniere_node:
            errors.append("aventure: charnière de sortie vide (D-123 §6)")
    return errors


def adventure_exceptions(partition) -> list[str]:
    """Lignes d'exceptions propres à l'étage aventure (fiche §6 : les
    absences fournies ni par la source ni par l'auteur sont SIGNALÉES,
    jamais improvisées). Retourne une liste de chaînes."""
    out: list[str] = []
    if partition.aventure is None:
        return out
    av = partition.aventure
    out.extend(av.warnings)
    for e in av.events():
        if not e.perturbations and e.rubrique == "trajectoire":
            line = (f"evenement {e.id}: perturbations [] — aucune condition "
                    "de perturbation fournie par la source")
            if line not in out:
                out.append(line)
        if not str(e.declencheur.get("valeur", "")).strip():
            line = f"evenement {e.id}: declencheur sans valeur fournie"
            if line not in out:
                out.append(line)
    for r in partition.records:
        if r.classe in ("pnj", "faction") and (
                not r.transverse.get("agenda")
                or not r.transverse.get("portee")):
            line = (f"record {r.id} ({r.classe}): agenda/portee absents — "
                    "non fournis par la source")
            if line not in out:
                out.append(line)
    return out
