"""Physical output of the Partition (SPEC-P4 §8): one self-contained directory,
manifest.json + structured markdown, one primitive = one folder. Markdown
stays the source of truth; no database at v0."""
from __future__ import annotations

import json
from pathlib import Path


def _md_table(t) -> str:
    lines = [f"# table {t.id}", "", f"de: `{t.de}`", ""]
    for e in t.entrees:
        lien = f" → [{e['lien_optionnel']}]" if e.get("lien_optionnel") else ""
        lines.append(f"- {e['plage_debut']}-{e['plage_fin']}: {e['resultat_md']}{lien}")
    return "\n".join(lines) + "\n"


def _front_matter(obj: dict) -> str:
    y = json.dumps(obj, ensure_ascii=False, indent=1)
    return f"---\n{y}\n---\n"


def write_partition(partition, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    # garde zéro-dangling E3 : toute pose de jeton vise un node de LA partition
    node_ids = {n.id for n in partition.nodes}
    for r in partition.records:
        for pose in getattr(r, "tokens_initial", []) or []:
            if pose["node_id"] not in node_ids:
                raise ValueError(
                    f"record {r.id}: tokens_initial pose vers le node "
                    f"inconnu {pose['node_id']} — zéro dangling autorisé")
    # garde D-218 contrat traversant : toute tension hors codes ⇒ erreur emit
    from coderain.converter.schemas import TENSION_CODES
    for t in getattr(partition, "tensions", []) or []:
        if getattr(t, "categorie", None) not in TENSION_CODES:
            raise ValueError(
                f"tension {t.id}: categorie {getattr(t, 'categorie', None)!r} "
                f"tension_code_invalide — hors {TENSION_CODES} "
                "(D-218 contrat traversant, emit non silencieux)")
    # garde zéro-dangling tensions : ancrage node_id existe
    for t in getattr(partition, "tensions", []) or []:
        if t.node_id not in node_ids:
            raise ValueError(
                f"tension {t.id}: node_id inconnu {t.node_id} — "
                "zéro dangling autorisé (D-218 §1)")
    # garde zéro-dangling ressources (D-216 §2) — liste unique dédupliquée par id (alias resources/ressources même objet)
    seen_ress: set[str] = set()
    uniq_ress: list = []
    for r in (getattr(partition, "ressources", []) or []) + (getattr(partition, "resources", []) or []):
        if r.id not in seen_ress:
            seen_ress.add(r.id)
            uniq_ress.append(r)
    for r in uniq_ress:
        if getattr(r, "node_id", None) and r.node_id not in node_ids:
            raise ValueError(
                f"ressource {r.id}: node_id inconnu {r.node_id} — "
                "zéro dangling autorisé (D-216 §2)")
    # garde zéro-dangling personnages (I-341/D-219) : tout rattachement de jalon
    # pointe un id existant de la partition (node/tension/ressource/personnage)
    all_ids = node_ids | {r.id for r in partition.records} \
              | {t.id for t in partition.tables} \
              | {s.id for s in partition.secrets} \
              | {t.id for t in getattr(partition, "tensions", [])} \
              | {r.id for r in uniq_ress}
    for pers in getattr(partition, "personnages", []) or []:
        for j in pers.destinee:
            ratt = j.get("rattachement")
            if ratt and ratt not in all_ids:
                raise ValueError(
                    f"personnage {pers.id} jalon {j['id']}: rattachement "
                    f"vers id inconnu {ratt} — zéro dangling autorisé "
                    "(I-341/D-219)")
    for sub in ("nodes", "records", "tables", "secrets", "patches", "tensions", "resources", "personnages"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)

    (out_dir / "manifest.json").write_text(
        json.dumps(partition.manifest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8")

    if partition.aventure is not None:
        av = partition.aventure
        fm = _front_matter({
            "etage": "adventure", "chantier": "D-178",
            # schéma evenement FIGÉ par D-182 (actée 2026-08-23)
            "schema_evenement": "fige-D-182",
            "trajectoire": [e.to_dict() for e in av.trajectoire],
            "conditions": [e.to_dict() for e in av.conditions]})
        body = ("## Charnière de sortie\n\n" + av.charniere_md + "\n")
        (out_dir / "aventure.md").write_text(fm + body, encoding="utf-8")

    for n in partition.nodes:
        fm = _front_matter({"id": n.id, "type": n.type, "titre": n.titre,
                            "altitude": n.altitude, "liens": n.liens,
                            **({"charniere_sortie": n.charniere_sortie}
                               if getattr(n, "charniere_sortie", None) else {}),
                            # étage SCÉNARIO (fiche méta 2026-08-23)
                            **({"objectif_md": n.objectif_md}
                               if getattr(n, "objectif_md", "") else {}),
                            **({"debouches": n.debouches}
                               if getattr(n, "debouches", []) else {}),
                            **({"heritage": n.heritage}
                               if getattr(n, "heritage", []) else {}),
                            "anchors": n.anchors})
        (out_dir / "nodes" / f"{n.id}.md").write_text(fm + n.corps_md + "\n",
                                                      encoding="utf-8")
    for r in partition.records:
        # P-CONV-1 : les clés réservées (ancre_srd, delta_vs_ancre,
        # tokens_initial, persistent) vivent au FRONT MATTER — le body reste
        # la mécanique pure, rechargable telle quelle par le moteur.
        fm = _front_matter({"id": r.id, "classe": r.classe, "nom": r.nom,
                            "tags": r.tags, "anchors": r.anchors,
                            **({"transverse": r.transverse}
                               if r.transverse else {}),
                            **({"fonctions_aval": r.fonctions_aval}
                               if getattr(r, "fonctions_aval", None) else {}),
                            **({"ancre_srd": r.ancre_srd}
                               if getattr(r, "ancre_srd", None) else {}),
                            **({"delta_vs_ancre": r.delta_vs_ancre}
                               if getattr(r, "delta_vs_ancre", None) else {}),
                            **({"tokens_initial": r.tokens_initial}
                               if getattr(r, "tokens_initial", None) else {}),
                            **({"persistent_attrs": r.persistent_attrs}
                               if getattr(r, "persistent_attrs", None) else {})})
        body = json.dumps(r.stats_5e, ensure_ascii=False, indent=1)
        (out_dir / "records" / f"{r.id}.md").write_text(fm + body + "\n",
                                                        encoding="utf-8")
    for t in partition.tables:
        fm = _front_matter({"id": t.id, "de": t.de, "anchors": t.anchors})
        (out_dir / "tables" / f"{t.id}.md").write_text(fm + _md_table(t),
                                                       encoding="utf-8")
    for s in partition.secrets:
        fm = _front_matter({"id": s.id, "statut": s.statut,
                            "porteurs": s.porteurs, "revelation": s.revelation,
                            "consequence_si_brule": s.consequence_si_brule,
                            "anchors": s.anchors})
        (out_dir / "secrets" / f"{s.id}.md").write_text(fm + s.contenu_md + "\n",
                                                        encoding="utf-8")
    for t in getattr(partition, "tensions", []) or []:
        fm = _front_matter({"id": t.id, "categorie": t.categorie,
                            "node_id": t.node_id, "anchors": t.anchors})
        (out_dir / "tensions" / f"{t.id}.md").write_text(
            fm + t.description_md + "\n", encoding="utf-8")
    for r in uniq_ress:
        fm = _front_matter({"id": r.id, "type": r.type_ressource,
                            "node_id": r.node_id, "page": r.page,
                            "fichier": r.fichier, "anchors": r.anchors})
        body = r.description_md or f"Ressource {r.id} ({r.type_ressource})"
        (out_dir / "resources" / f"{r.id}.md").write_text(
            fm + body + "\n", encoding="utf-8")
    for pers in getattr(partition, "personnages", []) or []:
        fm = _front_matter({"id": pers.id, "nom": pers.nom,
                            "acquis_conversation": pers.acquis_conversation,
                            "destinee": pers.to_dict()["destinee"]})
        body = f"# {pers.nom}\n\nPersonnage {pers.id}."
        (out_dir / "personnages" / f"{pers.id}.md").write_text(
            fm + body + "\n", encoding="utf-8")
    if partition.patches:
        rows = [_front_matter({"cible_id": p.cible_id, "operation": p.operation,
                               "cause": p.cause}) + p.payload + "\n"
                for p in partition.patches]
        for i, text in enumerate(rows):
            (out_dir / "patches" / f"{partition.patches[i].cible_id}-{i}.md"
             ).write_text(text, encoding="utf-8")

    # machine-readable mirror of everything except prose bodies
    index = {
        "nodes": [{"id": n.id, "type": n.type, "altitude": n.altitude,
                   **({"charniere_sortie": True}
                      if getattr(n, "charniere_sortie", None) else {}),
                   **({"scenario": True}
                      if n.altitude == "scenario" else {})}
                  for n in partition.nodes],
        "records": [{"id": r.id, "classe": r.classe,
                     "transverse": bool(getattr(r, "transverse", None)),
                     **({"ancre_srd": r.ancre_srd}
                        if getattr(r, "ancre_srd", None) else {}),
                     **({"pose_sur_nodes": [p["node_id"] for p in
                                            r.tokens_initial]}
                        if getattr(r, "tokens_initial", None) else {}),
                     **({"persistent_attrs": r.persistent_attrs}
                        if getattr(r, "persistent_attrs", None) else {})}
                    for r in partition.records],
        "tables": [{"id": t.id, "de": t.de} for t in partition.tables],
        "secrets": [{"id": s.id, "statut": s.statut} for s in partition.secrets],
        "tensions": [{"id": t.id, "categorie": t.categorie, "node_id": t.node_id}
                     for t in getattr(partition, "tensions", []) or []],
        "resources": [{"id": r.id, "type": r.type_ressource,
                       **({"node_id": r.node_id} if getattr(r, "node_id", None) else {}),
                       **({"page": r.page} if getattr(r, "page", None) else {}),
                       **({"fichier": r.fichier} if getattr(r, "fichier", "") else {})}
                      for r in uniq_ress],
        "personnages": [{"id": p.id, "nom": p.nom,
                         "nb_jalons": len(p.destinee),
                         "acquis_conversation": p.acquis_conversation}
                        for p in getattr(partition, "personnages", []) or []],
        "aventure": ({"etage": "adventure",
                      "trajectoire": len(av.trajectoire),
                      "conditions": len(av.conditions)}
                     if partition.aventure else None),
    }
    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    return out_dir


def read_manifest(partition_dir: Path) -> dict:
    return json.loads((Path(partition_dir) / "manifest.json").read_text(encoding="utf-8"))
