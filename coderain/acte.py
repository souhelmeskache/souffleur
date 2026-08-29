"""L'objet ACTE — le cadre à trois lectures de l'Auteur (D-262, candidate).

Choix d'implantation (documenté ici, cf. PR) : fichier FRÈRE `actes.md`, porté
par ce module dédié, calqué sur `campagne.py` (D-186) — plutôt qu'une
extension de `campagne.md`. Motif : `campagne.md` porte un schéma déjà figé
(FilRouge/porte, D-186) consommé par `validate()`/`rapport()`/le convertisseur ;
y greffer un objet à trois sous-parties (jalons, raccord) aurait complexifié
son parseur ligne-à-ligne pour un concept d'une autre nature (l'acte structure
le TEMPS de la campagne, le fil rouge en structure la MATIÈRE). `campagne.py`
et son schéma ne sont donc PAS touchés par cette lane.

La campagne se pense en ACTES : grandes étapes grossières et détournables.
Quand l'Auteur doit écrire un épisode, sa première question est « dans quel
acte sommes-nous, où en est-il ? ». ⛔ L'acte ne doit pas être re-déduit à
chaque réveil de l'Auteur : c'est un RECORD du dispositif, avec un état
mesuré, jamais recalculé depuis zéro à chaque lecture. Il porte TROIS
LECTURES, toutes assemblées par du code — zéro appel LLM dans ce module :

    1. REMPLISSAGE — ses jalons, vécu ⊥ pas-vécu ⊥ abandonné, mesurés contre
       le vécu promu (`memory/aventure.md`, PR #135) présenté À CÔTÉ pour le
       jugement de l'Auteur — le code ne décide JAMAIS qu'un jalon est vécu,
       il présente les pièces ; le basculement de statut est un geste
       d'écriture explicite.
    2. DIVERGENCE — l'écart entre les actes du joueur et la trame : ce module
       assemble les PIÈCES du jugement (objectif + vécu récent), jamais un
       score ni un seuil (D-131) — le jugement reste LLM/Auteur.
    3. RACCORD — le prochain module choisi et ses conditions d'entrée.

Format `actes.md` (Markdown lisible seul, mêmes briques que `memory.parse_entries`
pour la coquille externe — id stable, attrs, corps — puis un mini-format à
trois sous-sections dans le corps) :

    # actes

    ## <id>  {#<id>}
    titre: <titre>
    statut: ouvert | clos

    ### objectif
    <objectif_md — états et potentiels, JAMAIS une séquence d'événements>

    ### jalons
    - [<jalon-id>] (vécu|pas-vécu|abandonné) <intention_md>

    ### raccord
    module_id: <module_id ou vide si pas encore choisi>

    <conditions_entree_md>

Rien ne s'efface (même esprit que D-186) : un acte clos reste dans le
fichier avec ses jalons et leur dernier statut."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .memory import ADVENTURE_FILE, Entry, MemoryStore, parse_entries

JALON_STATUTS = ("vécu", "pas-vécu", "abandonné")
ACTE_STATUTS = ("ouvert", "clos")

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SECTION_RE = re.compile(r"^###\s+(objectif|jalons|raccord)\s*$")
_JALON_RE = re.compile(
    r"^-\s*\[(?P<id>[a-z0-9][a-z0-9-]*)\]\s*"
    r"\((?P<statut>vécu|pas-vécu|abandonné)\)\s*(?P<intention>.*)$")
_MODULE_ID_RE = re.compile(r"^module_id:\s?(.*)$", re.IGNORECASE)

# Combien d'entrées récentes du vécu entrent dans les pièces de divergence —
# une fenêtre de lecture, jamais un seuil de jugement (D-131 : pas d'agrégat).
_FENETRE_VECU_RECENT = 5


@dataclass
class Jalon:
    id: str
    intention_md: str = ""
    statut: str = "pas-vécu"


@dataclass
class Raccord:
    module_id: str = ""
    conditions_entree_md: str = ""


@dataclass
class Acte:
    id: str
    titre: str = ""
    objectif_md: str = ""
    jalons: list[Jalon] = field(default_factory=list)
    raccord: Raccord = field(default_factory=Raccord)
    statut: str = "ouvert"

    def by_jalon(self, jalon_id: str) -> Jalon | None:
        return next((j for j in self.jalons if j.id == jalon_id), None)


@dataclass
class Actes:
    actes: list[Acte] = field(default_factory=list)

    def by_id(self, acte_id: str) -> Acte | None:
        return next((a for a in self.actes if a.id == acte_id), None)


def _split_sections(body: str) -> dict[str, str]:
    """Découpe le corps d'un acte en sous-sections `### objectif|jalons|raccord`.
    Tout texte avant le premier `###` est ignoré (coquille externe seule)."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        m = _SECTION_RE.match(line)
        if m:
            current = m.group(1)
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _parse_jalons(text: str) -> list[Jalon]:
    jalons = []
    for line in text.splitlines():
        m = _JALON_RE.match(line.strip())
        if m:
            jalons.append(Jalon(id=m.group("id"), statut=m.group("statut"),
                                intention_md=m.group("intention").strip()))
    return jalons


