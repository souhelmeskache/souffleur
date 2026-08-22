"""The six Partition primitives (SPEC-P4 §5) plus the source unit.

Plain dicts at the edges (JSON in, markdown out), typed builders here so a
stage that forgets a mandatory field fails at construction, not at validation.
Ids are stable and meaningful; every id referenced anywhere must exist —
checked by validate_form.
"""
from __future__ import annotations

import re

from . import annexe_a

STRUCTURES = ("S1", "S2", "S3")
NODE_TYPES = ("chapitre", "section", "scene", "read_aloud")
# D-122 nomenclature + retour méta 2026-08-22 : arc/univers BANNIS comme
# étages ; seuls trois portent du contenu de module.
ALTITUDES = ("scene", "scenario", "adventure")
ETAGE_GLOBAL = "adventure"      # déclaré dans le manifest
RECORD_CLASSES = ("creature", "pnj", "objet", "lieu", "faction")
SECRET_STATUTS = ("public", "suspect", "secret")
PATCH_OPS = ("append", "prepend", "replace", "delete")

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def check_id(id_: str, what: str) -> str:
    if not isinstance(id_, str) or not _SLUG_RE.match(id_):
        raise ValueError(f"{what}: id must be a lowercase kebab slug, got {id_!r}")
    return id_


class Unit:
    """One segmented chunk of source text with its byte offsets (anti-
    hallucination anchor: the fidelity validator accounts for every offset)."""

    def __init__(self, uid: str, structure: str, start: int, end: int,
                 titre: str = "", renvois: list[dict] | None = None,
                 mj_only: bool = False):
        if structure not in STRUCTURES:
            raise ValueError(f"unit {uid}: structure {structure!r} not in {STRUCTURES}")
        if not (0 <= start <= end):
            raise ValueError(f"unit {uid}: bad offsets [{start}, {end})")
        self.uid = check_id(uid, "unit")
        self.structure = structure
        self.start, self.end = start, end
        self.titre = titre
        # conditional refs: [{"condition": "...", "cible": "<n° or unit id>"}]
        self.renvois = renvois or []
        self.mj_only = mj_only


class Manifest:
    REQUIRED = ("titre", "corpus_source", "corpus_cible", "structures",
                "hash_source", "date_conversion", "version_convertisseur")

    def __init__(self, **fields):
        missing = [k for k in self.REQUIRED if fields.get(k) in (None, "", [])]
        if missing:
            raise ValueError(f"manifest missing: {missing}")
        if fields["corpus_cible"] != "5e":
            raise ValueError("corpus_cible must be '5e' (lingua franca, D-174)")
        for s in fields["structures"]:
            if s not in STRUCTURES:
                raise ValueError(f"structure {s!r} not in {STRUCTURES}")
        self.fields = dict(fields)

    def to_dict(self) -> dict:
        return dict(self.fields)


class Node:
    """Readable prose: chapters/sections/scenes/read-aloud + cross links."""

    def __init__(self, nid: str, type_: str, titre: str, corps_md: str,
                 altitude: str, liens: list[dict] | None = None,
                 anchors: list[tuple[int, int]] | None = None):
        check_id(nid, "node")
        if type_ not in NODE_TYPES:
            raise ValueError(f"node {nid}: type {type_!r} not in {NODE_TYPES}")
        if altitude not in ALTITUDES:
            raise ValueError(f"node {nid}: altitude {altitude!r} not in {ALTITUDES}")
        if not anchors:
            raise ValueError(f"node {nid}: no source anchor — every node cites "
                             "what it translates (SPEC-P4 §3)")
        self.id, self.type, self.titre = nid, type_, titre
        self.corps_md, self.altitude = corps_md, altitude
        self.liens = liens or []
        self.anchors = [(int(a), int(b)) for a, b in anchors]


class Record:
    """Typed stat block, already converted to 5e.

    transverse (D-113/D-119, optional): {fonction, charge, agenda, portee} —
    what the entity DOES stripped from its décor, and its reach."""

    def __init__(self, rid: str, classe: str, nom: str, stats_5e: dict,
                 anchors: list[tuple[int, int]], tags: list[str] | None = None,
                 transverse: dict | None = None):
        check_id(rid, "record")
        if classe not in RECORD_CLASSES:
            raise ValueError(f"record {rid}: classe {classe!r} not in {RECORD_CLASSES}")
        if not anchors:
            raise ValueError(f"record {rid}: no source anchor")
        required = annexe_a.required_fields(classe)
        merged = {**stats_5e, "nom": nom}   # nom is first-class, not a stat
        missing = [f for f in required if f not in merged]
        if missing:
            raise ValueError(f"record {rid} ({classe}): stats_5e missing {missing}")
        self.id, self.classe, self.nom = rid, classe, nom
        self.stats_5e, self.tags = stats_5e, tags or []
        self.transverse = {k: str(v) for k, v in (transverse or {}).items()
                           if v}
        self.anchors = [(int(a), int(b)) for a, b in anchors]


