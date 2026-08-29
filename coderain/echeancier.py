"""L'Échéancier trans-modules (D-253.1, Issue #71) — conditions vivantes
extraites, re-script qui en perd une REFUSE.

Trou §3.1 du rapport `docs/audit-2-materiel-campagne-d252.md` (ligne 23) :
un front/échéance DATÉ posé dans un module (`Aventure.trajectoire`/
`conditions`, `Evenement.declencheur` de type `delai`/`etat`/`date`, D-119/
D-120) n'a AUCUN porteur persistant entre deux modules — campagne.md refuse
tout futur par conception (Règle 5 D-186), la toile ne porte que des secrets
(D-241). La règle actée (proposition (a) du rapport) : à chaque passe de
réadaptation, toute condition non échue est RÉ-ÉMISE dans le matériau
re-scripté — "pure discipline de passe, zéro forme nouvelle, vérifiable par
un garde de réadaptation".

Ce module fournit les deux briques, jamais l'organe de réadaptation lui-même
(chantier I-371d, séparé) :
  - `extraire()` — lit une `Aventure` déjà construite (D-178/D-182,
    `converter/schemas.py`) et retourne l'inventaire des conditions VIVANTES
    (delai/date non échues à une date de référence), ÉCHUES, et à déclencheur
    `etat` (listées, jamais datées — hors périmètre de la garde, documenté
    ci-dessous).
  - `garder_reportage()` — la GARDE elle-même : compare l'échéancier AVANT
    re-script à l'`Aventure` (+ `Patch`s) APRÈS et refuse (liste d'erreurs,
    jamais une exception — même esprit que `campagne.validate`/
    `toile.validate`) si une condition vivante de l'avant n'a nulle part de
    porteur dans l'après.

Lecture et calcul seuls : ce module ne construit, n'écrit ni ne modifie
aucune partition (même discipline que `author.py`, D-220) — déterministe,
100% hors-ligne (aucun LLM, aucun réseau, CLAUDE.md). La garde est une
fonction appelable, pas un crochet obligatoire : le futur organe de
réadaptation (I-371d) l'appellera quand il existera ; rien de l'existant ne
change de comportement tant que personne ne l'appelle (rétrocompatibilité
totale).

Hors périmètre garde v0 : les déclencheurs `etat` (non datés, D-119) n'ont
pas de notion d'échéance calendaire — `extraire()` les liste pour inventaire
complet (`Echeancier.etats`) mais `garder_reportage()` ne les compare jamais ;
le critère d'échéance ne s'y applique pas (spec Issue #71).

Convention de lecture des valeurs (le schéma `Evenement.declencheur.valeur`
reste du texte libre, D-182 — rien n'est retouché ici) :
  - `date`  : `AAAA-MM-JJ` (ISO 8601), l'échéance est cette date.
  - `delai` : `J+<n>` ou `<n> jour(s)|semaine(s)|mois` (mois = 30 jours,
    convention interne, documentée) — relatif à `date_pose` (la date à
    laquelle le module qui porte la condition a été posé dans la campagne),
    fournie par l'appelant, jamais devinée.
  - Une valeur illisible n'est jamais une erreur bloquante ici (ce module ne
    lève pas) : la condition est exclue de l'échéancier et signalée dans
    `Echeancier.avertissements`, à charge de l'appelant (même discipline que
    `Aventure._build` — "PERTE SIGNALÉE, jamais une improvisation").

Ancre : les `Evenement.anchors` sont des offsets caractère dans le texte
source (backbone anti-hallucination, `validate_fidelity.py`), pas des
numéros de ligne. `extraire()` compose une ancre lisible
`<fichier>:<offset_départ>-<offset_fin>` à partir du premier anchor (ou
`<fichier>:<id>` si l'événement n'en porte aucun) — `fichier` désigne la
partition/le module d'origine, fourni par l'appelant.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .converter.schemas import Aventure, Evenement, Patch

_UNITES_JOURS = {"jour": 1, "jours": 1, "semaine": 7, "semaines": 7,
                 "mois": 30}
_RE_DELAI_J = re.compile(r"^j\+(\d+)$")
_RE_DELAI_UNITE = re.compile(
    r"^(\d+)\s*(jour|jours|semaine|semaines|mois)$")


def _parse_delai_jours(valeur: str) -> int | None:
    """`J+30` ou `<n> jour(s)|semaine(s)|mois` -> nombre de jours, ou None
    si illisible (jamais une exception, cf. discipline du module)."""
    v = valeur.strip().lower()
    m = _RE_DELAI_J.match(v)
    if m:
        return int(m.group(1))
    m = _RE_DELAI_UNITE.match(v)
    if m:
        return int(m.group(1)) * _UNITES_JOURS[m.group(2)]
    return None


def _parse_date(valeur: str) -> date | None:
    try:
        return datetime.strptime(valeur.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _ancre(ev: Evenement, fichier: str) -> str:
    prefix = f"{fichier}:" if fichier else ""
    if ev.anchors:
        start, end = ev.anchors[0]
        return f"{prefix}{start}-{end}"
    return f"{prefix}{ev.id}"


@dataclass
class ConditionVivante:
    """Une condition datée/à délai, non échue à la date de référence — ce
    que la garde de réadaptation protège de la perte."""
    porteur_id: str
    type_declencheur: str      # "delai" | "date"
    echeance: date
    ancre: str
    description_md: str

    def to_dict(self) -> dict:
        return {"porteur_id": self.porteur_id,
                "type_declencheur": self.type_declencheur,
                "echeance": self.echeance.isoformat(),
                "ancre": self.ancre,
                "description_md": self.description_md}


@dataclass
class ConditionEtat:
    """Déclencheur `etat` — listé pour inventaire complet, HORS périmètre de
    la garde v0 (pas d'échéance calendaire, cf. docstring module)."""
    porteur_id: str
    valeur: str
    ancre: str
    description_md: str

    def to_dict(self) -> dict:
        return {"porteur_id": self.porteur_id, "valeur": self.valeur,
                "ancre": self.ancre, "description_md": self.description_md}


@dataclass
class Echeancier:
    """Inventaire d'une `Aventure`, à une date de référence donnée."""
    vivantes: list[ConditionVivante] = field(default_factory=list)
    echues: list[ConditionVivante] = field(default_factory=list)
    etats: list[ConditionEtat] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)

    def rapport(self) -> dict:
        """Rapport de lecture — comptes seuls, jamais un verdict (même
        esprit que `author.rapport`/`campagne.rapport`)."""
        return {"vivantes": len(self.vivantes), "echues": len(self.echues),
                "etats": len(self.etats),
                "avertissements": len(self.avertissements)}


