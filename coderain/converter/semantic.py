"""LLM stage 3 — semantic conversion: unit text -> primitives (the resource
post of SPEC-P4 §1). Strong model, cold, one unit at a time.

Every produced object MUST cite the offsets it translates. Rule mechanics are
NOT converted here — the LLM emits raw stats with a "ruleset" marker and
ruletables.RuleTables does the arithmetic; anything without a table becomes an
exceptions entry, never an improvisation.
"""
from __future__ import annotations

from ..llm import emit_json_ex
from .schemas import (Node, Record, RollTable, Secret, Patch, Partition,
                      Evenement, Aventure)

SYSTEM = """You convert ONE unit of a tabletop RPG module into structured
objects. Fidelity rules:
- You translate CONTENT, you never rewrite or summarize beyond structure.
- EVERY object must carry "anchors": [[start, end), ...] — the exact source
  offsets inside this unit's text that it translates. No anchor = invalid.
- Creatures/NPCs: emit {"records": [...]} with their RAW source stats in
  "stats_source" plus a "ruleset" field ("2e" etc.). DO NOT convert numbers.
  If the source states what an entity is FOR (function, charge/mood,
  agenda, reach/scope), carry it verbatim in the transverse fields
  {fonction, charge, agenda, portee}; anything not stated stays empty —
  NEVER invent it. If a later event depends on that entity, list it in
  "fonctions_aval".
- Readable prose: emit {"nodes": [...]} with type chapitre|section|scene|
  read_aloud and altitude univers|arc|scene.
- A node with altitude "scenario" (macro level) may carry: "objectif_md"
  (the trajectory aimed at — never a sequence), "debouches": [{id,
  cible_id | ouvre_vers_md, prerequis_etat: [{type:
  entite_vivante|flag|quete_etat, ...}], condition_textuelle}] — a debouche
  is BY WHAT one can go on, not where; prerequis_etat only when the source
  states it, else condition_textuelle. And "heritage": [{fait_md,
  ancre_source: [start, end], porte: [ids]}] — facts that keep later
  scenarios portable. CONVERT what the source states; leave a rubric out
  rather than invent it. If a node is the module's END,
  convert it into an exit hinge (D-123): charniere_sortie:
  {ouvre_vers_md, prerequis_etat} — NEVER "the end".
- Rollable tables: emit {"tables": [...]} with de:"1d20" and contiguous ranges.
- Hidden/DM-only information that can be burned: emit {"secrets": [...]} with
  statut public|suspect|secret, porteurs (entity ids), revelation
  {declencheur, node_cible}, consequence_si_brule.
- Predetermined world events ("if the PCs do nothing, X happens by ..."),
  deadlines, laws without spatial limit: emit {"evenements": [...]} with
  rubrique "trajectoire" or "condition", declencheur {type:
  delai|etat|date, valeur}, once:true, description_md, consequences:[md],
  perturbations [{condition_etat, porteur_cible_id?, issue:
  transplantee|abandonnee}] — issue must CHANGE the course (transplanted to
  another bearer, or abandoned), never merely delay it; if the source gives
  no perturbation condition, use [] — never invent one. CONVERT what the
  module states; NEVER create events the module does not contain.
Return ONLY a JSON object with any of those keys (empty object if nothing)."""


def _anchors(raw, uid) -> list[tuple[int, int]]:
    out = [(int(a[0]), int(a[1])) for a in (raw.get("anchors") or [])]
    if not out:
        raise ValueError(f"{uid}: produced object without anchors")
    return out


