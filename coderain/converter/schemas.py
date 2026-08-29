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
# D-218 tension traversante (P-CONV-2) : premier inventaire réel
TENSION_CATEGORIES = ("menace", "horloge", "echeance", "cout", "choix", "revelation")
# D-218 contrat traversant : alias canonique — les 6 codes que l'analyse repère,
# que l'adaptation rend jouable, que l'Auteur respecte. Toute tension hors ces
# 6 codes est ROUGE (validate_form §8, emit garde, test-auteur-codes-tension).
TENSION_CODES = TENSION_CATEGORIES
RESSOURCE_TYPES = ("carte",)  # D-216 §2 générique, premier cas = carte (D-217 poste uniquement)
# D-129/D-135 via D-220 : marqueurs temporels interdits dans les jalons de destinée
# (passé/intention seuls — jamais futur ni événement)
JALON_INTERDITS_FUTUR = ("fera", "ferait", "futur", "quand il", "lorsqu'il",
                          "il arrivera", "il adviendra", "va", "ira", "deviendra")
NEGATION_TYPE = "non"   # D-187: non(<atome>), une seule profondeur
DECLENCHEUR_TYPES = ("delai", "etat", "date")                # D-182
ISSUES_PERTURBATION = ("transplantee", "abandonnee")         # D-120 §5.1
# D-252.2 (issue #62) — objets magiques : champs OPTIONNELS de stats_5e,
# réservés à la classe objet (annexe A §3bis). Malédiction/identification ne
# sont PAS des champs ici : câblage sur Secret via secret_lie_id (résolu par
# validate_form, hors de portée du Record isolé).
TYPE_OBJET = ("arme", "armure", "anneau", "potion", "parchemin", "baguette",
              "baton", "merveille")
RARETE = ("commun", "peu_commun", "rare", "tres_rare", "legendaire", "artefact")
ACTIVATION = ("action", "mot_de_commande", "consommable", "passif")