def extraire(aventure: Aventure, *, date_reference: date,
             date_pose: date, fichier: str = "") -> Echeancier:
    """Extrait l'échéancier d'une `Aventure` déjà construite.

    `date_reference` : date à laquelle on juge une condition échue ou non
    (échéance <= date_reference => échue, strictement postérieure => vivante).
    `date_pose` : date à laquelle le module qui porte `aventure` a été posé
    dans la campagne — sert d'ancrage aux délais (`delai` est relatif à cette
    date, jamais à `date_reference`).
    `fichier` : identifiant de la partition/du module d'origine, composé dans
    l'ancre de chaque condition (cf. docstring module).
    """
    vivantes: list[ConditionVivante] = []
    echues: list[ConditionVivante] = []
    etats: list[ConditionEtat] = []
    avertissements: list[str] = []
    for ev in aventure.events():
        dec = ev.declencheur
        typ = dec.get("type")
        valeur = dec.get("valeur", "")
        ancre = _ancre(ev, fichier)
        if typ == "etat":
            etats.append(ConditionEtat(ev.id, valeur, ancre,
                                       ev.description_md))
            continue
        if typ == "date":
            echeance = _parse_date(valeur)
        elif typ == "delai":
            jours = _parse_delai_jours(valeur)
            echeance = (date_pose + timedelta(days=jours)
                       if jours is not None else None)
        else:
            echeance = None
        if echeance is None:
            avertissements.append(
                f"evenement {ev.id}: declencheur {typ!r} valeur {valeur!r} "
                "illisible — exclu de l'échéancier, à corriger à la source")
            continue
        cond = ConditionVivante(ev.id, typ, echeance, ancre,
                                ev.description_md)
        (vivantes if echeance > date_reference else echues).append(cond)
    return Echeancier(vivantes=vivantes, echues=echues, etats=etats,
                      avertissements=avertissements)


def garder_reportage(avant: list[ConditionVivante],
                      apres: Aventure | list[Evenement],
                      patches_apres: list[Patch] | None = None
                      ) -> list[str]:
    """La GARDE de ré-émission (contrat Issue #71) : compare l'échéancier
    VIVANT d'avant re-script à l'`Aventure` (ou liste d'`Evenement`)
    re-scriptée. Retourne une liste d'erreurs — une par condition perdue,
    nommant la condition (id, type, échéance, ancre) — vide == passe.

    Un porteur dans l'après est soit le même `Evenement.id` ré-émis tel
    quel, soit un `Patch` de `patches_apres` dont `cible_id` référence la
    condition — un solde explicite n'est pas une perte (contrat Issue #71).
    Ne lève jamais, ne mute jamais (même discipline que
    `campagne.validate`/`toile.validate`) : c'est à l'appelant (le futur
    organe de réadaptation, I-371d) de décider quoi faire d'un refus."""
    evenements = apres.events() if isinstance(apres, Aventure) else apres
    ids_apres = {ev.id for ev in evenements}
    cibles_soldees = {p.cible_id for p in (patches_apres or [])}
    erreurs = []
    for cond in avant:
        if cond.porteur_id in ids_apres or cond.porteur_id in cibles_soldees:
            continue
        erreurs.append(
            f"condition vivante perdue au re-script : {cond.porteur_id} "
            f"({cond.type_declencheur}, échéance {cond.echeance.isoformat()}) "
            f"— ni ré-émise, ni soldée par Patch (ancre {cond.ancre})")
    return erreurs
