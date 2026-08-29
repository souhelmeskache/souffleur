"""Le stock de formes — vocabulaire composable versionné (D-261).

Quand l'Auteur doit écrire du scénario (cas 2/3 de D-117 — le joueur hors des
sentiers), il ne crée pas librement : il CHOISIT dans un stock de formes
narratives publiques éprouvées (fonctions de Propp, situations de Polti,
contes-types ATU — `catalogue/formes/`, domaine public seul), les assemble et
les colorie à la campagne. Ce module porte deux choses, même pattern que
`selecteur.py`/`validator.py` (le LLM propose, le code refuse) :

- `charger_vocabulaire()` — lit le stock versionné (jamais de réseau, jamais
  de matériau de campagne : ce vocabulaire est public et versionné dans ce
  repo, `catalogue/formes/README.md`).
- `valider_declaration(...)` — la garde de forme sur une déclaration
  d'Auteur : amendement 2 de D-261, les formes utilisées sont DÉCLARÉES
  (id + justification) et tracées — jamais de convocation implicite. Une
  déclaration vide, un id hors vocabulaire ou une justification vide sont
  REFUSÉS ici, jamais acceptés sur la parole du LLM ; les rejets sont
  motivés, jamais silencieux.
- `bloc_prompt(...)` — le bloc de prompt réutilisable qui présente le
  vocabulaire (ou un sous-ensemble filtré) et exige la déclaration + le lien
  à la pulsion du personnage + la part d'adversité (amendement 3 de D-261 :
  les briques portent l'efficacité, jamais l'unicité).

⚠️ L'organe qui écrit les épisodes n'existe pas encore dans le code (issue
#133) : ce module pose le socle consommable par lui, sans câblage dans un
organe inexistant.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Racine du stock versionné (catalogue/formes/, domaine public — README.md
# de ce dossier détaille la licence). Résolu relativement à ce fichier, pas
# au cwd, pour que le module fonctionne quel que soit l'appelant.
_RACINE_FORMES = Path(__file__).resolve().parent.parent / "catalogue" / "formes"

# Les trois index composant le stock (D-261 amendement 1) : Propp en
# colonne vertébrale (fonctions), Polti (situations), ATU (contes-types,
# sélection raisonnée — jamais l'index entier).
_FICHIERS_VOCABULAIRE = ("propp.json", "polti.json", "atu.json")


@dataclass(frozen=True)
class Forme:
    """Une forme narrative du stock (D-261) — atome COMPOSABLE, jamais un
    trope de surface. `exige` porte ce que la forme demande au récit pour
    fonctionner (adversité, coût, renversement…) ; `compose_avec` liste les
    ids d'autres formes avec lesquelles celle-ci s'enchaîne naturellement."""
    id: str
    nom: str
    source: str
    description: str
    exige: tuple[str, ...]
    compose_avec: tuple[str, ...]

    def to_prompt_dict(self) -> dict:
        """Projection montrable au LLM — mêmes champs que le schéma
        versionné, jamais plus."""
        return {"id": self.id, "nom": self.nom, "source": self.source,
                "description": self.description, "exige": list(self.exige),
                "compose_avec": list(self.compose_avec)}


def charger_vocabulaire(racine: Path | None = None) -> dict[str, Forme]:
    """Lit le stock de formes versionné (`catalogue/formes/*.json`) et
    retourne un dict `id -> Forme`. Jamais de réseau, jamais de matériau de
    campagne : ce vocabulaire est public et versionné dans ce repo."""
    racine = racine or _RACINE_FORMES
    vocabulaire: dict[str, Forme] = {}
    for nom_fichier in _FICHIERS_VOCABULAIRE:
        chemin = racine / nom_fichier
        brutes = json.loads(chemin.read_text(encoding="utf-8"))
        for raw in brutes:
            forme = Forme(
                id=str(raw["id"]), nom=str(raw["nom"]),
                source=str(raw["source"]),
                description=str(raw["description"]),
                exige=tuple(raw.get("exige", [])),
                compose_avec=tuple(raw.get("compose_avec", [])))
            if forme.id in vocabulaire:
                raise ValueError(f"id de forme dupliqué dans le stock versionné : {forme.id}")
            vocabulaire[forme.id] = forme
    return vocabulaire


def valider_declaration(declaration: list[dict],
                         vocabulaire: dict[str, Forme]) -> tuple[list[dict], list[dict]]:
    """Garde de forme (D-261 amendement 2) : une écriture d'Auteur déclare
    `formes: [{id, justification}]` — cette fonction REFUSE ce qui n'est
    pas ancré au vocabulaire, jamais accepté sur la parole du LLM.

    REFUS si : id hors vocabulaire, déclaration vide, justification vide.
    Retourne `(declarations_validees, rejets)` — chaque rejet porte sa
    raison, jamais silencieux (même esprit que `selecteur._valider_candidat`
    et `validator.rejection_text`)."""
    if not declaration:
        return [], [{"declaration": None, "raison": "déclaration vide "
                     "(au moins une forme, id + justification, est requise)"}]

    validees: list[dict] = []
    rejets: list[dict] = []
    for raw in declaration:
        if not isinstance(raw, dict):
            rejets.append({"declaration": raw, "raison": "déclaration n'est pas un objet"})
            continue
        forme_id = str(raw.get("id", "")).strip()
        justification = str(raw.get("justification", "")).strip()
        if not forme_id:
            rejets.append({"declaration": raw, "raison": "déclaration sans id de forme"})
            continue
        if forme_id not in vocabulaire:
            rejets.append({"declaration": raw,
                           "raison": f"id hors vocabulaire : {forme_id}"})
            continue
        if not justification:
            rejets.append({"declaration": raw,
                           "raison": f"déclaration de {forme_id} sans justification"})
            continue
        validees.append({"id": forme_id, "justification": justification})
    return validees, rejets


def bloc_prompt(vocabulaire: dict[str, Forme], *,
                 sous_ensemble: list[str] | None = None) -> str:
    """Bloc de prompt réutilisable (D-261) : présente le vocabulaire (ou un
    sous-ensemble filtré par id, ex. formes déjà signalées comme répétées)
    et EXIGE la déclaration + le lien à la pulsion du personnage + la part
    d'adversité (`exige` de la forme choisie). Ne fait aucun appel LLM —
    c'est un bloc de texte, l'appel reste à la charge de l'organe appelant."""
    if sous_ensemble is not None:
        formes = [vocabulaire[i] for i in sous_ensemble if i in vocabulaire]
    else:
        formes = list(vocabulaire.values())
    catalogue_json = json.dumps([f.to_prompt_dict() for f in formes],
                                 ensure_ascii=False)
    return (
        "STOCK DE FORMES DISPONIBLE (domaine public — fonctions de Propp, "
        "situations de Polti, contes-types ATU) :\n"
        + catalogue_json
        + "\n\nTu n'inventes pas la dramaturgie : tu CHOISIS dans ce stock, "
          "tu assembles et tu colories à la campagne. Pour chaque forme "
          "retenue, tu dois DÉCLARER explicitement :\n"
          "- son id (tel qu'il apparaît dans le stock ci-dessus, jamais "
          "inventé) ;\n"
          "- une justification qui relie CETTE forme à la pulsion/toile du "
          "personnage (pourquoi ce choix, pas un autre) ;\n"
          "- comment la part d'adversité EXIGÉE par la forme (son champ "
          "\"exige\") est servie par ce que tu écris — le cadre exige sa "
          "part d'adversité, jamais une forme sans coût.\n\n"
          "Retourne la déclaration sous la forme "
          '{"formes": [{"id": "...", "justification": "..."}]} — '
          "jamais de forme convoquée implicitement, sans déclaration."
    )
