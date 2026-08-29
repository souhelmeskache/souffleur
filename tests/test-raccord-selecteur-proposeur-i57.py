"""I-57 -- RACCORD selecteur/proposeur : premiere soudure reelle des deux
organes (revues adversariales PR #54 et #56).

Verifie le critere de fin de l'Issue #57 :
  1. un seul CandidatActe vit dans le code -- coderain.proposeur importe le
     type reel de coderain.selecteur (plus de stub) ;
  2. un acte a modules chaines deux fois est refuse par le selecteur, message
     explicite ;
  3. chaine bout en bout : une envie synthetique passe par `selectionner`,
     le candidat retenu est ancre sous forme de Proposition via son id
     derive stable (`CandidatActe.id()`), et cette proposition est validee
     par le proposeur -- la premiere soudure reelle des deux organes.

Fixtures 100% synthetiques (D-109) : univers fictif, ids et catalogue
inventes pour ce test seul -- aucun materiau de campagne reel.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coderain.selecteur import EntreeCatalogue, CandidatActe, selectionner
from coderain.proposeur import (
    ElementPropose, EnvieJoueur, Proposition, RegistreProposeur,
    CENTRAL, SECONDAIRE, valider, valider_ancrage,
)


class StubLLM:
    """Faux organe Auteur : renvoie EXACTEMENT le texte fourni au
    constructeur, jamais un vrai modele (100% hors-ligne, CLAUDE.md)."""
    def __init__(self, text: str):
        self.text = text

    def complete(self, messages, **kw):
        return self.text


def _json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ---- 0) un seul CandidatActe dans le code : le proposeur reexporte le
# type reel du selecteur, pas un stub avec un champ id -----------------------

from coderain import proposeur as _proposeur_mod
assert _proposeur_mod.CandidatActe is CandidatActe, \
    "coderain.proposeur.CandidatActe doit etre le meme objet que " \
    "coderain.selecteur.CandidatActe -- un seul type, plus de stub"
assert not hasattr(CandidatActe, "__dataclass_fields__") or \
    "id" not in CandidatActe.__dataclass_fields__, \
    "CandidatActe ne doit porter aucun champ 'id' saisi a la main"
print("0) coderain.proposeur importe le CandidatActe reel du selecteur (plus de stub)")

# ---- 1) unicite des modules dans un candidat d'acte : un acte qui chaine
# deux fois le meme module est refuse avec message explicite -----------------

CATALOGUE = [
    EntreeCatalogue(
        id="module-atelier-rouille", univers="rouages-brises",
        themes=("mecanisme-fige",),
        personnage_sert="demande un protagoniste bricoleur",
        echelle="mini", puissance_attendue="niveaux 1-2 (5e)"),
    EntreeCatalogue(
        id="module-grue-effondree", univers="rouages-brises",
        themes=("effondrement",),
        personnage_sert="demande un protagoniste courageux",
        echelle="mini", puissance_attendue="niveaux 2-3 (5e)"),
]

llm_doublon = StubLLM(_json({"candidats": [
    {"modules": ["module-atelier-rouille", "module-atelier-rouille"],
     "libelle": "Un atelier revisite deux fois.", "justification": "..."},
]}))
candidats, rejets = selectionner("envie de bricolage", CATALOGUE, llm_doublon)
assert candidats == [], candidats
assert len(rejets) == 1, rejets
assert "chaîné plusieurs fois" in rejets[0]["raison"], rejets
assert "module-atelier-rouille" in rejets[0]["raison"], rejets
print("1) un acte qui chaîne deux fois le même module est refusé, message explicite")

# ---- 2) chaîne bout en bout : envie -> selectionner -> Proposition ancrée
# sur le candidat retenu (via son id dérivé) -> validée par le proposeur -----

llm_nominal = StubLLM(_json({"candidats": [
    {"modules": ["module-atelier-rouille", "module-grue-effondree"],
     "libelle": "Une grue effondrée bloque l'atelier à remettre en état.",
     "justification": "répond à l'envie de bricolage sous contrainte"},
]}))
candidats, rejets = selectionner(
    "je veux un personnage bricoleur confronté à une machine cassée",
    CATALOGUE, llm_nominal)
assert rejets == [], rejets
assert len(candidats) == 1, candidats
candidat_retenu = candidats[0]

proposition = Proposition(
    id="prop-1",
    personnage=[
        ElementPropose(label="role", texte="Un mécanicien opiniâtre",
                       ancre_source=candidat_retenu.id(), portee=CENTRAL),
    ],
    contrat=[
        ElementPropose(label="clause_centrale",
                       texte="Redresser la grue effondrée pour rouvrir l'atelier",
                       ancre_source=candidat_retenu.id(), portee=CENTRAL),
    ],
)
assert valider(proposition) == [], valider(proposition)
assert valider_ancrage(proposition, candidats, []) == [], \
    "la proposition doit s'ancrer sur le candidat retenu via son id dérivé"

registre = RegistreProposeur()
registre.proposer(proposition)
assert registre.derniere() is proposition
print("2) chaîne bout en bout : envie -> candidat d'acte retenu -> proposition "
      "ancrée (id dérivé) -> validée par le proposeur -- soudure des deux organes")

print("\nOK -- raccord sélecteur/proposeur (I-57)")
