"""L'Auteur — détecteur de répétition à l'échelle campagne (I-229).

Aucun module ne « voit » les autres (le convertisseur ne connaît qu'UN
module à la fois, l'Adaptateur ne connaît qu'UNE partition) : l'Auteur est
le seul organe placé pour comparer deux scénarios. Ce module compare des
inventaires de tension (D-218 — six codes traversants : menace, horloge,
echeance, cout, choix, revelation) déjà émis par des scénarios distincts et
SIGNALE les motifs les plus proches — jamais une décision, jamais un rejet ;
l'Auteur reste seul juge de ce qui est une redite assumée ou un défaut.

D-220 (interdiction de rétro-création) : ce module ne construit, n'écrit ni
ne modifie aucune partition — lecture et rapport seuls, jamais branché en
séance, même esprit que campagne.py (« Ce module ne branche rien en
séance »). L'entrée est déjà émise (schemas/emit, P-CONV-3) : des dicts au
format `Tension.to_dict()` — {id, categorie, description_md, node_id,
ancres_sources} — jamais l'objet Partition lui-même, pour rester découplé
de sa construction/ses invariants. Déterministe, 100% hors-ligne (aucun
LLM, aucun réseau — CLAUDE.md) : le score combine l'égalité de code D-218
et la similarité textuelle (difflib, stdlib) du motif le plus proche.

Extension D-261 (stock de formes) : le même détecteur s'étend des codes de
tension aux FORMES déclarées (`coderain.formes.valider_declaration`) — il
signale la réutilisation d'un même id de forme (Propp/Polti/ATU) à travers
les scénarios d'une campagne. Même contrat que le détecteur de tension : un
SIGNAL, jamais une décision (une redite de forme peut être assumée — deux
scénarios qui rejouent délibérément la même situation dramatique — ou un
défaut : l'Auteur reste seul juge). L'entrée est la déclaration déjà
validée par `formes.valider_declaration` : des dicts {id, justification},
jamais le vocabulaire ni le texte du scénario lui-même.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass

from .converter.schemas import TENSION_CATEGORIES

# Seuil de similarité texte (SequenceMatcher.ratio, 0..1) en dessous duquel
# deux tensions de même code D-218 ne sont pas signalées comme motif proche.
# Pont qui réoutille à froid (doigté, docs/doigte-verrou-central.md #4) : UN
# seuil, recalibrable ici sans toucher au reste du code.
SEUIL_SIMILARITE = 0.6


@dataclass
class SignalRepetition:
    """Un signal, jamais une décision (I-229) : score par code D-218 +
    motif le plus proche, l'Auteur reste seul juge de la suite."""
    scenario_a: str
    scenario_b: str
    tension_a_id: str
    tension_b_id: str
    categorie: str
    score: float
    motif_proche: str

    def to_dict(self) -> dict:
        return {"scenario_a": self.scenario_a, "scenario_b": self.scenario_b,
                "tension_a_id": self.tension_a_id,
                "tension_b_id": self.tension_b_id,
                "categorie": self.categorie, "score": round(self.score, 4),
                "motif_proche": self.motif_proche}


def _similarite(a: str, b: str) -> float:
    """Similarité déterministe de deux motifs (0..1) — stdlib, pas de LLM."""
    return difflib.SequenceMatcher(None, a.strip().lower(),
                                    b.strip().lower()).ratio()


def comparer_paire(nom_a: str, tensions_a: list[dict],
                    nom_b: str, tensions_b: list[dict], *,
                    seuil: float = SEUIL_SIMILARITE) -> list["SignalRepetition"]:
    """Compare deux inventaires de tension (D-218) déjà émis et retourne les
    signaux au-dessus du seuil, triés du score le plus fort au plus faible.

    Pour chaque tension de A, ne retient que le meilleur motif de B PARTAGEANT
    LA MÊME CATÉGORIE D-218 (le code traverse, D-218 §1 — comparer un
    « horloge » à un « choix » ne veut rien dire) ; les tensions dont la
    catégorie est hors du contrat D-218 sont ignorées, pas rejetées — ce
    n'est pas le rôle de ce détecteur de refaire la garde d'emit."""
    signaux: list[SignalRepetition] = []
    for ta in tensions_a:
        cat = ta.get("categorie")
        if cat not in TENSION_CATEGORIES:
            continue
        desc_a = str(ta.get("description_md", ""))
        meilleur: tuple[float, dict] | None = None
        for tb in tensions_b:
            if tb.get("categorie") != cat:
                continue
            score = _similarite(desc_a, str(tb.get("description_md", "")))
            if meilleur is None or score > meilleur[0]:
                meilleur = (score, tb)
        if meilleur is not None and meilleur[0] >= seuil:
            score, tb = meilleur
            signaux.append(SignalRepetition(
                scenario_a=nom_a, scenario_b=nom_b,
                tension_a_id=str(ta.get("id", "")),
                tension_b_id=str(tb.get("id", "")),
                categorie=cat, score=score,
                motif_proche=str(tb.get("description_md", ""))))
    signaux.sort(key=lambda s: -s.score)
    return signaux


