"""Le PROPOSEUR personnage+contrat et la boucle de refus (I-370c, MRPG-I-370,
étapes (3)-(4) de la séquence D-232 : bâtir personnage + contrat sur la
matière retenue, puis validation conjointe avec le joueur).

Règles actées (registre méta, hors périmètre de ce repo) :

  - D-232 : un contrat refusé ne se rafistole JAMAIS — la proposition
    suivante est AUTRE sur ses éléments centraux, jamais une variation
    cosmétique de la refusée.
  - D-245 (arbitrage Souhel du 29/08) : pas de quota de propositions codé en
    dur, et dès le premier refus PAS de deuxième proposition à l'aveugle —
    l'organe ouvre une discussion avec le joueur (capturée en clair dans
    `Friction`) AVANT toute reproposition ; la reproposition doit être
    informée par cette friction.

Ce module ne porte ni la conversation B (D-219, protocole complet — issue
#15) ni le raccord contrat/biographie (issue (d) de la même fiche) : c'est la
structure de proposition + le garde-fou du cycle de refus, hors séance.

RACCORD (I-57) : ce module consomme le `CandidatActe` réel de
`coderain.selecteur` (champs `modules`, `justification`, `libelle` — pas de
champ `id`). L'identité d'un candidat, utilisée comme `ancre_source`, est
l'id dérivé stable `CandidatActe.id()` (concaténation ordonnée des ids de
modules, jamais saisi à la main) — voir `selecteur.CandidatActe.id`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .selecteur import CandidatActe

CENTRAL = "central"
SECONDAIRE = "secondaire"
PORTEES = (CENTRAL, SECONDAIRE)

STATUTS = ("en_attente", "refusee", "retenue")


@dataclass
class EnvieJoueur:
    """Une envie exprimée par le joueur, retenue comme matière source au même
    titre qu'un candidat d'acte."""
    id: str
    texte: str = ""


@dataclass
class ElementPropose:
    """Un élément de la proposition — un trait de personnage OU une clause de
    contrat. Ancrage obligatoire (D-232) : `ancre_source` pointe l'id d'un
    `CandidatActe` ou d'une `EnvieJoueur` connu, jamais un texte libre."""
    label: str
    texte: str
    ancre_source: str
    portee: str = SECONDAIRE  # "central" | "secondaire" (diff anti-rafistolage)


@dataclass
class Friction:
    """Le point de friction capturé en clair après un refus (D-245). Jamais
    réécrit une fois capturé — une friction par refus, référencée par son id
    depuis la reproposition qu'elle informe."""
    id: str
    proposition_refusee_id: str
    point: str


@dataclass
class Proposition:
    """Une proposition personnage+contrat. `statut` transitionne
    en_attente -> refusee|retenue mais l'objet reste dans l'historique du
    registre quoi qu'il arrive — trace jamais réécrite ni supprimée (même
    doctrine que `campagne.set_statut`, D-186)."""
    id: str
    personnage: list[ElementPropose] = field(default_factory=list)
    contrat: list[ElementPropose] = field(default_factory=list)
    statut: str = "en_attente"
    friction_source_id: str | None = None  # None seulement pour la 1re proposition

    def elements(self) -> list[ElementPropose]:
        return self.personnage + self.contrat

    def centraux(self) -> set[tuple[str, str]]:
        """Signature des éléments centraux : (label, ancre_source). Sert au
        garde anti-rafistolage — deux propositions qui partagent une entrée
        ici ne sont pas vraiment AUTRES (D-232)."""
        return {(e.label, e.ancre_source) for e in self.elements()
                if e.portee == CENTRAL}


def valider(prop: Proposition) -> list[str]:
    """Validation de forme (livrable) : chaque élément a un texte et une
    ancre_source non vides ; la proposition porte au moins un élément."""
    errors: list[str] = []
    tag_prop = f"proposition[{prop.id}]"
    if not prop.elements():
        errors.append(f"{tag_prop}: aucun élément (personnage+contrat vides)")
    if prop.statut not in STATUTS:
        errors.append(f"{tag_prop}: statut '{prop.statut}' hors {list(STATUTS)}")
    for e in prop.elements():
        tag = f"{tag_prop}.{e.label}"
        if not e.texte.strip():
            errors.append(f"{tag}: texte vide")
        if not e.ancre_source.strip():
            errors.append(f"{tag}: ancre_source absente")
        if e.portee not in PORTEES:
            errors.append(f"{tag}: portée '{e.portee}' hors {list(PORTEES)}")
    return errors


