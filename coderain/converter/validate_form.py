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
    return errors
