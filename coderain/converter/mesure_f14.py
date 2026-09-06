"""F1.4 (Issue #342) — mesure pure : ce que la partition JOUÉE déclare sur
ses nœuds d'altitude 'scenario' (débouchés, prérequis par type, débouchés
vides) + signaux d'axe LIEU/HORLOGE non déclarés (D-282 règle 4) dans le
corps de ces mêmes nœuds.

Aucune évaluation runtime des prérequis (F1.1), aucun nouveau type de
prérequis (F1.2), aucune modification de la partition émise — lecture pure
d'un répertoire de Partition déjà converti (`nodes/*.md` + `index.json`,
via `.aval`), hors ligne. Le rapport ne porte JAMAIS le texte du module
(D-109 : dépôt public) — seulement des comptes et des ids machine.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .aval import get_node, load_partition

# Motifs suggérant un prérequis d'axe LIEU ou HORLOGE (D-282 règle 4) que le
# convertisseur n'a PAS matérialisé en prerequis_etat structuré — liste
# fermée, documentée ICI (le corpus réel est en anglais, la partition émise
# porte des rubriques auteur en français : les deux familles sont couvertes).
# Le rapport ne retient que des comptes + ids de nœuds : jamais l'extrait de
# corps_md qui a matché.
SIGNAUX_AXE: dict[str, list[str]] = {
    "lieu": [
        r"(?:déjà|deja)\s+(?:allé|all[eé]e|visit[ée])",
        r"already\s+(?:been|visited)",
        r"have\s+you\s+(?:already\s+)?been",
    ],
    "horloge": [
        r"à\s+la\s+nuit\s+tomb[ée]e",
        r"at\s+night(?:fall)?",
        r"\bavant\s+que\b",
        r"\bavant\s+de\b",
        r"\baprès\b",
        r"\bbefore\s+you\b",
        r"\bafter\s+you\b",
        r"\bonce\s+you\s+have\b",
    ],
}

# les 3 primitives de la fiche SCÉNARIO §2 (schemas.PREREQUIS_TYPES) —
# dupliqué ici en constante locale pour ne dépendre que de la forme du champ
# (le rapport lit du JSON déjà écrit sur disque, pas des objets Node)
TYPES_PREREQUIS = ("entite_vivante", "flag", "quete_etat")


def _debouche_types_negations(debouche: dict) -> tuple[list[str], int]:
    """types présents (dédupliqués, ordre d'apparition) + nombre de
    négations `non(<atome>)` (D-187) portées par un débouché."""
    types: list[str] = []
    negations = 0
    for p in debouche.get("prerequis_etat") or []:
        if p.get("type") == "non":
            negations += 1
            t = (p.get("atome") or {}).get("type")
        else:
            t = p.get("type")
        if t and t not in types:
            types.append(t)
    return types, negations


def _debouche_report(d: dict) -> dict:
    prereqs = d.get("prerequis_etat") or []
    types, negations = _debouche_types_negations(d)
    if d.get("cible_id"):
        cible = {"kind": "cible_id", "value": d["cible_id"]}
    else:
        cible = {"kind": "ouvre_vers_md"}
    return {"id": d["id"], "cible": cible, "n_prerequis": len(prereqs),
            "types_prerequis": types, "negations": negations}


def _aggreger_debouches(nodes_meta: list[dict]) -> dict:
    """comptes agrégés (fiche §a, ligne 'même comptes' pour les scènes) —
    sur une liste de fronts-matter de nodes déjà lus."""
    total = sans_prereq = negations = cible_id = ouvre_vers_md = 0
    types = {t: 0 for t in TYPES_PREREQUIS}
    for meta in nodes_meta:
        for d in meta.get("debouches") or []:
            total += 1
            prereqs = d.get("prerequis_etat") or []
            if not prereqs:
                sans_prereq += 1
            dtypes, neg = _debouche_types_negations(d)
            negations += neg
            for p in prereqs:
                t = ((p.get("atome") or {}).get("type")
                     if p.get("type") == "non" else p.get("type"))
                if t in types:
                    types[t] += 1
            if d.get("cible_id"):
                cible_id += 1
            else:
                ouvre_vers_md += 1
    return {"debouches_total": total, "debouches_sans_prerequis": sans_prereq,
            "debouches_avec_prerequis": total - sans_prereq,
            "types_prerequis": types, "negations": negations,
            "cible_id": cible_id, "ouvre_vers_md": ouvre_vers_md}


def build_report(partition_dir: str | Path) -> dict:
    """Rapport F1.4 (Issue #342 §a) pour une Partition déjà convertie sur
    disque. Retourne un dict pur JSON — jamais de texte de module."""
    partition_dir = Path(partition_dir)
    index = load_partition(partition_dir)
    manifest = {}
    mpath = partition_dir / "manifest.json"
    if mpath.exists():
        manifest = json.loads(mpath.read_text(encoding="utf-8"))

    scenario_ids = [n["id"] for n in index["nodes"]
                    if n.get("altitude") == "scenario"]
    scene_ids = [n["id"] for n in index["nodes"]
                 if n.get("altitude") == "scene"]

    scenarios: list[dict] = []
    obj_manquants: list[str] = []
    signaux = {axis: {"occurrences": 0, "noeuds": []} for axis in SIGNAUX_AXE}
    scenario_metas: list[dict] = []

    for nid in scenario_ids:
        node = get_node(partition_dir, nid)
        meta, body = node["meta"], node["body"]
        scenario_metas.append(meta)
        objectif_present = bool(str(meta.get("objectif_md", "")).strip())
        if not objectif_present:
            obj_manquants.append(nid)
        debouches_meta = meta.get("debouches") or []
        deb_detail = [_debouche_report(d) for d in debouches_meta]
        sans_prereq = [d["id"] for d in debouches_meta
                       if not d.get("prerequis_etat")]
        for axis, motifs in SIGNAUX_AXE.items():
            n_match = sum(len(re.findall(m, body, re.I)) for m in motifs)
            if n_match:
                signaux[axis]["occurrences"] += n_match
                signaux[axis]["noeuds"].append(nid)
        scenarios.append({
            "id": nid,
            "objectif_md_present": objectif_present,
            "debouches_total": len(debouches_meta),
            "debouches": deb_detail,
            "debouches_sans_prerequis": sans_prereq,
        })

    scene_metas = [get_node(partition_dir, nid)["meta"] for nid in scene_ids]

    return {
        "partition_titre": manifest.get("titre"),
        "hash_source": manifest.get("hash_source"),
        "noeuds_scenario": len(scenario_ids),
        "noeuds_scenario_sans_objectif": obj_manquants,
        "scenarios": scenarios,
        "totaux_scenario": _aggreger_debouches(scenario_metas),
        "noeuds_scene": len(scene_ids),
        "totaux_scene": _aggreger_debouches(scene_metas),
        "signaux_axe": signaux,
    }


def render_md(report: dict, *, partition_slug: str = "",
              date: str = "") -> str:
    """Rendu Markdown chiffres-seuls (fiche §b) — même contrat de forme que
    #316 (b) : un rapport PAR NŒUD de scénario puis un total."""
    lines = ["# Mesure F1.4 — prérequis des débouchés de scénario", ""]
    if partition_slug or date:
        lines.append(f"Partition : `{partition_slug}` — {date}".strip())
        lines.append("")
    lines.append(f"- nœuds scénario : {report['noeuds_scenario']}")
    lines.append(f"- nœuds scénario sans `objectif_md` : "
                 f"{len(report['noeuds_scenario_sans_objectif'])}"
                 + (f" ({', '.join(report['noeuds_scenario_sans_objectif'])})"
                    if report["noeuds_scenario_sans_objectif"] else ""))
    lines.append("")
    lines.append("## Par nœud de scénario")
    lines.append("")
    for s in report["scenarios"]:
        lines.append(f"### {s['id']}")
        lines.append(f"- objectif_md présent : {s['objectif_md_present']}")
        lines.append(f"- débouchés : {s['debouches_total']}")
        for d in s["debouches"]:
            cible = (f"cible_id={d['cible']['value']}"
                     if d["cible"]["kind"] == "cible_id" else "ouvre_vers_md")
            lines.append(f"  - {d['id']} : {cible}, "
                         f"{d['n_prerequis']} prérequis, "
                         f"types={d['types_prerequis']}, "
                         f"négations={d['negations']}")
        if s["debouches_sans_prerequis"]:
            lines.append(f"- débouchés SANS prérequis : "
                         f"{s['debouches_sans_prerequis']}")
        lines.append("")

    tot = report["totaux_scenario"]
    lines.append("## Total scénario")
    lines.append(f"- débouchés : {tot['debouches_total']}")
    lines.append(f"- débouchés sans prérequis : "
                 f"{tot['debouches_sans_prerequis']} "
                 f"({tot['debouches_avec_prerequis']} avec)")
    lines.append(f"- types de prérequis : {tot['types_prerequis']}")
    lines.append(f"- négations : {tot['negations']}")
    lines.append(f"- cible_id : {tot['cible_id']} — "
                 f"ouvre_vers_md : {tot['ouvre_vers_md']}")
    lines.append("")

    scene = report["totaux_scene"]
    lines.append("## Total scène (agrégé, %d nœuds)" % report["noeuds_scene"])
    lines.append(f"- débouchés : {scene['debouches_total']}")
    lines.append(f"- débouchés sans prérequis : "
                 f"{scene['debouches_sans_prerequis']} "
                 f"({scene['debouches_avec_prerequis']} avec)")
    lines.append(f"- types de prérequis : {scene['types_prerequis']}")
    lines.append(f"- négations : {scene['negations']}")
    lines.append(f"- cible_id : {scene['cible_id']} — "
                 f"ouvre_vers_md : {scene['ouvre_vers_md']}")
    lines.append("")

    lines.append("## Signaux d'axe (lieu / horloge non déclarés)")
    for axis, s in report["signaux_axe"].items():
        lines.append(f"- {axis} : {s['occurrences']} occurrence(s) sur "
                     f"{len(s['noeuds'])} nœud(s) {s['noeuds']}")
    lines.append("")
    return "\n".join(lines)