def valider_ancrage(prop: Proposition, candidats: list[CandidatActe],
                     envies: list[EnvieJoueur]) -> list[str]:
    """Ancrage obligatoire (D-232) : chaque ancre_source doit pointer un
    candidat d'acte ou une envie joueur CONNUS — pas seulement une chaîne non
    vide (valider() ci-dessus ne vérifie que la forme). L'identité d'un
    candidat est son id dérivé (`CandidatActe.id()`), jamais un champ saisi
    à la main (I-57)."""
    ids = {c.id() for c in candidats} | {v.id for v in envies}
    errors: list[str] = []
    for e in prop.elements():
        if e.ancre_source not in ids:
            errors.append(
                f"proposition[{prop.id}].{e.label}: ancre_source "
                f"'{e.ancre_source}' ne pointe aucun candidat/envie connu")
    return errors


@dataclass
class RegistreProposeur:
    """Le journal append-only des propositions et frictions d'une même
    négociation personnage+contrat. Rien n'y est jamais réécrit ni supprimé —
    une proposition refusée reste dans `propositions`, une friction capturée
    reste dans `frictions` (trace biographique, même doctrine que
    `campagne.RegistreCampagne`/`set_statut`)."""
    propositions: list[Proposition] = field(default_factory=list)
    frictions: list[Friction] = field(default_factory=list)

    def derniere(self) -> Proposition | None:
        return self.propositions[-1] if self.propositions else None

    def friction_pour(self, proposition_id: str) -> Friction | None:
        return next((f for f in self.frictions
                     if f.proposition_refusee_id == proposition_id), None)

    def proposer(self, prop: Proposition) -> Proposition:
        """Enregistre une nouvelle proposition. Règle D-245 : si la dernière
        proposition du registre a été refusée, celle-ci DOIT porter une
        `friction_source_id` pointant une friction déjà capturée pour cette
        proposition refusée, et ne doit reprendre AUCUN de ses éléments
        centraux (D-232, anti-rafistolage) — sinon ValueError, jamais de
        reproposition à l'aveugle ni de quota codé en dur (aucune limite de
        compte ici : seule la présence de la friction fait foi)."""
        errors = valider(prop)
        if errors:
            raise ValueError("proposition invalide: " + "; ".join(errors))
        derniere = self.derniere()
        if derniere is not None and derniere.statut == "refusee":
            if prop.friction_source_id is None:
                raise ValueError(
                    "reproposition refusée : aucune friction_source_id — "
                    "pas de deuxième proposition à l'aveugle (D-245)")
            friction = self.friction_pour(derniere.id)
            if friction is None or friction.id != prop.friction_source_id:
                raise ValueError(
                    "reproposition refusée : friction_source_id ne pointe "
                    f"aucune friction capturée pour {derniere.id}")
            if not prop.centraux().isdisjoint(derniere.centraux()):
                raise ValueError(
                    "reproposition refusée : éléments centraux partagés "
                    "avec la proposition refusée — rafistolage interdit "
                    "(D-232)")
        self.propositions.append(prop)
        return prop

    def refuser(self, proposition_id: str) -> Proposition:
        """Passe une proposition à `refusee`. L'objet reste dans
        `propositions` — jamais réécrit ni supprimé (trace)."""
        prop = next((p for p in self.propositions if p.id == proposition_id),
                    None)
        if prop is None:
            raise ValueError(f"proposition inconnue: {proposition_id}")
        prop.statut = "refusee"
        return prop

    def retenir(self, proposition_id: str) -> Proposition:
        prop = next((p for p in self.propositions if p.id == proposition_id),
                    None)
        if prop is None:
            raise ValueError(f"proposition inconnue: {proposition_id}")
        prop.statut = "retenue"
        return prop

    def capturer_friction(self, proposition_id: str, point: str) -> Friction:
        """Capture le point de friction d'un refus, en clair, avant toute
        reproposition (D-245). Une proposition non refusée ne peut pas porter
        de friction."""
        prop = next((p for p in self.propositions if p.id == proposition_id),
                    None)
        if prop is None or prop.statut != "refusee":
            raise ValueError(
                f"capture de friction impossible: proposition "
                f"{proposition_id} non refusée")
        if not point.strip():
            raise ValueError("point de friction vide")
        friction = Friction(id=f"friction-{len(self.frictions) + 1}",
                             proposition_refusee_id=proposition_id,
                             point=point.strip())
        self.frictions.append(friction)
        return friction


def rendu_joueur(prop: Proposition) -> str:
    """Rendu montrable au joueur : jamais l'ancre_source (pointeur interne
    vers le candidat d'acte / l'envie), jamais l'id de la proposition ou de
    la friction, jamais le statut interne — même doctrine que le garde
    narrateur I-376 (`memory._context_render`), appliquée ici à la
    proposition plutôt qu'à une `Entry`."""
    lines = ["## Proposition"]
    if prop.personnage:
        lines.append("")
        lines.append("### Personnage")
        for e in prop.personnage:
            lines.append(f"- {e.texte}")
    if prop.contrat:
        lines.append("")
        lines.append("### Contrat")
        for e in prop.contrat:
            lines.append(f"- {e.texte}")
    return "\n".join(lines) + "\n"