def detecter_campagne(scenarios: dict[str, list[dict]], *,
                       seuil: float = SEUIL_SIMILARITE) -> list["SignalRepetition"]:
    """Compare tous les scénarios de la campagne deux à deux — jamais un
    scénario contre lui-même, jamais une paire comptée deux fois. `scenarios`
    associe un nom de scénario à son inventaire de tensions déjà émis."""
    noms = sorted(scenarios)
    signaux: list[SignalRepetition] = []
    for i, nom_a in enumerate(noms):
        for nom_b in noms[i + 1:]:
            signaux.extend(comparer_paire(nom_a, scenarios[nom_a],
                                          nom_b, scenarios[nom_b], seuil=seuil))
    signaux.sort(key=lambda s: -s.score)
    return signaux


def rapport(signaux: list["SignalRepetition"]) -> dict:
    """Rapport de lecture, hors séance, pour l'Auteur — même esprit que
    `campagne.rapport()` : un compte par catégorie D-218, jamais un verdict."""
    par_categorie = {c: sum(1 for s in signaux if s.categorie == c)
                     for c in TENSION_CATEGORIES}
    return {
        "total": len(signaux),
        "par_categorie": par_categorie,
        "signaux": [s.to_dict() for s in signaux],
    }


@dataclass
class SignalRepetitionForme:
    """Un signal, jamais une décision (I-229 étendu aux formes, D-261) :
    même id de forme (Propp/Polti/ATU) déclaré dans deux scénarios distincts
    de la campagne — l'Auteur reste seul juge (redite assumée ou défaut)."""
    scenario_a: str
    scenario_b: str
    forme_id: str
    justification_a: str
    justification_b: str

    def to_dict(self) -> dict:
        return {"scenario_a": self.scenario_a, "scenario_b": self.scenario_b,
                "forme_id": self.forme_id,
                "justification_a": self.justification_a,
                "justification_b": self.justification_b}


def comparer_paire_formes(nom_a: str, formes_a: list[dict],
                           nom_b: str, formes_b: list[dict]) -> list["SignalRepetitionForme"]:
    """Compare deux déclarations de formes déjà validées (`formes.
    valider_declaration`, dicts {id, justification}) et signale tout id de
    forme partagé entre les deux scénarios — comparaison exacte sur l'id
    (une forme est déclarée ou ne l'est pas, pas de similarité floue ici,
    contrairement à `comparer_paire` sur les tensions)."""
    ids_b = {str(f.get("id", "")): str(f.get("justification", "")) for f in formes_b}
    signaux: list[SignalRepetitionForme] = []
    for fa in formes_a:
        forme_id = str(fa.get("id", ""))
        if not forme_id or forme_id not in ids_b:
            continue
        signaux.append(SignalRepetitionForme(
            scenario_a=nom_a, scenario_b=nom_b, forme_id=forme_id,
            justification_a=str(fa.get("justification", "")),
            justification_b=ids_b[forme_id]))
    return signaux


def detecter_campagne_formes(declarations: dict[str, list[dict]]) -> list["SignalRepetitionForme"]:
    """Compare toutes les déclarations de formes de la campagne deux à deux
    — jamais un scénario contre lui-même, jamais une paire comptée deux
    fois. `declarations` associe un nom de scénario à sa déclaration de
    formes déjà validée."""
    noms = sorted(declarations)
    signaux: list[SignalRepetitionForme] = []
    for i, nom_a in enumerate(noms):
        for nom_b in noms[i + 1:]:
            signaux.extend(comparer_paire_formes(
                nom_a, declarations[nom_a], nom_b, declarations[nom_b]))
    return signaux


def rapport_formes(signaux: list["SignalRepetitionForme"]) -> dict:
    """Rapport de lecture, hors séance, pour l'Auteur — même esprit que
    `rapport()` : un compte par id de forme, jamais un verdict."""
    par_forme: dict[str, int] = {}
    for s in signaux:
        par_forme[s.forme_id] = par_forme.get(s.forme_id, 0) + 1
    return {
        "total": len(signaux),
        "par_forme": par_forme,
        "signaux": [s.to_dict() for s in signaux],
    }