def check_prerequis(raw, owner: str, _depth: int = 0) -> dict:
    """prerequis_etat — mêmes primitives que le moteur (fiche SCÉNARIO §2):
    entite_vivante(id) | flag(nom, valeur?) | quete_etat(id, etat).
    Négation bornée (D-187): non(<atome>) — une seule profondeur, pas de
    logique composée (la conjonction reste la liste)."""
    if not isinstance(raw, dict) or raw.get("type") not in PREREQUIS_TYPES \
            + (NEGATION_TYPE,):
        raise ValueError(f"{owner}: prerequis type {raw.get('type')!r} "
                         f"not in {PREREQUIS_TYPES + (NEGATION_TYPE,)}")
    t = raw["type"]
    if t == NEGATION_TYPE:
        if _depth > 0:
            raise ValueError(f"{owner}: non(non(...)) interdit — la négation "
                             "porte sur UN atome, une seule profondeur "
                             "(D-187)")
        if not isinstance(raw.get("atome"), dict):
            raise ValueError(f"{owner}: non() exige UN atome "
                             f"{PREREQUIS_TYPES} (D-187)")
        return {"type": t,
                "atome": check_prerequis(raw["atome"], owner,
                                         _depth + 1)}
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
    what the entity DOES stripped from its décor, and its reach.

    Formes P-CONV-1 (E2/E3, fiche 2026-08-26) — clés RÉSERVÉES de stats_5e,
    sorties du corps mécanique vers les attributs typés :
    - ancre_srd   : slug `dnd5e-srd-data` (créature uniquement) — la
      partition référence le dataset, elle n'en copie jamais les stats ;
    - delta_vs_ancre : écart documenté vs l'ancre (variante SRD), jamais
      orpheline ;
    - tokens_initial : poses initiales E3 [{node_id, count, placement_md}] —
      OÙ la rencontre pose ses jetons (le garde zéro-dangling vit dans emit) ;
    - persistent  : attributs qui survivent aux frontières de combat (delta
      persist `1b84258`) — déclarés côté auteur par la ligne 'persistent:'
      côté moteur ; ici la liste des attrs DOIT exister dans les stats.
    """

    _RESERVED = ("ancre_srd", "delta_vs_ancre", "tokens_initial", "persistent")

    def __init__(self, rid: str, classe: str, nom: str, stats_5e: dict,
                 anchors: list[tuple[int, int]], tags: list[str] | None = None,
                 transverse: dict | None = None,
                 fonctions_aval: list[str] | None = None):
        check_id(rid, "record")
        if classe not in RECORD_CLASSES:
            raise ValueError(f"record {rid}: classe {classe!r} not in {RECORD_CLASSES}")
        if not anchors:
            raise ValueError(f"record {rid}: no source anchor")
        stats = {k: v for k, v in stats_5e.items() if k not in self._RESERVED}
        self.ancre_srd = self._ancre(rid, classe, stats_5e)
        self.delta_vs_ancre = self._delta(rid, stats_5e)
        self.tokens_initial = self._tokens(rid, stats_5e)
        self.persistent_attrs = self._persistent(rid, stats_5e, stats)
        self._objet_magique(rid, classe, stats)
        required = annexe_a.required_fields(classe)
        merged = {**stats, "nom": nom}   # nom is first-class, not a stat
        missing = [f for f in required if f not in merged]
        if missing:
            raise ValueError(f"record {rid} ({classe}): stats_5e missing {missing}")
        self.id, self.classe, self.nom = rid, classe, nom
        self.stats_5e, self.tags = stats, tags or []
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

    def _ancre(self, rid, classe, raw) -> str | None:
        ancre = raw.get("ancre_srd")
        if ancre is None:
            return None
        if classe != "creature":
            raise ValueError(f"record {rid} ({classe}): ancre_srd réservé à "
                             "la classe creature")
        a = str(ancre)
        if not _SLUG_RE.match(a):
            raise ValueError(f"record {rid}: ancre_srd doit être un slug "
                             f"kebab minuscule du dataset, got {ancre!r}")
        return a

    def _delta(self, rid, raw) -> dict | None:
        delta = raw.get("delta_vs_ancre")
        if delta is None:
            return None
        if not raw.get("ancre_srd"):
            raise ValueError(f"record {rid}: delta_vs_ancre sans ancre_srd — "
                             "un delta est toujours relatif à son ancre")
        if not isinstance(delta, dict) or not delta:
            raise ValueError(f"record {rid}: delta_vs_ancre doit être un "
                             "dict non vide (écart documenté, jamais orphelin)")
        return {str(k): v for k, v in delta.items()}

    def _tokens(self, rid, raw) -> list[dict]:
        poses = raw.get("tokens_initial")
        if poses is None:
            return []
        if not isinstance(poses, list) or not poses:
            raise ValueError(f"record {rid}: tokens_initial doit être une "
                             "liste non vide de poses")
        out = []
        for i, p in enumerate(poses):
            what = f"record {rid} tokens_initial[{i}]"
            if not isinstance(p, dict) or set(p) != {"node_id", "count",
                                                     "placement_md"}:
                raise ValueError(f"{what}: forme exacte exigée "
                                 "{node_id, count, placement_md}, got "
                                 f"{sorted(p) if isinstance(p, dict) else p!r}")
            node_id = p["node_id"]
            if not isinstance(node_id, str) or not _SLUG_RE.match(node_id):
                raise ValueError(f"{what}: node_id doit être un slug kebab "
                                 f"minuscule, got {node_id!r}")
            count = p["count"]
            if isinstance(count, bool) or not isinstance(count, int) \
                    or count < 1:
                raise ValueError(f"{what}: count doit être un entier >= 1, "
                                 f"got {count!r}")
            place = p["placement_md"]
            if not isinstance(place, str) or not place.strip():
                raise ValueError(f"{what}: placement_md requis (où la source "
                                 "dit de poser le jeton)")
            out.append({"node_id": node_id, "count": int(count),
                        "placement_md": place.strip()})
        return out

    def _persistent(self, rid, raw, stats) -> list[str]:
        decl = raw.get("persistent")
        if decl is None:
            return []
        if not isinstance(decl, list) or not decl:
            raise ValueError(f"record {rid}: persistent doit être une liste "
                             "non vide d'attributs déclarés (delta persist "
                             "1b84258)")
        out = []
        for a in decl:
            attr = str(a)
            if attr not in stats:
                raise ValueError(f"record {rid}: attribut persistant "
                                 f"{attr!r} absent des stats du record — "
                                 "la déclaration 'persistent:' ne porte que "
                                 "des attributs existants")
            out.append(attr)
        return out

    def _objet_magique(self, rid, classe, stats) -> None:
        """D-252.2 (issue #62) — champs optionnels objets magiques : reste
        dans stats_5e (pas de _RESERVED, contrairement à ancre_srd/tokens_
        initial/persistent — ce sont de vraies stats, pas des métadonnées
        traversantes) mais chaque valeur postée dedans est vérifiée.
        secret_lie_id n'est ici vérifié qu'en FORME (slug) : la résolution
        vers un Secret existant est un contrôle inter-primitives, porté par
        validate_form (Record n'a pas accès à la partition)."""
        keys = ("type_objet", "rarete", "harmonisation",
                "condition_harmonisation", "activation", "charges",
                "recharge", "effets_md", "secret_lie_id")
        present = [k for k in keys if k in stats]
        if not present:
            return
        if classe != "objet":
            raise ValueError(f"record {rid} ({classe}): {present} réservés "
                             "à la classe objet (D-252.2)")
        if "type_objet" in stats and stats["type_objet"] not in TYPE_OBJET:
            raise ValueError(f"record {rid}: type_objet "
                             f"{stats['type_objet']!r} not in {TYPE_OBJET}")
        if "rarete" in stats and stats["rarete"] not in RARETE:
            raise ValueError(f"record {rid}: rarete {stats['rarete']!r} "
                             f"not in {RARETE}")
        if "activation" in stats and stats["activation"] not in ACTIVATION:
            raise ValueError(f"record {rid}: activation "
                             f"{stats['activation']!r} not in {ACTIVATION}")
        if "harmonisation" in stats \
                and not isinstance(stats["harmonisation"], bool):
            raise ValueError(f"record {rid}: harmonisation doit être un "
                             f"booléen, got {stats['harmonisation']!r}")
        if "condition_harmonisation" in stats and not stats.get("harmonisation"):
            raise ValueError(f"record {rid}: condition_harmonisation sans "
                             "harmonisation=true — une condition ne porte "
                             "que sur une harmonisation requise")
        if "recharge" in stats and "charges" not in stats:
            raise ValueError(f"record {rid}: recharge sans charges — une "
                             "recharge est toujours relative à un nombre de "
                             "charges déclaré")
        if "charges" in stats:
            c = stats["charges"]
            if isinstance(c, bool) or not isinstance(c, int) or c < 0:
                raise ValueError(f"record {rid}: charges doit être un "
                                 f"entier >= 0, got {c!r}")
        if "secret_lie_id" in stats:
            check_id(str(stats["secret_lie_id"]),
                     f"record {rid} secret_lie_id")


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


class Tension:
    """Inventaire de tension traversant (D-218 §1) — premier exemplaire réel.

    Chaque entrée repère UN élément de tension du module avec son ancrage
    node : menace, horloge/échéance, coût, choix, révélation.
    Convertir, jamais créer : sans matière source, l'entrée n'existe pas.
    """

    def __init__(self, tid: str, categorie: str, description_md: str,
                 node_id: str,
                 anchors: list[tuple[int, int]] | list[int] | None = None):
        check_id(tid, "tension")
        if categorie not in TENSION_CATEGORIES:
            raise ValueError(f"tension {tid}: categorie {categorie!r} not in "
                             f"{TENSION_CATEGORIES}")
        if not description_md or not str(description_md).strip():
            raise ValueError(f"tension {tid}: description_md vide")
        check_id(node_id, f"tension {tid} node_id")
        if not anchors:
            raise ValueError(f"tension {tid}: no source anchor — every tension "
                             "cites what it translates (D-218 §1)")
        norm = []
        for a in anchors or []:
            norm.append((int(a), int(a)) if isinstance(a, int) else
                        (int(a[0]), int(a[1])))
        self.id = tid
        self.categorie = categorie
        self.description_md = str(description_md).strip()
        self.node_id = node_id
        self.anchors = norm

    def to_dict(self) -> dict:
        return {"id": self.id, "categorie": self.categorie,
                "description_md": self.description_md,
                "node_id": self.node_id,
                "ancres_sources": [list(a) for a in self.anchors]}


class Ressource:
    """Primitive générique Ressource (D-216 §2, D-217 poste uniquement).

    Premier cas d'usage = carte (maps booklet p99-117, tilepage/submap).
    Générique par construction : `type` ∈ RESSOURCE_TYPES, ancrage par
    `node_id` (node existant) OU `page` (numéro de page PDF, 1-based) — au
    moins un des deux est requis — `fichier` est le chemin relatif côté poste
    (corpus-modules/.../resources/, jamais dans git, jamais dans le vault
    joueur), `anchors` cite la matière source (SPEC-P4 §3).
    """

    def __init__(self, rid: str, type_ressource: str,
                 anchors: list[tuple[int, int]] | list[int] | None = None,
                 node_id: str | None = None,
                 page: int | None = None,
                 fichier: str | None = None,
                 description_md: str = ""):
        check_id(rid, "ressource")
        if type_ressource not in RESSOURCE_TYPES:
            raise ValueError(f"ressource {rid}: type {type_ressource!r} not in "
                             f"{RESSOURCE_TYPES} (D-216 §2 générique, premier cas carte)")
        if node_id is not None:
            check_id(node_id, f"ressource {rid} node_id")
        if page is not None:
            if not isinstance(page, int) or isinstance(page, bool) or not (1 <= page <= 500):
                raise ValueError(f"ressource {rid}: page doit être un entier 1..500, got {page!r}")
        if not node_id and not page:
            raise ValueError(f"ressource {rid}: ancrage manquant — au moins node_id ou page requis (fiche P-CONV-3)")
        if not anchors:
            raise ValueError(f"ressource {rid}: no source anchor — every ressource "
                             "cites what it translates (SPEC-P4 §3)")
        norm = []
        for a in anchors or []:
            norm.append((int(a), int(a)) if isinstance(a, int) else
                        (int(a[0]), int(a[1])))
        self.id = rid
        self.type_ressource = type_ressource
        self.node_id = node_id
        self.page = page
        self.fichier = str(fichier).strip() if fichier else ""
        self.description_md = str(description_md or "")
        self.anchors = norm

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type_ressource,
                "node_id": self.node_id, "page": self.page,
                "fichier": self.fichier,
                "description_md": self.description_md,
                "ancres_sources": [list(a) for a in self.anchors]}


class Personnage:
    """Primitive Personnage + Destinée (I-341, D-219, D-220).

    Le personnage n'est pas un prérequis à l'ingestion, c'est UNE SORTIE de
    l'ingestion — créé après le premier module, via fenêtres négociables.
    La destinée est un chemin biographique VAGUE mais CONNU, structuré en
    jalons flous rattachables (D-129/D-135 via D-220 : passé/intention seuls,
    jamais futur ni événement).

    acquis_conversation : choix négociés issus de la conversation d'accord,
    vide à l'état initial avant B.
    destinee : liste de jalons flous, chacun {id, intention_md, rattachement?}
    où rattachement pointe un id existant de la partition (node_id,
    ressource_id, tension_id) — garde zéro-dangling portée par emit/validate.
    """

    def __init__(self, pid: str, nom: str,
                 acquis_conversation: list[str] | None = None,
                 destinee: list[dict] | None = None):
        check_id(pid, "personnage")
        if not nom or not str(nom).strip():
            raise ValueError(f"personnage {pid}: nom vide")
        self.id = pid
        self.nom = str(nom).strip()
        self.acquis_conversation = [str(a) for a in (acquis_conversation or [])]
        self.destinee: list[dict] = []
        for i, j in enumerate(destinee or []):
            self.destinee.append(self._check_jalon(j, pid, i))
        if len(self.destinee) < 2:
            raise ValueError(f"personnage {pid}: destinee exige au moins 2 "
                             "jalons flous (D-220 : chemin biographique "
                             "vague mais connu)")

    def _check_jalon(self, j: dict, pid: str, idx: int) -> dict:
        jid = check_id(str(j.get("id", "")), f"personnage {pid} jalon[{idx}]")
        intention = str(j.get("intention_md", "")).strip()
        if not intention:
            raise ValueError(f"personnage {pid} jalon {jid}: intention_md vide")
        bas = intention.lower()
        for marqueur in JALON_INTERDITS_FUTUR:
            if marqueur in bas:
                raise ValueError(f"personnage {pid} jalon {jid}: "
                                 f"intention_md contient {marqueur!r} — "
                                 "D-129/D-135 : passé/intention seuls, "
                                 "jamais futur ni événement")
        ratt = j.get("rattachement")
        if ratt is not None:
            check_id(str(ratt), f"personnage {pid} jalon {jid} rattachement")
        return {"id": jid, "intention_md": intention,
                "rattachement": str(ratt) if ratt else None}

    def to_dict(self) -> dict:
        return {"id": self.id, "nom": self.nom,
                "acquis_conversation": self.acquis_conversation,
                "destinee": [{"id": j["id"], "intention_md": j["intention_md"],
                              **({"rattachement": j["rattachement"]}
                                 if j["rattachement"] else {})}
                             for j in self.destinee]}


class Fenetre:
    """Fenêtre de conversation d'accord (D-219 §Les quatre fenêtres, I-033).

    Chaque fenêtre couvre UNE dimension du personnage (F1 origine, F2 posture,
    F3 lien tension, F4 enjeu). Structure : negociable (bool), non_negociable_msg
    (contrainte module), tension_id (lien vers inventaire D-218), rattachement
    (id partition existant — node/tension/ressource).

    La borne à deux murs (I-033) refuse :
    - F3 (lien_tension) sans tension liée (a) — tension_id optionnelle pour
      F1/F2/F4, requise seulement pour F3 (D-219 §4, I-370a)
    - fenêtre négociable qui cite un secret (b, zéro-spoiler règle 1)
    - fenêtre dont le rattachement n'existe pas (c, zéro-dangling)
    """

    DIMENSIONS = ("origine", "posture", "lien_tension", "enjeu")

    def __init__(self, fid: str, dimension: str, titre: str,
                 contexte_md: str, options: list[str],
                 negociable: bool = True,
                 non_negociable_msg: str = "",
                 tension_id: str | None = None,
                 rattachement: str | None = None):
        check_id(fid, "fenetre")
        if dimension not in self.DIMENSIONS:
            raise ValueError(f"fenetre {fid}: dimension {dimension!r} not in "
                             f"{self.DIMENSIONS} (D-219 §4 fenêtres)")
        if not titre or not str(titre).strip():
            raise ValueError(f"fenetre {fid}: titre vide")
        if not options or len(options) < 1:
            raise ValueError(f"fenetre {fid}: options vide — au moins 1 option requise")
        self.id = fid
        self.dimension = dimension
        self.titre = str(titre).strip()
        self.contexte_md = str(contexte_md or "").strip()
        self.options = [str(o).strip() for o in options if str(o).strip()]
        self.negociable = bool(negociable)
        self.non_negociable_msg = str(non_negociable_msg or "").strip()
        if tension_id is not None:
            check_id(tension_id, f"fenetre {fid} tension_id")
        self.tension_id = tension_id
        if rattachement is not None:
            check_id(rattachement, f"fenetre {fid} rattachement")
        self.rattachement = rattachement

    def to_dict(self) -> dict:
        return {"id": self.id, "dimension": self.dimension,
                "titre": self.titre, "contexte_md": self.contexte_md,
                "options": self.options, "negociable": self.negociable,
                **({"non_negociable_msg": self.non_negociable_msg}
                   if self.non_negociable_msg else {}),
                **({"tension_id": self.tension_id} if self.tension_id else {}),
                **({"rattachement": self.rattachement} if self.rattachement else {})}


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
        self.tensions: list["Tension"] = []    # D-218 — inventaire traversant
        self.ressources: list["Ressource"] = []  # D-216 §2 — primitive générique (premier cas carte, D-217 poste uniquement)
        # alias anglais pour les outils/emission : resources <-> ressources
        self.resources = self.ressources
        self.personnages: list["Personnage"] = []  # I-341/D-219 — personnage + destinée
        self.fenetres: list["Fenetre"] = []  # I-033/D-219 — fenêtres conversation d'accord

    def ids(self) -> set[str]:
        return ({n.id for n in self.nodes} | {r.id for r in self.records}
                | {t.id for t in self.tables} | {s.id for s in self.secrets}
                | {t.id for t in getattr(self, "tensions", [])}
                | {r.id for r in getattr(self, "ressources", [])}
                | {r.id for r in getattr(self, "resources", [])}
                | {p.id for p in getattr(self, "personnages", [])}
                | {f.id for f in getattr(self, "fenetres", [])})
