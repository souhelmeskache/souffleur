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
PREREQUIS_TYPES = ("entite_vivante", "flag", "quete_etat")   # fiche SCÉNARIO §2
DECLENCHEUR_TYPES = ("delai", "etat", "date")                # D-182
ISSUES_PERTURBATION = ("transplantee", "abandonnee")         # D-120 §5.1


def check_prerequis(raw, owner: str) -> dict:
    """prerequis_etat — mêmes primitives que le moteur (fiche SCÉNARIO §2):
    entite_vivante(id) | flag(nom, valeur?) | quete_etat(id, etat)."""
    if not isinstance(raw, dict) or raw.get("type") not in PREREQUIS_TYPES:
        raise ValueError(f"{owner}: prerequis type {raw.get('type')!r} "
                         f"not in {PREREQUIS_TYPES}")
    t = raw["type"]
    if t == "entite_vivante":
        if not raw.get("id"):
            raise ValueError(f"{owner}: entite_vivante requires id")
        return {"type": t, "id": str(raw["id"])}
    if t == "flag":
        if not raw.get("nom"):
            raise ValueError(f"{owner}: flag requires nom")
        out = {"type": t, "nom": str(raw["nom"])}
        if raw.get("valeur"):
            out["valeur"] = str(raw["valeur"])
        return out
    if not raw.get("id") or not raw.get("etat"):
        raise ValueError(f"{owner}: quete_etat requires id + etat")
    return {"type": t, "id": str(raw["id"]), "etat": str(raw["etat"])}


def make_debouche(raw: dict, owner: str) -> dict:
    """un débouché n'est pas VERS OÙ on va, c'est PAR QUOI ON PEUT Y ALLER
    (D-118 amendée). Exactly one of cible_id | ouvre_vers_md; prerequis_etat
    if the source permits it, else condition_textuelle."""
    did = check_id(str(raw.get("id", "")), f"{owner} debouche")
    cible, ouvre = raw.get("cible_id"), raw.get("ouvre_vers_md")
    if bool(cible) == bool(ouvre):
        raise ValueError(f"debouche {did}: exactly one of cible_id | "
                         "ouvre_vers_md required")
    return {"id": did,
            "cible_id": str(cible) if cible else None,
            "ouvre_vers_md": str(ouvre) if ouvre else None,
            "prerequis_etat": [check_prerequis(p, did)
                               for p in raw.get("prerequis_etat", [])],
            "condition_textuelle": str(raw.get("condition_textuelle", ""))}


def make_heritage(raw: dict, owner: str) -> dict:
    """le gel passe par des primitives d'état ; ce qui se scelle est le bruit
    de branche, pas le fait (fiche SCÉNARIO §3, critère D-183)."""
    fait = str(raw.get("fait_md", "")).strip()
    anc = raw.get("ancre_source")
    if not fait or not anc or len(anc) != 2:
        raise ValueError(f"{owner}: heritage entry needs fait_md + "
                         "ancre_source [start, end]")
    return {"fait_md": fait,
            "ancre_source": [int(anc[0]), int(anc[1])],
            "porte": [str(x) for x in raw.get("porte", [])]}
# D-178 étage aventure (fiche méta 2026-08-23)
RUBRIQUES_AVENTURE = ("trajectoire", "condition")
EVENEMENT_DECLENCHEURS = ("delai", "etat", "date")       # D-119/D-120
PERTURBATION_ISSUES = ("transplantee", "abandonnee")     # D-120 §5.1 — garde
# anti-rail: la perturbation CHANGE le cours, jamais seulement le retarde
ALTITUDE_EVENEMENT = ("adventure", "scenario")

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
    """Readable prose: chapters/sections/scenes/read-aloud + cross links.

    Étage SCÉNARIO (fiche méta 2026-08-23): un node d'altitude 'scenario'
    porte objectif_md (`D-065` : trajectoire visée, jamais une séquence),
    debouches (`D-118` amendée : PAR QUOI on peut y aller) et heritage
    (critère `D-183` : gel ⊥ scellement). Matière source absente ⇒ rubrique
    vide + exception signalée, jamais improvisée (`I-111`)."""

    def __init__(self, nid: str, type_: str, titre: str, corps_md: str,
                 altitude: str, liens: list[dict] | None = None,
                 anchors: list[tuple[int, int]] | None = None,
                 charniere_sortie: dict | None = None,
                 objectif_md: str = "", debouches: list[dict] | None = None,
                 heritage: list[dict] | None = None):
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
        cs = charniere_sortie or None
        if cs is not None:
            for k in ("ouvre_vers_md", "prerequis_etat"):
                if not str(cs.get(k, "")).strip():
                    raise ValueError(
                        f"node {nid}: charniere_sortie missing {k} (D-123 §6)")
            cs = {"ouvre_vers_md": str(cs["ouvre_vers_md"]),
                  "prerequis_etat": str(cs["prerequis_etat"])}
        self.charniere_sortie = cs   # D-123: sortie d'aventure, jamais une fin
        self.objectif_md, self.debouches, self.heritage = "", [], []
        if any([objectif_md, debouches, heritage]):
            if altitude != "scenario":
                raise ValueError(
                    f"node {nid}: rubriques scénario exigent altitude "
                    "'scenario' (fiche SCÉNARIO §1)")
            self._set_scenario(objectif_md, debouches, heritage)
        self.anchors = [(int(a), int(b)) for a, b in anchors]

    def _set_scenario(self, objectif_md, debouches, heritage) -> None:
        seen: set[str] = set()
        for d in debouches or []:
            d = make_debouche(d, f"node {self.id}")
            if d["id"] in seen:
                raise ValueError(f"node {self.id}: debouche dupliqué {d['id']}")
            seen.add(d["id"])
            self.debouches.append(d)
        for h in heritage or []:
            self.heritage.append(make_heritage(h, f"node {self.id}"))
        self.objectif_md = str(objectif_md or "")

    def attach_scenario(self, objectif_md: str = "",
                        debouches: list[dict] | None = None,
                        heritage: list[dict] | None = None) -> None:
        """Application à froid par l'adaptateur depuis le fichier auteur
        (contrat aval de la fiche SCÉNARIO §4) : monte l'altitude et pose
        les trois rubriques — la validation reste à la construction."""
        self.altitude = "scenario"
        self._set_scenario(objectif_md, debouches, heritage)


