"""Le Sélecteur de matière — organe Auteur (D-244, I-370b, fiche D-241 issue b).

Étape (2) de la séquence de création D-232 : le joueur dit ce qu'il veut
jouer et pourquoi (plancher : type d'univers + raison, texte libre) → CE
module apparie l'envie à de la matière au catalogue → le proposeur (issue
séparée) bâtit ensuite personnage + contrat sur le candidat retenu.

Arbitrage D-244 : le sélecteur est porté par l'AUTEUR — premier jugement de
doigté de la chaîne (apparier une pulsion à de la matière), PAS un lookup
déterministe du moteur. La sélection passe donc par le LLM (`emit_json_ex`,
même seam que `modules/trinity.py`) ; ce module ne fait JAMAIS le choix
lui-même, il pose le contrat d'entrée/sortie et la garde de forme autour du
jugement du LLM :

- **Entrée** : l'envie du joueur (texte libre) + le catalogue disponible.
- **Sortie** : des CANDIDATS D'ACTE — l'échelle est le premier acte (2-3
  aventures enchaînables, D-232), jamais un module isolé ni une campagne
  entière. Chaque candidat est ANCRÉ au catalogue (chaque module cité doit
  exister dans le catalogue transmis) et porte sa justification
  d'appariement. Un candidat sans ancre est REFUSÉ par `valider_forme` —
  jamais accepté sur la parole du LLM (même esprit que `validator.py` :
  le LLM propose, le code applique/refuse).

**Interface de catalogue posée par cette lane** (I-370b : « si le catalogue
à l'échelle d'acte n'existe pas encore dans le code, construire contre une
interface minimale + fixture synthétique, et signaler l'interface posée »).
`catalogue/README.md` décrit des entrées à l'échelle MODULE (mini | module |
mini-campagne) — aucune notion d'ACTE n'existe encore dans ce schéma. Ce
module ne modifie pas ce schéma : il consomme des `EntreeCatalogue` (mêmes 7
champs, seuls les champs déjà montrables par construction du schéma catalogue
— jamais de champ secret/interne) et laisse l'Auteur COMPOSER un candidat
d'acte en chaînant 2 à 3 entrées de cette liste. Le jour où un catalogue à
l'échelle d'acte existe en code, `EntreeCatalogue` peut se construire depuis
lui sans changer ce module.

Zéro spoiler (D-109, même esprit que `docs/gabarit-autorat-secrets-i159.md`) :
comme `EntreeCatalogue` ne porte que des champs déjà montrables (README
catalogue §schéma), rien de secret n'entre jamais dans le prompt du LLM —
la garde de forme vérifie en plus que `libelle` (la seule sortie montrable
au joueur) ne cite aucun id de catalogue tel quel.
"""
from __future__ import annotations

from dataclasses import dataclass

from .llm import emit_json_ex

# Bornes de l'échelle "premier acte" (D-232) : 2-3 aventures enchaînables,
# jamais un module isolé (1) ni une mini-campagne complète (4+).
MIN_MODULES_ACTE = 2
MAX_MODULES_ACTE = 3


@dataclass(frozen=True)
class EntreeCatalogue:
    """Une entrée de catalogue, à l'échelle MODULE (catalogue/README.md
    §schéma) — l'unité que l'Auteur chaîne pour composer un candidat d'acte.
    Seuls des champs déjà montrables par construction du schéma catalogue :
    aucun champ secret/interne ne vit ici, donc rien de tel n'entre jamais
    dans le prompt du LLM ni dans une sortie candidat."""
    id: str
    univers: str
    themes: tuple[str, ...]
    personnage_sert: str
    echelle: str
    puissance_attendue: str
    statut: str = "non-ingere"

    def to_prompt_dict(self) -> dict:
        """Projection montrable au LLM — mêmes champs que le schéma
        catalogue, jamais plus (pas de champ secret à filtrer : il n'y en a
        pas dans cette dataclass, par construction)."""
        return {"id": self.id, "univers": self.univers,
                "themes": list(self.themes),
                "personnage_sert": self.personnage_sert,
                "echelle": self.echelle,
                "puissance_attendue": self.puissance_attendue}


@dataclass(frozen=True)
class CandidatActe:
    """Un candidat d'acte (2-3 aventures enchaînables, D-232) — ANCRÉ : les
    ids de `modules` existent tous dans le catalogue transmis à
    `selectionner`. `libelle` est la SEULE sortie montrable au joueur ;
    `justification` explique le doigté (pourquoi cette matière répond à
    l'envie) et peut circuler côté auteur/logs, pas nécessairement au
    joueur."""
    modules: tuple[str, ...]
    justification: str
    libelle: str

    def id(self) -> str:
        """Identité dérivée stable d'un candidat (I-57, RACCORD proposeur) :
        la concaténation ordonnée des ids de modules — jamais un id saisi à
        la main, jamais stocké comme champ (deux candidats aux mêmes modules
        dans le même ordre partagent la même identité, par construction)."""
        return "+".join(self.modules)

    def to_dict(self) -> dict:
        return {"modules": list(self.modules),
                "justification": self.justification,
                "libelle": self.libelle}