def _validate(obj: dict, unit, tables: "RuleTablesLike") -> dict:
    out: dict = {"nodes": [], "records": [], "tables": [], "secrets": [],
                 "patches": [], "raw_stats": [], "evenements": [],
                 "exceptions": []}
    for n in obj.get("nodes", []):
        cs = n.get("charniere_sortie")
        out["nodes"].append(Node(
            nid=str(n["id"]), type_=str(n["type"]), titre=str(n.get("titre", "")),
            corps_md=str(n["corps_md"]), altitude=str(n["altitude"]),
            liens=[{"cible_id": str(l["cible_id"]),
                    "condition_textuelle": str(l.get("condition_textuelle", ""))}
                   for l in n.get("liens", [])],
            anchors=_anchors(n, f"node {n.get('id')}"),
            charniere_sortie=cs,
            objectif_md=str(n.get("objectif_md", "")),
            debouches=n.get("debouches") or None,
            heritage=n.get("heritage") or None,
        ))
    for r in obj.get("records", []):
        anchors = _anchors(r, f"record {r.get('id')}")
        stats_source = r.get("stats_source") or {}
        converted = tables.convert_stats(stats_source)
        tr = {k: str(r[k]) for k in ("fonction", "charge", "agenda", "portee")
              if r.get(k)}
        out["records"].append(Record(
            rid=str(r["id"]), classe=str(r["classe"]), nom=str(r["nom"]),
            stats_5e=converted, anchors=anchors, tags=r.get("tags"),
            transverse=tr,
            fonctions_aval=[str(x) for x in (r.get("fonctions_aval") or [])],
        ))
        if r.get("ruleset") and str(r["ruleset"]) != "5e":
            out["raw_stats"].append({"id": str(r["id"]),
                                     "source": dict(stats_source)})
    for t in obj.get("tables", []):
        entrees = [{"plage_debut": int(e["plage_debut"]),
                    "plage_fin": int(e["plage_fin"]),
                    "resultat_md": str(e["resultat_md"]),
                    **({"lien_optionnel": str(e["lien_optionnel"])}
                       if e.get("lien_optionnel") else {})}
                   for e in t["entrees"]]
        out["tables"].append(RollTable(
            tid=str(t["id"]), de=str(t["de"]), entrees=entrees,
            anchors=_anchors(t, f"table {t.get('id')}")))
    for s in obj.get("secrets", []):
        out["secrets"].append(Secret(
            sid=str(s["id"]), contenu_md=str(s["contenu_md"]),
            statut=str(s["statut"]), porteurs=[str(p) for p in s["porteurs"]],
            revelation={"declencheur": str(s["revelation"]["declencheur"]),
                        "node_cible": str(s["revelation"]["node_cible"])},
            consequence_si_brule=str(s.get("consequence_si_brule", "")),
            anchors=_anchors(s, f"secret {s.get('id')}")))
    for p in obj.get("patches", []):
        out["patches"].append(Patch(cible_id=str(p["cible_id"]),
                                    operation=str(p["operation"]),
                                    payload=str(p.get("payload", "")),
                                    cause=str(p.get("cause", ""))))
    for e in obj.get("evenements", []):
        anchors = _anchors(e, f"evenement {e.get('id')}")
        perturbations = e.get("perturbations") or []
        if not perturbations and e.get("rubrique") == "trajectoire":
            out["exceptions"].append(
                f"evenement {e.get('id')}: perturbations [] — aucune "
                "condition de perturbation fournie par la source")
        try:
            out["evenements"].append(Evenement(
                eid=str(e["id"]),
                description_md=str(e["description_md"]),
                declencheur={"type": str((e.get("declencheur") or {})
                                         .get("type", "etat")),
                             "valeur": str((e.get("declencheur") or {})
                                           .get("valeur", ""))},
                altitude=str(e.get("altitude", "adventure")),
                consequences=[str(c) for c in (e.get("consequences") or [])],
                perturbations=perturbations,
                once=bool(e.get("once", True)),
                anchors=anchors,
                rubrique=str(e.get("rubrique", "trajectoire")),
            ))
        except ValueError as ex:
            # garde anti-rail violée par la sortie LLM: signalé, jamais corrigé
            out["exceptions"].append(f"{unit.uid} evenement {e.get('id')}: {ex}")
    return out


def absorb_aventure(partition: Partition, evenements: list) -> None:
    """Assemble/étend l'étage aventure d'une partition à partir des
    Evenements produits par la route LLM (triés par rubrique)."""
    if not evenements:
        return
    if partition.aventure is None:
        partition.aventure = Aventure([], [], "")
    for e in evenements:
        if e.rubrique == "condition":
            partition.aventure.conditions.append(e)
        else:
            partition.aventure.trajectoire.append(e)


def convert_unit(llm, unit_text: str, unit, partition: Partition,
                 tables) -> tuple[dict | None, str | None]:
    payload = (f'Unit id: {unit.uid} (structure {unit.structure}, '
               f'titre: {unit.titre or "n/a"})\nSource text (offsets relative '
               f'to full document):\n{unit_text}')
    obj, err = emit_json_ex(llm, SYSTEM, payload, retry=1, temperature=0.0)
    if obj is None:
        return None, f"semantic conversion failed for {unit.uid}: {err}"
    try:
        return _validate(obj, unit, tables), None
    except (KeyError, ValueError, TypeError) as e:
        return None, f"semantic grammar violated for {unit.uid}: {e}"


BATCH_SYSTEM = SYSTEM.replace("ONE unit", "SEVERAL units").replace(
    "Return ONLY a JSON object with any of those keys (empty object if nothing).",
    'Return ONLY: {"units": [{"uid": "<the unit id>", <the keys above for '
    'that unit>}]} — exactly one entry per given uid.')

# measured on the specimen's first real pass: one call per paragraph made a
# ~60-paragraph module cost hours; batches of 8 keep prompts small enough
# that anchors stay reliable while cutting the call count ~8x.
BATCH_SIZE = 8


def convert_batch(llm, items, tables) -> tuple[dict[str, dict], list[str]]:
    """items: [(unit, unit_text)]. Returns ({uid: result}, errors)."""
    parts = []
    for u, txt in items:
        parts.append(f'--- Unit id: {u.uid} (structure {u.structure}) ---\n{txt}')
    obj, err = emit_json_ex(llm, BATCH_SYSTEM, "\n\n".join(parts),
                            retry=1, temperature=0.0)
    results: dict[str, dict] = {}
    errors: list[str] = []
    if obj is None:
        return results, [f"batch failed: {err}"]
    by_uid = {str(r.get("uid")): r for r in obj.get("units", [])}
    for u, _txt in items:
        raw = by_uid.get(u.uid)
        if raw is None:
            errors.append(f"{u.uid}: missing from batch response")
            continue
        try:
            results[u.uid] = _validate(raw, u, tables)
        except (KeyError, ValueError, TypeError) as e:
            errors.append(f"semantic grammar violated for {u.uid}: {e}")
    extra = set(by_uid) - {u.uid for u, _ in items}
    if extra:
        errors.append(f"batch invented uids: {sorted(extra)}")
    return results, errors


class RuleTablesLike:  # pragma: no cover — typing hint only
    pass
