"""I-370b -- le sélecteur de matière (D-244, organe Auteur) :
coderain.selecteur.selectionner apparie une envie joueur (texte libre) à des
CANDIDATS D'ACTE (2-3 modules enchaînables, D-232) tirés d'un catalogue.
Chaque candidat doit être ANCRÉ au catalogue transmis -- un candidat sans
ancre, hors échelle, multi-univers ou qui fuite un id dans son libelle
montrable est REFUSÉ par la garde de forme (`_valider_candidat`), jamais
accepté sur la seule parole du LLM.

Fixtures 100% synthétiques (D-109) : univers fictif "sable-rouge", ids et
secrets inventés pour ce test seul -- aucun matériau de campagne réel.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coderain.selecteur import (EntreeCatalogue, CandidatActe,
                                selectionner, sortie_montrable)

# ============================================================
# Fixture synthétique -- catalogue à l'échelle module (D-232 §2)
# ============================================================

CATALOGUE = [
    EntreeCatalogue(
        id="module-puits-des-suppliques", univers="sable-rouge",
        themes=("dette-de-sang", "exil-impose"),
        personnage_sert="demande un protagoniste qui fuit une dette contractée "
                        "par un aîné ; offre l'épreuve de la rembourser",
        echelle="mini", puissance_attendue="niveaux 1-2 (5e)"),
    EntreeCatalogue(
        id="module-caravane-des-cendres", univers="sable-rouge",
        themes=("dette-de-sang", "loyaute-mise-a-lepreuve"),
        personnage_sert="demande un protagoniste prêt à choisir entre deux "
                        "loyautés ; offre la confrontation de ce choix",
        echelle="mini", puissance_attendue="niveaux 2-3 (5e)"),
    EntreeCatalogue(
        id="module-verger-noye", univers="autre-monde",
        themes=("deuil-non-fait",),
        personnage_sert="demande un protagoniste endeuillé ; offre le deuil "
                        "comme épreuve",
        echelle="mini", puissance_attendue="niveaux 1-2 (5e)"),
]
IDS_CATALOGUE = {e.id for e in CATALOGUE}

# Secrets/ids INTERNES à la fixture -- n'existent nulle part dans
# EntreeCatalogue (par construction du module) : le grep zéro-spoiler doit
# les trouver absents de toute sortie montrable, quoi que le LLM propose.
SECRETS_FIXTURE = ["le-percepteur-est-le-pere-du-heros", "PNJ-INTERNE-0042"]


class StubLLM:
    """Faux organe Auteur : renvoie EXACTEMENT le texte fourni au
    constructeur, jamais un vrai modèle (100% hors-ligne, CLAUDE.md)."""
    def __init__(self, text: str):
        self.text = text

    def complete(self, messages, **kw):
        return self.text


def _json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ---- 1) nominal : deux candidats bien formés, ancrés, un univers chacun ----
llm = StubLLM(_json({"candidats": [
    {"modules": ["module-puits-des-suppliques", "module-caravane-des-cendres"],
     "libelle": "Un héritage de dettes vous rattrape dans les sables rouges.",
     "justification": "répond à l'envie d'un poids familial à assumer"},
]}))
candidats, rejets = selectionner(
    "je veux un personnage qui porte le poids d'une dette familiale", CATALOGUE, llm)
assert rejets == [], rejets
assert len(candidats) == 1, candidats
c = candidats[0]
assert c.modules == ("module-puits-des-suppliques", "module-caravane-des-cendres")
assert "module-" not in c.libelle, c.libelle
print("1) une envie bien formée produit un candidat d'acte ancré et justifié")

# ---- 2) candidat sans ancre -> refusé avec message ----
llm = StubLLM(_json({"candidats": [
    {"modules": ["module-puits-des-suppliques", "module-invente-hors-catalogue"],
     "libelle": "Une aventure inventée.", "justification": "..."},
]}))
candidats, rejets = selectionner("peu importe l'envie", CATALOGUE, llm)
assert candidats == [], candidats
assert len(rejets) == 1 and "ancre catalogue manquante" in rejets[0]["raison"], rejets
assert "module-invente-hors-catalogue" in rejets[0]["raison"], rejets
print("2) un candidat citant un id hors catalogue est refusé, message explicite")

# ---- 3) échelle violée : module isolé (1) et hors-borne haute (4) ----
llm = StubLLM(_json({"candidats": [
    {"modules": ["module-puits-des-suppliques"],
     "libelle": "Un module seul.", "justification": "..."},
]}))
candidats, rejets = selectionner("envie", CATALOGUE, llm)
assert candidats == [] and "échelle acte violée" in rejets[0]["raison"], rejets
print("3a) un candidat à un seul module (pas un acte) est refusé")

llm = StubLLM(_json({"candidats": [
    {"modules": ["module-puits-des-suppliques", "module-caravane-des-cendres",
                 "module-verger-noye", "module-puits-des-suppliques"],
     "libelle": "Une campagne entière.", "justification": "..."},
]}))
candidats, rejets = selectionner("envie", CATALOGUE, llm)
assert candidats == [] and "échelle acte violée" in rejets[0]["raison"], rejets
print("3b) un candidat à 4 modules (mini-campagne, pas un acte) est refusé")

# ---- 4) univers mélangés dans un même acte -> refusé ----
llm = StubLLM(_json({"candidats": [
    {"modules": ["module-puits-des-suppliques", "module-verger-noye"],
     "libelle": "Un mélange d'univers.", "justification": "..."},
]}))
candidats, rejets = selectionner("envie", CATALOGUE, llm)
assert candidats == [] and "plusieurs univers" in rejets[0]["raison"], rejets
print("4) un candidat chaînant deux univers différents est refusé")

# ---- 5) libelle qui fuite un id catalogue -> refusé (zéro spoiler) ----
llm = StubLLM(_json({"candidats": [
    {"modules": ["module-puits-des-suppliques", "module-caravane-des-cendres"],
     "libelle": "Commence par module-puits-des-suppliques puis enchaîne.",
     "justification": "..."},
]}))
candidats, rejets = selectionner("envie", CATALOGUE, llm)
assert candidats == [] and "zéro spoiler" in rejets[0]["raison"], rejets
print("5) un libelle qui cite un id de catalogue tel quel est refusé")

# ---- 6) plancher d'entrée : envie vide / catalogue vide ----
candidats, rejets = selectionner("   ", CATALOGUE, StubLLM(_json({"candidats": []})))
assert candidats == [] and "envie vide" in rejets[0]["raison"], rejets
candidats, rejets = selectionner("envie", [], StubLLM(_json({"candidats": []})))
assert candidats == [] and "catalogue vide" in rejets[0]["raison"], rejets
print("6) envie vide et catalogue vide sont rejetés avant tout appel LLM")

# ---- 7) sortie LLM inexploitable -> rejet explicite, jamais une exception ----
candidats, rejets = selectionner("envie", CATALOGUE, StubLLM("pas du JSON du tout"))
assert candidats == [] and "appel LLM échoué" in rejets[0]["raison"], rejets
print("7) une sortie LLM sans JSON valide devient un rejet, pas une exception")

# ============================================================
# 8) zéro spoiler bout en bout : un grep des ids internes/secrets de la
# fixture sur la sortie montrable rend zéro, même avec plusieurs candidats
# valides mêlés à des rejets.
# ============================================================
llm = StubLLM(_json({"candidats": [
    {"modules": ["module-puits-des-suppliques", "module-caravane-des-cendres"],
     "libelle": "Un héritage de dettes vous rattrape dans les sables rouges.",
     "justification": "le-percepteur-est-le-pere-du-heros"},  # secret -- jamais montrable
    {"modules": ["module-verger-noye"], "libelle": "trop court", "justification": "x"},
]}))
candidats, rejets = selectionner(
    "un personnage qui porte une dette familiale", CATALOGUE, llm)
assert len(candidats) == 1 and len(rejets) == 1, (candidats, rejets)
montrable = sortie_montrable(candidats)
for secret in SECRETS_FIXTURE:
    assert secret not in montrable, (secret, montrable)
for cid in IDS_CATALOGUE:
    assert cid not in montrable, (cid, montrable)
print("8) grep ids internes + secrets de la fixture sur la sortie montrable : zéro")

print("\nOK -- sélecteur de matière (I-370b)")