def _parse_raccord(text: str) -> Raccord:
    module_id, conditions_lines = "", []
    for line in text.splitlines():
        m = _MODULE_ID_RE.match(line)
        if m and not module_id and not conditions_lines:
            module_id = m.group(1).strip()
        else:
            conditions_lines.append(line)
    return Raccord(module_id=module_id,
                   conditions_entree_md="\n".join(conditions_lines).strip())


def load(text: str) -> Actes:
    """Parse actes.md. Réutilise `parse_entries` pour la coquille (id stable,
    attrs, corps), puis un mini-parseur pour les trois sous-sections du corps."""
    actes = []
    for e in parse_entries(text):
        titre = e.attrs.pop("titre", "").strip()
        statut = e.attrs.pop("statut", "").strip() or "ouvert"
        sections = _split_sections(e.body)
        objectif_md = sections.get("objectif", "")
        jalons = _parse_jalons(sections.get("jalons", ""))
        raccord = _parse_raccord(sections.get("raccord", ""))
        actes.append(Acte(id=e.slug, titre=titre, objectif_md=objectif_md,
                          jalons=jalons, raccord=raccord, statut=statut))
    return Actes(actes=actes)


def load_file(path: str | Path) -> Actes:
    p = Path(path)
    return load(p.read_text(encoding="utf-8") if p.exists() else "")


def render(actes: Actes) -> str:
    out = ["# actes", ""]
    for a in actes.actes:
        out.append(f"## {a.id}  {{#{a.id}}}")
        out.append(f"titre: {a.titre}")
        out.append(f"statut: {a.statut}")
        out.append("")
        out.append("### objectif")
        out.append(a.objectif_md.strip())
        out.append("")
        out.append("### jalons")
        for j in a.jalons:
            out.append(f"- [{j.id}] ({j.statut}) {j.intention_md.strip()}")
        out.append("")
        out.append("### raccord")
        out.append(f"module_id: {a.raccord.module_id}")
        out.append("")
        out.append(a.raccord.conditions_entree_md.strip())
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def save_file(actes: Actes, path: str | Path) -> None:
    Path(path).write_text(render(actes), encoding="utf-8")


def validate(actes: Actes) -> list[str]:
    """Garde de forme (livrable 4) : un acte sans `objectif_md`, ou avec un
    jalon sans `intention_md`, est REFUSÉ — rejet motivé, jamais silencieux.
    Retourne une liste de messages d'erreur ; vide == valide."""
    errors: list[str] = []
    seen: set[str] = set()
    for a in actes.actes:
        tag = f"acte[{a.id}]"
        if not _ID_RE.match(a.id):
            errors.append(f"{tag}: id non conforme au slug stable")
        if a.id in seen:
            errors.append(f"{tag}: id dupliqué")
        seen.add(a.id)
        if not a.objectif_md.strip():
            errors.append(f"{tag}: objectif_md absent")
        if a.statut not in ACTE_STATUTS:
            errors.append(f"{tag}: statut '{a.statut}' hors {list(ACTE_STATUTS)}")
        seen_jalons: set[str] = set()
        for j in a.jalons:
            jtag = f"{tag}.jalon[{j.id}]"
            if not _ID_RE.match(j.id):
                errors.append(f"{jtag}: id non conforme au slug stable")
            if j.id in seen_jalons:
                errors.append(f"{jtag}: id dupliqué")
            seen_jalons.add(j.id)
            if not j.intention_md.strip():
                errors.append(f"{jtag}: intention_md absente")
            if j.statut not in JALON_STATUTS:
                errors.append(f"{jtag}: statut '{j.statut}' hors {list(JALON_STATUTS)}")
    return errors