class RollTable:
    def __init__(self, tid: str, de: str, entrees: list[dict],
                 anchors: list[tuple[int, int]]):
        check_id(tid, "table")
        if not re.match(r"^\d+d\d+$", de):
            raise ValueError(f"table {tid}: 'de' must look like '1d20', got {de!r}")
        if not anchors:
            raise ValueError(f"table {tid}: no source anchor")
        prev_end = None
        for e in entrees:
            for k in ("plage_debut", "plage_fin", "resultat_md"):
                if k not in e:
                    raise ValueError(f"table {tid}: entry missing {k}: {e}")
            if e["plage_debut"] > e["plage_fin"]:
                raise ValueError(f"table {tid}: inverted range {e}")
            if prev_end is not None and e["plage_debut"] != prev_end + 1:
                raise ValueError(f"table {tid}: gap/overlap before range "
                                 f"{e['plage_debut']}-{e['plage_fin']}")
            prev_end = e["plage_fin"]
        self.id, self.de, self.entrees = tid, de, entrees
        self.anchors = [(int(a), int(b)) for a, b in anchors]


class Secret:
    """Epistemic secret (D-019): who carries it, what reveals it, what breaks."""

    def __init__(self, sid: str, contenu_md: str, statut: str,
                 porteurs: list[str], revelation: dict,
                 consequence_si_brule: str,
                 anchors: list[tuple[int, int]]):
        check_id(sid, "secret")
        if statut not in SECRET_STATUTS:
            raise ValueError(f"secret {sid}: statut {statut!r} not in {SECRET_STATUTS}")
        if not anchors:
            raise ValueError(f"secret {sid}: no source anchor")
        for k in ("declencheur", "node_cible"):
            if k not in revelation:
                raise ValueError(f"secret {sid}: revelation missing {k}")
        self.id, self.contenu_md, self.statut = sid, contenu_md, statut
        self.porteurs, self.revelation = porteurs, revelation
        self.consequence_si_brule = consequence_si_brule
        self.anchors = [(int(a), int(b)) for a, b in anchors]


class Patch:
    """Addressed incremental mutation (D-132) — never a full rewrite."""

    def __init__(self, cible_id: str, operation: str, payload: str, cause: str):
        if operation not in PATCH_OPS:
            raise ValueError(f"patch -> {cible_id}: op {operation!r} not in {PATCH_OPS}")
        self.cible_id, self.operation, self.payload, self.cause = (
            cible_id, operation, payload, cause)


class Aventure:
    """Étage AVENTURE de la partition (escalier `D-122`, chantier `D-178`).

    trajectoire : [{evenement_md, perturbations:[md]}] — ce qui s'enchaîne si
                  personne n'intervient, avec ce qui le perturbe (`D-120`)
    conditions  : [{description_md, declencheur}] — échéances/lois sans limite
                  spatiale ; declencheur = date OU état d'entité (`D-119`)
    charniere   : la sortie du module convertie en charnière, jamais une fin
                  (`D-123` §6)
    """

    def __init__(self, trajectoire: list[dict], conditions: list[dict],
                 charniere_md: str):
        cleaned_traj = []
        for t in trajectoire or []:
            if not t.get("evenement_md"):
                raise ValueError("trajectoire: entrée sans evenement_md")
            cleaned_traj.append({
                "evenement_md": str(t["evenement_md"]),
                "perturbations": [str(x) for x in t.get("perturbations", [])],
            })
        cleaned_cond = []
        for c in conditions or []:
            if not c.get("description_md") or not c.get("declencheur"):
                raise ValueError("condition de monde: description_md et "
                                 "declencheur requis (D-119)")
            cleaned_cond.append({
                "description_md": str(c["description_md"]),
                "declencheur": str(c["declencheur"]),
            })
        if not charniere_md or not charniere_md.strip():
            raise ValueError("charnière de sortie obligatoire (D-123 §6)")
        self.trajectoire = cleaned_traj
        self.conditions = cleaned_cond
        self.charniere_md = charniere_md


class Partition:
    """The whole output object; `emit.write_partition` serializes it."""

    def __init__(self, manifest: Manifest):
        self.manifest = manifest
        self.nodes: list[Node] = []
        self.records: list[Record] = []
        self.tables: list[RollTable] = []
        self.secrets: list[Secret] = []
        self.patches: list[Patch] = []
        self.aventure: Aventure | None = None   # D-178 — optional at v0.2

    def ids(self) -> set[str]:
        return ({n.id for n in self.nodes} | {r.id for r in self.records}
                | {t.id for t in self.tables} | {s.id for s in self.secrets})