SELECTEUR_SYS = """\
You are the SÉLECTEUR DE MATIÈRE, an authorial judgment organ (not a lookup \
engine). A player has stated what kind of story they want to play and why. \
You are given a CATALOGUE of available modules (id, univers, themes, what \
the module asks of/offers a protagonist, scale, expected power level).

Propose ACT-SCALE candidates: each candidate CHAINS %d to %d catalogue \
modules (by id, in play order) into one playable first act. Every id you \
cite MUST come from the catalogue given to you — never invent one. Pick \
modules from the SAME univers within one candidate (a chained act does not \
cross settings).

For each candidate give a short player-facing "libelle" (what the act is \
about, in inviting prose) that NEVER quotes a catalogue id, an internal \
name, or any upcoming twist — and a "justification" (why this matter \
answers the player's stated envie).

Return ONLY a JSON object:
{"candidats": [{"modules": ["id-1", "id-2"],
                "libelle": "...", "justification": "..."}]}
""" % (MIN_MODULES_ACTE, MAX_MODULES_ACTE)


def _payload(envie: str, catalogue: list[EntreeCatalogue]) -> str:
    import json
    return ("ENVIE DU JOUEUR:\n" + envie.strip()
            + "\n\nCATALOGUE DISPONIBLE:\n"
            + json.dumps([e.to_prompt_dict() for e in catalogue],
                          ensure_ascii=False))


def _valider_candidat(raw: dict, ids_connus: dict[str, EntreeCatalogue]) -> tuple[CandidatActe | None, str | None]:
    """Garde de forme (I-370b) : un candidat sans ancre au catalogue est
    REFUSÉ ici, jamais accepté sur parole du LLM. Retourne (candidat, None)
    si valide, sinon (None, raison)."""
    if not isinstance(raw, dict):
        return None, "candidat n'est pas un objet"
    modules = raw.get("modules")
    if not isinstance(modules, list) or not modules:
        return None, "candidat sans champ 'modules' (liste d'ids)"
    modules = [str(m).strip() for m in modules if str(m).strip()]
    if not (MIN_MODULES_ACTE <= len(modules) <= MAX_MODULES_ACTE):
        return None, (f"échelle acte violée : {len(modules)} module(s) "
                      f"(attendu {MIN_MODULES_ACTE}-{MAX_MODULES_ACTE})")
    manquants = [m for m in modules if m not in ids_connus]
    if manquants:
        return None, f"ancre catalogue manquante : {', '.join(manquants)}"
    if len(set(modules)) != len(modules):
        doublons = sorted({m for m in modules if modules.count(m) > 1})
        return None, f"module chaîné plusieurs fois dans le même acte : {', '.join(doublons)}"
    avec_plus = sorted(m for m in modules if "+" in m)
    if avec_plus:
        return None, (
            "id de module contenant '+' interdit — collision avec le "
            "séparateur de CandidatActe.id() (I-57) et non-conforme à la "
            "convention de slug kebab-case inter-modules "
            f"(docs/identite-inter-modules-d253.md) : {', '.join(avec_plus)}")
    univers = {ids_connus[m].univers for m in modules}
    if len(univers) > 1:
        return None, f"modules de plusieurs univers dans un même acte : {sorted(univers)}"
    justification = str(raw.get("justification", "")).strip()
    if not justification:
        return None, "candidat sans justification"
    libelle = str(raw.get("libelle", "")).strip()
    if not libelle:
        return None, "candidat sans libelle montrable"
    fuite = [m for m in ids_connus if m in libelle]
    if fuite:
        return None, f"libelle cite un id de catalogue (zéro spoiler) : {', '.join(fuite)}"
    return CandidatActe(tuple(modules), justification, libelle), None


def selectionner(envie: str, catalogue: list[EntreeCatalogue], llm,
                  *, retry: int = 1) -> tuple[list[CandidatActe], list[dict]]:
    """Fait porter le jugement de doigté au LLM (organe Auteur, D-244) puis
    applique la garde de forme (jamais un candidat accepté sur parole).

    Retourne `(candidats, rejets)` : `candidats` est la liste des candidats
    d'acte ANCRÉS et prêts à être montrés au joueur ; `rejets` liste chaque
    proposition écartée avec sa raison — jamais silencieux (même esprit que
    `validator.rejection_text`)."""
    envie = (envie or "").strip()
    if not envie:
        return [], [{"candidat": None, "raison": "envie vide (plancher : "
                     "type d'univers + raison)"}]
    if not catalogue:
        return [], [{"candidat": None, "raison": "catalogue vide"}]
    ids_connus = {e.id: e for e in catalogue}

    obj, err = emit_json_ex(llm, SELECTEUR_SYS, _payload(envie, catalogue),
                            retry=retry)
    if obj is None:
        return [], [{"candidat": None, "raison": f"appel LLM échoué : {err}"}]
    bruts = obj.get("candidats")
    if not isinstance(bruts, list):
        return [], [{"candidat": None,
                     "raison": "sortie LLM sans champ 'candidats' (liste)"}]

    candidats: list[CandidatActe] = []
    rejets: list[dict] = []
    for raw in bruts:
        candidat, raison = _valider_candidat(raw, ids_connus)
        if candidat is not None:
            candidats.append(candidat)
        else:
            rejets.append({"candidat": raw, "raison": raison})
    return candidats, rejets


def sortie_montrable(candidats: list[CandidatActe]) -> str:
    """Concatène tout ce qui est montrable au joueur (`libelle` seul,
    jamais `justification` ni `modules`) — le texte à passer au grep
    zéro-spoiler (ids internes / secrets de la fixture)."""
    return "\n".join(c.libelle for c in candidats)