def _vecu_promu(store: MemoryStore) -> list[dict]:
    """Les entrées promues de `memory/aventure.md` (PR #135), projetées pour
    présentation côte à côte — titre + corps tels quels, aucune synthèse."""
    return [{"id": e.slug, "titre": e.title, "resume_md": e.body.strip()}
            for e in store.entries(ADVENTURE_FILE)]


def remplissage(acte: Acte, store: MemoryStore | None = None) -> dict:
    """Lecture 1 (REMPLISSAGE) : comptage vécu/pas-vécu/abandonné des jalons,
    PLUS le rapprochement avec le vécu réel — les entrées promues de
    `memory/aventure.md` présentées EN REGARD des jalons pour le jugement de
    l'Auteur. Le code ne décide jamais qu'un jalon est vécu ; il présente les
    pièces (aucun score, aucun seuil)."""
    return {
        "total": len(acte.jalons),
        "vecu": sum(1 for j in acte.jalons if j.statut == "vécu"),
        "pas_vecu": sum(1 for j in acte.jalons if j.statut == "pas-vécu"),
        "abandonne": sum(1 for j in acte.jalons if j.statut == "abandonné"),
        "jalons": [{"id": j.id, "statut": j.statut, "intention_md": j.intention_md}
                  for j in acte.jalons],
        "vecu_promu": _vecu_promu(store) if store is not None else [],
    }


def pieces_divergence(acte: Acte, store: MemoryStore,
                      fenetre: int = _FENETRE_VECU_RECENT) -> dict:
    """Lecture 2 (DIVERGENCE) : assemble les PIÈCES du jugement — objectif de
    l'acte + dernières entrées du vécu — en un bloc présentable. AUCUN score,
    aucun seuil : le jugement de l'écart entre les actes du joueur et la
    trame reste LLM/Auteur (D-131)."""
    return {
        "objectif_md": acte.objectif_md,
        "vecu_recent": _vecu_promu(store)[-fenetre:],
    }


def bloc_cadre(acte: Acte, store: MemoryStore | None = None) -> str:
    """Le rendu complet des trois lectures, prêt à entrer dans un prompt
    d'Auteur (le futur organe d'écriture d'épisodes, hors périmètre de cette
    lane, en est le lecteur nommé)."""
    rempl = remplissage(acte, store)
    diverg = pieces_divergence(acte, store) if store is not None else \
        {"objectif_md": acte.objectif_md, "vecu_recent": []}

    lines = [f"# ACTE {acte.id} — {acte.titre}  (statut: {acte.statut})", ""]

    lines.append("## 1. Remplissage")
    lines.append(f"Jalons : {rempl['vecu']} vécu(s), {rempl['pas_vecu']} "
                 f"pas-vécu(s), {rempl['abandonne']} abandonné(s) sur "
                 f"{rempl['total']}.")
    for j in rempl["jalons"]:
        lines.append(f"- [{j['id']}] ({j['statut']}) {j['intention_md']}")
    lines.append("")
    lines.append("Vécu promu (memory/aventure.md), en regard des jalons "
                 "ci-dessus — le basculement de statut reste un geste "
                 "d'écriture explicite :")
    if rempl["vecu_promu"]:
        for v in rempl["vecu_promu"]:
            lines.append(f"- {v['titre']} : {v['resume_md']}")
    else:
        lines.append("(aucune entrée promue pour l'instant)")
    lines.append("")

    lines.append("## 2. Divergence")
    lines.append("Objectif de l'acte :")
    lines.append(diverg["objectif_md"].strip())
    lines.append("")
    lines.append("Dernières entrées du vécu :")
    if diverg["vecu_recent"]:
        for v in diverg["vecu_recent"]:
            lines.append(f"- {v['titre']} : {v['resume_md']}")
    else:
        lines.append("(aucune entrée promue pour l'instant)")
    lines.append("(jugement LLM/Auteur — le code présente les pièces, il ne "
                 "score jamais, D-131)")
    lines.append("")

    lines.append("## 3. Raccord")
    lines.append(f"Module suivant : {acte.raccord.module_id or '(pas encore choisi)'}")
    lines.append("Conditions d'entrée :")
    lines.append(acte.raccord.conditions_entree_md.strip() or "(aucune)")

    return "\n".join(lines).rstrip("\n") + "\n"