class Record:
    """Typed stat block, already converted to 5e.

    transverse (D-113/D-119, optional): {fonction, charge, agenda, portee} —
    what the entity DOES stripped from its décor, and its reach."""

    def __init__(self, rid: str, classe: str, nom: str, stats_5e: dict,
                 anchors: list[tuple[int, int]], tags: list[str] | None = None,
                 transverse: dict | None = None,
                 fonctions_aval: list[str] | None = None):
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
        # transverses D-113/D-119/D-120 §6 — explicites, jamais improvisés:
        # fonction = à quoi l'élément peut servir ; charge = ce qu'il doit
        # faire ressentir ; agenda/portee = acteurs (pnj|faction) ;
        # fonctions_aval = evenements qui dépendent de lui (perte détectable).
        tr_in = dict(transverse or {})
        self.transverse = {k: str(tr_in[k]) for k in
                           ("fonction", "charge", "agenda", "portee")
                           if tr_in.get(k)}
        self.fonctions_aval = [str(x) for x in (fonctions_aval or [])]
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


class Evenement:
    """7ᵉ primitive — schéma FIGÉ par `D-182` (actée 2026-08-23 ; chantier
    `D-178`). Règle mère D-120 amendée : CONVERTIR, jamais créer — tout champ
    sans matière source reste vide et sort en exception signalée.

    declencheur : {type: delai|etat|date, valeur} (D-119)
    perturbations : [{condition_etat, porteur_cible_id?, issue}] — issue
                    transplantee|abandonnee (garde anti-rail D-120 §5.1)
    rubrique : trajectoire (2a) | condition (2b, portée mondiale implicite)
    """

    def __init__(self, eid: str, description_md: str,
                 declencheur: dict | None = None,
                 altitude: str = "adventure",
                 consequences: list[str] | None = None,
                 perturbations: list[dict] | None = None,
                 once: bool = True,
                 anchors: list[tuple[int, int]] | list[int] | None = None,
                 rubrique: str = "trajectoire",
                 extra: dict | None = None):
        check_id(eid, "evenement")
        if altitude not in ALTITUDE_EVENEMENT:
            raise ValueError(f"evenement {eid}: altitude {altitude!r} not in "
                             f"{ALTITUDE_EVENEMENT}")
        if rubrique not in RUBRIQUES_AVENTURE:
            raise ValueError(f"evenement {eid}: rubrique {rubrique!r} not in "
                             f"{RUBRIQUES_AVENTURE}")
        dec = dict(declencheur or {})
        if dec.get("type") not in EVENEMENT_DECLENCHEURS:
            raise ValueError(f"evenement {eid}: declencheur.type "
                             f"{dec.get('type')!r} not in {EVENEMENT_DECLENCHEURS}")
        if not description_md or not str(description_md).strip():
            raise ValueError(f"evenement {eid}: description_md vide")
        cleaned_pert = []
        for p in perturbations or []:
            if not str(p.get("condition_etat", "")).strip():
                raise ValueError(f"evenement {eid}: perturbation sans "
                                 "condition_etat")
            issue = p.get("issue")
            if issue is not None and issue not in PERTURBATION_ISSUES:
                raise ValueError(f"evenement {eid}: perturbation.issue "
                                 f"{issue!r} not in {PERTURBATION_ISSUES} "
                                 "(garde anti-rail D-120 §5.1)")
            entry = {"condition_etat": str(p["condition_etat"])}
            if issue is not None:
                entry["issue"] = issue   # absence ⇒ rouge au valideur (§6)
            if p.get("porteur_cible_id"):
                entry["porteur_cible_id"] = str(p["porteur_cible_id"])
            cleaned_pert.append(entry)
        # anchors tolérés absents À LA CONSTRUCTION (matière auteur non
        # localisable) mais signalés ROUGES par le valideur (fiche §6.1)
        self.id = eid
        self.rubrique = rubrique
        self.altitude = altitude
        self.declencheur = {"type": dec["type"],
                            "valeur": str(dec.get("valeur", ""))}
        self.once = bool(once)
        self.description_md = str(description_md)
        self.consequences = [str(c) for c in (consequences or [])]
        self.perturbations = cleaned_pert
        norm = []
        for a in anchors or []:
            norm.append((int(a), int(a)) if isinstance(a, int) else
                        (int(a[0]), int(a[1])))
        self.anchors = norm
        self.extra = {k: v for k, v in (extra or {}).items()
                      if k not in ("description_md", "declencheur")}

    def to_dict(self) -> dict:
        out = {"id": self.id, "rubrique": self.rubrique,
               "altitude": self.altitude, "declencheur": self.declencheur,
               "once": self.once, "description_md": self.description_md,
               "ancres_sources": [a for a in self.anchors],
               "consequences": self.consequences,
               "perturbations": self.perturbations}
        out.update(self.extra)
        return out


