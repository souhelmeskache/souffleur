"""Le RETOUR 2 — conformité texte contre texte, AVANT le jeu (D-262/D-128,
issue #139).

Le triple retour (décision vault `MRPG-D-128`) distingue trois contrôles sur
ce que l'Auteur écrit. Le retour 2 est le plus important : le texte écrit
remplit-il les objectifs que l'étage au-dessus lui donne ? C'est un contrôle
de CONFORMITÉ, pas d'effet — il a lieu à l'écriture, avant que rien ne se
joue, donc il échappe à tous les biais (pas de confabulation : on compare
DEUX textes, dont l'un a été écrit par l'étage du dessus).

Même pattern que `selecteur.py`/`formes.py` (le LLM juge, le code pose le
contrat et la garde de forme) :

- **Entrée** : `objectifs` (le texte de l'étage au-dessus, un par un — id +
  texte) · `texte` (le module-épisode écrit par l'Auteur) · optionnellement
  `formes_declarees` (les formes D-261 déclarées par l'écriture — mêmes
  dicts `{id, justification}` que `formes.valider_declaration` produit).
- **Le jugement LLM** (`emit_json_ex`, même seam que `selecteur.py`) : pour
  CHAQUE objectif transmis, un verdict {objectif_id, verdict, justification,
  extraits} — les `extraits` citent le passage du texte qui fonde le
  verdict. Si `formes_declarees` est fourni, un verdict de correspondance
  par forme déclarée (la déclaration correspond-elle à ce que le texte fait
  réellement).
- **La garde de forme (code)** : un verdict sans justification est refusé ·
  un verdict citant un objectif (ou une forme) non transmis est refusé · un
  extrait introuvable dans le texte (inclusion de sous-chaîne, tolérance
  espaces) invalide le verdict concerné — rejets motivés, jamais silencieux
  (même esprit que `validator.rejection_text`).
- **La sortie** : `RapportConformite` — verdicts validés, rejets, synthèse
  {conforme_total, ecarts}. ⛔ AUCUN score agrégé, aucune note chiffrée
  (D-131/D-118) : la liste des écarts, l'Auteur (ou Souhel) tranche.

Module autonome (I-... #139) : aucun import du moteur de jeu (`engine.py`),
aucun câblage dans un organe existant — le futur organe d'écriture est son
appelant nommé.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .llm import emit_json_ex

# Vocabulaire de verdict fermé — jamais une note chiffrée (D-131/D-118).
VERDICTS_VALIDES = ("conforme", "non-conforme", "absent")
CORRESPONDANCES_VALIDES = ("conforme", "non-conforme")


@dataclass(frozen=True)
class Objectif:
    """Un objectif transmis par l'étage au-dessus — texte libre, jamais un
    champ structuré inventé par ce module (l'objet ACTE, hors périmètre de
    cette lane, arrive plus tard ; ici les objectifs arrivent en TEXTE)."""
    id: str
    texte: str

    def to_prompt_dict(self) -> dict:
        return {"id": self.id, "texte": self.texte}


@dataclass(frozen=True)
class VerdictConformite:
    """Un verdict de conformité, ANCRÉ : `objectif_id` existe parmi les
    objectifs transmis, `extraits` sont tous trouvés (sous-chaîne, tolérance
    espaces) dans le texte jugé — garanti par `_valider_verdict`, jamais
    accepté sur la parole du LLM."""
    objectif_id: str
    verdict: str
    justification: str
    extraits: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"objectif_id": self.objectif_id, "verdict": self.verdict,
                "justification": self.justification,
                "extraits": list(self.extraits)}


@dataclass(frozen=True)
class VerdictForme:
    """Un verdict de correspondance déclaration/texte pour une forme D-261
    déjà déclarée (amendement 2) — même garde d'ancrage que
    `VerdictConformite`."""
    forme_id: str
    correspond: str
    justification: str
    extraits: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"forme_id": self.forme_id, "correspond": self.correspond,
                "justification": self.justification,
                "extraits": list(self.extraits)}


@dataclass(frozen=True)
class RapportConformite:
    """La sortie du retour 2 — verdicts validés, rejets motivés, synthèse.
    ⛔ AUCUN score agrégé, aucune note chiffrée (D-131/D-118) : `ecarts` est
    une LISTE d'écarts nommés, jamais un chiffre — l'Auteur (ou Souhel)
    tranche sur cette liste, pas sur un score."""
    verdicts: tuple[VerdictConformite, ...]
    verdicts_formes: tuple[VerdictForme, ...]
    rejets: tuple[dict, ...]
    conforme_total: bool
    ecarts: tuple[dict, ...]

    def to_dict(self) -> dict:
        return {
            "verdicts": [v.to_dict() for v in self.verdicts],
            "verdicts_formes": [v.to_dict() for v in self.verdicts_formes],
            "rejets": list(self.rejets),
            "conforme_total": self.conforme_total,
            "ecarts": list(self.ecarts),
        }


RETOUR2_SYS = """\
You are the RETOUR 2, a compliance judge (not a play-effect judge). You are \
given OBJECTIFS (goals stated by the layer above: act objective, targeted \
milestones, régime requirements — free text, one per id) and a TEXTE (an \
episode-module written by an Author). Your job is a TEXT-VS-TEXT compliance \
check, before anything is played — never invent effects, never speculate \
about how play might go.