class Aventure:
    """Étage AVENTURE de la partition (`D-122` escalier, chantier `D-178`).

    trajectoire : [Evenement] — ce qui s'enchaîne si personne n'intervient,
                  chaque événement déclarant CE QUI LE PERTURBE (`D-120`)
    conditions  : [Evenement] — échéances/lois sans limite spatiale (`D-119`)
    charniere_md : la sortie convertie en charnière, jamais une fin
                   (`D-123` §6)

    Les entrées héritées (md libre + perturbations-chaînes) sont converties
    avec PERTE SIGNALÉE : chaque champ manquant produit un avertissement que
    cli.py remonte comme ligne d'exceptions — jamais une improvisation.
    """

    def __init__(self, trajectoire: list[dict], conditions: list[dict],
                 charniere_md: str):
        self.warnings: list[str] = []
        self.trajectoire: list[Evenement] = []
        self.conditions: list[Evenement] = []
        for i, t in enumerate(trajectoire or [], 1):
            ev = self._build(t, "trajectoire", f"traj-{i:02d}")
            if ev:
                self.trajectoire.append(ev)
        for i, c in enumerate(conditions or [], 1):
            ev = self._build(c, "condition", f"cond-monde-{i:02d}")
            if ev:
                self.conditions.append(ev)
        self.charniere_md = str(charniere_md or "")

    def _build(self, raw: dict, rubrique: str, fallback_id: str) -> Evenement:
        desc = raw.get("description_md") or raw.get("evenement_md")
        if not desc or not str(desc).strip():
            raise ValueError(f"{rubrique}: entrée sans description")
        eid = str(raw.get("id") or fallback_id)
        perturbations = []
        for j, p in enumerate(raw.get("perturbations", []), 1):
            if isinstance(p, str):   # forme héritée: chaîne sans structure
                self.warnings.append(
                    f"evenement {eid}: perturbation #{j} héritée (chaîne) "
                    "sans issue transplantee|abandonnee — garde D-120 §5.1 "
                    "non satisfaite par la source")
            else:
                if p.get("issue") not in PERTURBATION_ISSUES:
                    self.warnings.append(
                        f"evenement {eid}: perturbation #{j} sans issue "
                        "(transplantee|abandonnee) — garde D-120 §5.1")
                perturbations.append(p)
        dec = raw.get("declencheur")
        if isinstance(dec, str):
            dec = {"type": "etat", "valeur": dec}
        elif dec is None:
            dec = {"type": "etat", "valeur": ""}
            self.warnings.append(
                f"evenement {eid}: declencheur absent de la source — "
                "type/valeur laissés vides, à compléter ou exceptionner")
        kwargs = {}
        if raw.get("anchors"):
            kwargs["anchors"] = raw["anchors"]
        elif raw.get("ancres_sources"):
            kwargs["anchors"] = raw["ancres_sources"]
        else:
            self.warnings.append(
                f"evenement {eid}: sans ancre source (fiche §6.1 ⇒ rouge)")
        return Evenement(
            eid, str(desc), declencheur=dec,
            altitude=str(raw.get("altitude", "adventure")),
            consequences=raw.get("consequences"),
            perturbations=perturbations,
            once=bool(raw.get("once", True)),
            rubrique=rubrique,
            extra={k: v for k, v in raw.items() if k == "triggers_all"},
            **kwargs)

    def events(self) -> list[Evenement]:
        return self.trajectoire + self.conditions


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