For EVERY objectif given to you, return ONE verdict: does the TEXTE fulfill \
it? "conforme" (fulfilled), "non-conforme" (addressed but falls short), or \
"absent" (the text never addresses it at all). Ground every verdict in a \
"justification" and, when the text does address the objectif, "extraits": \
one or more short passages QUOTED VERBATIM from the TEXTE (never \
paraphrased, never invented) that support your verdict.

If FORMES DÉCLARÉES are given (forms the Author claims to have used), judge \
each one separately: does the TEXTE actually do what the declaration \
claims? "conforme" or "non-conforme", with justification and verbatim \
extraits the same way.

Never invent an objectif_id or a forme_id — use only the ids given to you. \
Never assign a numeric score or grade — only the fixed verdict vocabulary.

Return ONLY a JSON object:
{"verdicts": [{"objectif_id": "...", "verdict": "conforme|non-conforme|absent",
               "justification": "...", "extraits": ["..."]}],
 "verdicts_formes": [{"forme_id": "...", "correspond": "conforme|non-conforme",
                       "justification": "...", "extraits": ["..."]}]}
"""


def _normaliser_espaces(s: str) -> str:
    """Tolérance espaces pour la vérification par inclusion de sous-chaîne :
    espaces/retours-ligne multiples réduits à un seul espace, bords coupés."""
    return re.sub(r"\s+", " ", s).strip()


def _extrait_present(extrait: str, texte_normalise: str) -> bool:
    return _normaliser_espaces(extrait) in texte_normalise


def _payload(objectifs: list[Objectif], texte: str,
             formes_declarees: list[dict] | None) -> str:
    parts = ["OBJECTIFS TRANSMIS:\n"
             + json.dumps([o.to_prompt_dict() for o in objectifs],
                           ensure_ascii=False),
             "\nTEXTE À JUGER:\n" + texte.strip()]
    if formes_declarees:
        parts.append("\nFORMES DÉCLARÉES PAR L'ÉCRITURE:\n"
                      + json.dumps(formes_declarees, ensure_ascii=False))
    return "\n".join(parts)


def _valider_verdict(raw: dict, ids_objectifs: set[str],
                      texte_normalise: str) -> tuple[VerdictConformite | None, str | None]:
    """Garde de forme sur un verdict d'objectif — jamais accepté sur la
    parole du LLM. Retourne (verdict, None) si valide, sinon (None, raison)."""
    if not isinstance(raw, dict):
        return None, "verdict n'est pas un objet"
    objectif_id = str(raw.get("objectif_id", "")).strip()
    if not objectif_id:
        return None, "verdict sans objectif_id"
    if objectif_id not in ids_objectifs:
        return None, f"verdict cite un objectif non transmis : {objectif_id}"
    verdict = str(raw.get("verdict", "")).strip()
    if verdict not in VERDICTS_VALIDES:
        return None, (f"verdict de {objectif_id} hors vocabulaire fermé : "
                      f"{verdict!r} (attendu {VERDICTS_VALIDES})")
    justification = str(raw.get("justification", "")).strip()
    if not justification:
        return None, f"verdict de {objectif_id} sans justification"
    extraits_raw = raw.get("extraits", [])
    if not isinstance(extraits_raw, list):
        return None, f"verdict de {objectif_id} : champ 'extraits' n'est pas une liste"
    extraits = tuple(str(e).strip() for e in extraits_raw if str(e).strip())
    for extrait in extraits:
        if not _extrait_present(extrait, texte_normalise):
            return None, (f"verdict de {objectif_id} : extrait introuvable "
                          f"dans le texte : {extrait!r}")
    return VerdictConformite(objectif_id, verdict, justification, extraits), None


def _valider_verdict_forme(raw: dict, ids_formes: set[str],
                           texte_normalise: str) -> tuple[VerdictForme | None, str | None]:
    """Même garde que `_valider_verdict`, pour une forme déclarée."""
    if not isinstance(raw, dict):
        return None, "verdict de forme n'est pas un objet"
    forme_id = str(raw.get("forme_id", "")).strip()
    if not forme_id:
        return None, "verdict de forme sans forme_id"
    if forme_id not in ids_formes:
        return None, f"verdict cite une forme non déclarée : {forme_id}"
    correspond = str(raw.get("correspond", "")).strip()
    if correspond not in CORRESPONDANCES_VALIDES:
        return None, (f"verdict de forme {forme_id} hors vocabulaire fermé : "
                      f"{correspond!r} (attendu {CORRESPONDANCES_VALIDES})")
    justification = str(raw.get("justification", "")).strip()
    if not justification:
        return None, f"verdict de forme {forme_id} sans justification"
    extraits_raw = raw.get("extraits", [])
    if not isinstance(extraits_raw, list):
        return None, f"verdict de forme {forme_id} : champ 'extraits' n'est pas une liste"
    extraits = tuple(str(e).strip() for e in extraits_raw if str(e).strip())
    for extrait in extraits:
        if not _extrait_present(extrait, texte_normalise):
            return None, (f"verdict de forme {forme_id} : extrait introuvable "
                          f"dans le texte : {extrait!r}")
    return VerdictForme(forme_id, correspond, justification, extraits), None


def _synthese(objectifs: list[Objectif], verdicts: list[VerdictConformite],
              formes_declarees: list[dict] | None,
              verdicts_formes: list[VerdictForme]) -> tuple[bool, list[dict]]:
    """Aucun score : une liste d'écarts nommés (D-131/D-118). Un objectif
    sans verdict validé (absent de la sortie LLM ou rejeté par la garde de
    forme) est lui aussi un écart — jamais silencieusement ignoré."""
    par_objectif = {v.objectif_id: v for v in verdicts}
    ecarts: list[dict] = []
    for obj in objectifs:
        v = par_objectif.get(obj.id)
        if v is None:
            ecarts.append({"type": "objectif", "id": obj.id,
                           "verdict": "non-couvert",
                           "justification": "aucun verdict validé pour cet "
                           "objectif (absent de la sortie LLM ou rejeté par "
                           "la garde de forme)"})
        elif v.verdict != "conforme":
            ecarts.append({"type": "objectif", "id": obj.id,
                           "verdict": v.verdict,
                           "justification": v.justification})

    if formes_declarees:
        par_forme = {v.forme_id: v for v in verdicts_formes}
        for decl in formes_declarees:
            forme_id = str(decl.get("id", "")).strip()
            v = par_forme.get(forme_id)
            if v is None:
                ecarts.append({"type": "forme", "id": forme_id,
                               "verdict": "non-couvert",
                               "justification": "aucun verdict de "
                               "correspondance validé pour cette forme "
                               "déclarée"})
            elif v.correspond != "conforme":
                ecarts.append({"type": "forme", "id": forme_id,
                               "verdict": v.correspond,
                               "justification": v.justification})

    return len(ecarts) == 0, ecarts


def retour2(objectifs: list[Objectif], texte: str, llm,
           *, formes_declarees: list[dict] | None = None,
           retry: int = 1) -> RapportConformite:
    """Le retour 2 (D-262/D-128) : conformité texte contre texte, AVANT le
    jeu. Fait porter le jugement au LLM (`emit_json_ex`, même seam que
    `selecteur.py`) puis applique la garde de forme (jamais un verdict
    accepté sur parole). Ne fait AUCUN import du moteur de jeu — module
    autonome, son appelant est le futur organe d'écriture (issue suivante)."""
    texte = (texte or "").strip()
    if not texte:
        return RapportConformite((), (), ({"verdict": None,
                                           "raison": "texte vide"},), False, ())
    if not objectifs:
        return RapportConformite((), (), ({"verdict": None,
                                           "raison": "objectifs vide"},), False, ())

    ids_objectifs = {o.id for o in objectifs}
    ids_formes = {str(d.get("id", "")).strip() for d in (formes_declarees or [])}
    texte_normalise = _normaliser_espaces(texte)

    obj, err = emit_json_ex(llm, RETOUR2_SYS,
                            _payload(objectifs, texte, formes_declarees),
                            retry=retry)
    if obj is None:
        return RapportConformite((), (), ({"verdict": None,
                                           "raison": f"appel LLM échoué : {err}"},),
                                 False, ())

    bruts = obj.get("verdicts")
    if not isinstance(bruts, list):
        return RapportConformite((), (), ({"verdict": None,
                                           "raison": "sortie LLM sans champ "
                                           "'verdicts' (liste)"},), False, ())

    verdicts: list[VerdictConformite] = []
    rejets: list[dict] = []
    for raw in bruts:
        v, raison = _valider_verdict(raw, ids_objectifs, texte_normalise)
        if v is not None:
            verdicts.append(v)
        else:
            rejets.append({"verdict": raw, "raison": raison})

    verdicts_formes: list[VerdictForme] = []
    if formes_declarees:
        bruts_formes = obj.get("verdicts_formes")
        if not isinstance(bruts_formes, list):
            rejets.append({"verdict": None, "raison": "sortie LLM sans champ "
                           "'verdicts_formes' (liste) alors que des formes "
                           "étaient déclarées"})
        else:
            for raw in bruts_formes:
                v, raison = _valider_verdict_forme(raw, ids_formes, texte_normalise)
                if v is not None:
                    verdicts_formes.append(v)
                else:
                    rejets.append({"verdict": raw, "raison": raison})

    conforme_total, ecarts = _synthese(objectifs, verdicts, formes_declarees,
                                       verdicts_formes)
    return RapportConformite(tuple(verdicts), tuple(verdicts_formes),
                             tuple(rejets), conforme_total, tuple(ecarts))
