"""Issue #139 -- le RETOUR 2 (D-262/D-128) : contrôle de conformité
texte-contre-texte, AVANT le jeu. `coderain.retour2.retour2` fait juger par
le LLM (mocké, 100% hors-ligne) si le TEXTE écrit remplit les OBJECTIFS
transmis par l'étage au-dessus -- chaque verdict doit être ANCRÉ (objectif
transmis, justification non vide, extraits trouvés verbatim dans le texte) :
un verdict qui ne l'est pas est REFUSÉ par la garde de forme, jamais accepté
sur la seule parole du LLM. AUCUN score agrégé nulle part (D-131/D-118).

Fixtures 100% synthétiques (D-109) : module-épisode et objectifs inventés
pour ce test seul -- aucun matériau de campagne réel.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coderain.retour2 import Objectif, retour2

# ============================================================
# Fixture synthétique -- un module-épisode et ses objectifs d'acte
# ============================================================

TEXTE = (
    "Le protagoniste arrive au campement des cendres au crépuscule. Un vieil "
    "homme lui tend un carnet couvert de suie et dit : \"ta dette n'est pas "
    "la tienne, mais tu la portes quand même.\" Plus loin, une caravane "
    "brûlée bloque la route ; il faut choisir entre poursuivre les pillards "
    "ou soigner les blessés laissés derrière."
)

OBJECTIFS = [
    Objectif(id="obj-1", texte="le module doit poser le poids d'une dette "
             "héritée, pas choisie par le personnage"),
    Objectif(id="obj-2", texte="le module doit offrir un choix moral concret "
             "au joueur, avec un coût des deux côtés"),
    Objectif(id="obj-3", texte="le module doit introduire un allié récurrent "
             "destiné à revenir dans l'acte suivant"),
]
IDS_OBJECTIFS = {o.id for o in OBJECTIFS}


class StubLLM:
    """Faux organe : renvoie EXACTEMENT le texte fourni au constructeur,
    jamais un vrai modèle (100% hors-ligne, CLAUDE.md)."""
    def __init__(self, text: str):
        self.text = text

    def complete(self, messages, **kw):
        return self.text


def _json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ---- 1) nominal : verdicts bien formés, ancrés, extraits verbatim ----
llm = StubLLM(_json({"verdicts": [
    {"objectif_id": "obj-1", "verdict": "conforme",
     "justification": "la dette est explicitement héritée, pas choisie",
     "extraits": ["ta dette n'est pas la tienne, mais tu la portes quand même"]},
    {"objectif_id": "obj-2", "verdict": "conforme",
     "justification": "le choix pillards/blessés porte un coût des deux côtés",
     "extraits": ["poursuivre les pillards ou soigner les blessés laissés derrière"]},
    {"objectif_id": "obj-3", "verdict": "absent",
     "justification": "aucun allié récurrent n'est introduit dans ce texte",
     "extraits": []},
]}))
rapport = retour2(OBJECTIFS, TEXTE, llm)
assert rapport.rejets == (), rapport.rejets
assert len(rapport.verdicts) == 3, rapport.verdicts
assert rapport.conforme_total is False, rapport
assert len(rapport.ecarts) == 1 and rapport.ecarts[0]["id"] == "obj-3", rapport.ecarts
print("1) verdicts bien formés acceptés, écart listé pour l'objectif absent, zéro score")

# ---- 2) tous conformes -> conforme_total True, zéro écart ----
llm = StubLLM(_json({"verdicts": [
    {"objectif_id": "obj-1", "verdict": "conforme", "justification": "ok",
     "extraits": ["ta dette n'est pas la tienne"]},
    {"objectif_id": "obj-2", "verdict": "conforme", "justification": "ok",
     "extraits": ["poursuivre les pillards"]},
    {"objectif_id": "obj-3", "verdict": "conforme", "justification": "ok",
     "extraits": ["Un vieil homme"]},
]}))
rapport = retour2(OBJECTIFS, TEXTE, llm)
assert rapport.rejets == (), rapport.rejets
assert rapport.conforme_total is True, rapport
assert rapport.ecarts == (), rapport.ecarts
print("2) tous les objectifs conformes -> conforme_total True, écarts vide")

# ---- 3) verdict sans justification -> refusé ----
llm = StubLLM(_json({"verdicts": [
    {"objectif_id": "obj-1", "verdict": "conforme", "justification": "",
     "extraits": []},
]}))
rapport = retour2(OBJECTIFS, TEXTE, llm)
assert rapport.verdicts == (), rapport.verdicts
assert len(rapport.rejets) == 1 and "sans justification" in rapport.rejets[0]["raison"], rapport.rejets
print("3) un verdict sans justification est refusé, message explicite")

# ---- 4) objectif inventé (non transmis) -> refusé ----
llm = StubLLM(_json({"verdicts": [
    {"objectif_id": "obj-invente-hors-liste", "verdict": "conforme",
     "justification": "...", "extraits": []},
]}))
rapport = retour2(OBJECTIFS, TEXTE, llm)
assert rapport.verdicts == (), rapport.verdicts
assert len(rapport.rejets) == 1 and "objectif non transmis" in rapport.rejets[0]["raison"], rapport.rejets
assert "obj-invente-hors-liste" in rapport.rejets[0]["raison"], rapport.rejets
print("4) un verdict citant un objectif non transmis est refusé")

# ---- 5) extrait introuvable dans le texte -> invalide le verdict ----
llm = StubLLM(_json({"verdicts": [
    {"objectif_id": "obj-1", "verdict": "conforme",
     "justification": "plausible mais mal citée",
     "extraits": ["une phrase qui n'existe nulle part dans le texte"]},
]}))
rapport = retour2(OBJECTIFS, TEXTE, llm)
assert rapport.verdicts == (), rapport.verdicts
assert len(rapport.rejets) == 1 and "extrait introuvable" in rapport.rejets[0]["raison"], rapport.rejets
print("5) un verdict citant un extrait introuvable dans le texte est invalidé")

# ---- 5b) extrait présent mais avec espaces/retours-ligne différents -> accepté (tolérance) ----
llm = StubLLM(_json({"verdicts": [
    {"objectif_id": "obj-1", "verdict": "conforme", "justification": "ok",
     "extraits": ["ta dette n'est   pas\nla tienne"]},
]}))
rapport = retour2(OBJECTIFS, TEXTE, llm)
assert rapport.rejets == (), rapport.rejets
assert len(rapport.verdicts) == 1, rapport.verdicts
print("5b) un extrait qui diffère seulement par les espaces/retours-ligne est accepté")

# ---- 6) verdict hors vocabulaire fermé (pas de note chiffrée) -> refusé ----
llm = StubLLM(_json({"verdicts": [
    {"objectif_id": "obj-1", "verdict": "8/10", "justification": "...",
     "extraits": []},
]}))
rapport = retour2(OBJECTIFS, TEXTE, llm)
assert rapport.verdicts == (), rapport.verdicts
assert len(rapport.rejets) == 1 and "hors vocabulaire fermé" in rapport.rejets[0]["raison"], rapport.rejets
print("6) un verdict hors du vocabulaire fermé (ex. une note chiffrée) est refusé")

# ---- 7) plancher d'entrée : texte vide / objectifs vide ----
rapport = retour2(OBJECTIFS, "   ", StubLLM(_json({"verdicts": []})))
assert rapport.verdicts == () and "texte vide" in rapport.rejets[0]["raison"], rapport
rapport = retour2([], TEXTE, StubLLM(_json({"verdicts": []})))
assert rapport.verdicts == () and "objectifs vide" in rapport.rejets[0]["raison"], rapport
print("7) texte vide et objectifs vide sont rejetés avant tout appel LLM")

# ---- 8) sortie LLM inexploitable -> rejet explicite, jamais une exception ----
rapport = retour2(OBJECTIFS, TEXTE, StubLLM("pas du JSON du tout"))
assert rapport.verdicts == () and "appel LLM échoué" in rapport.rejets[0]["raison"], rapport
print("8) une sortie LLM sans JSON valide devient un rejet, pas une exception")

# ---- 9) objectif jamais couvert par la sortie LLM -> écart "non-couvert" ----
llm = StubLLM(_json({"verdicts": [
    {"objectif_id": "obj-1", "verdict": "conforme", "justification": "ok",
     "extraits": ["ta dette n'est pas la tienne"]},
]}))
rapport = retour2(OBJECTIFS, TEXTE, llm)
assert rapport.conforme_total is False, rapport
ids_ecarts = {e["id"] for e in rapport.ecarts}
assert ids_ecarts == {"obj-2", "obj-3"}, rapport.ecarts
assert all(e["verdict"] == "non-couvert" for e in rapport.ecarts), rapport.ecarts
print("9) un objectif jamais jugé par le LLM devient un écart 'non-couvert', jamais silencieux")

# ============================================================
# 10) formes déclarées (D-261) -- correspondance déclaration/texte
# ============================================================
FORMES_DECLAREES = [
    {"id": "propp-XI-depart", "justification": "le protagoniste quitte le "
     "campement pour poursuivre les pillards"},
]

llm = StubLLM(_json({
    "verdicts": [
        {"objectif_id": "obj-1", "verdict": "conforme", "justification": "ok",
         "extraits": ["ta dette n'est pas la tienne"]},
        {"objectif_id": "obj-2", "verdict": "conforme", "justification": "ok",
         "extraits": ["poursuivre les pillards"]},
        {"objectif_id": "obj-3", "verdict": "absent", "justification": "ok",
         "extraits": []},
    ],
    "verdicts_formes": [
        {"forme_id": "propp-XI-depart", "correspond": "conforme",
         "justification": "le départ est bien présent",
         "extraits": ["poursuivre les pillards"]},
    ],
}))
rapport = retour2(OBJECTIFS, TEXTE, llm, formes_declarees=FORMES_DECLAREES)
assert rapport.rejets == (), rapport.rejets
assert len(rapport.verdicts_formes) == 1, rapport.verdicts_formes
assert rapport.verdicts_formes[0].correspond == "conforme"
print("10) une forme déclarée correspondante est validée aux côtés des objectifs")

# ---- 11) forme non déclarée citée dans un verdict de forme -> refusée ----
llm = StubLLM(_json({
    "verdicts": [
        {"objectif_id": "obj-1", "verdict": "conforme", "justification": "ok",
         "extraits": ["ta dette n'est pas la tienne"]},
    ],
    "verdicts_formes": [
        {"forme_id": "forme-jamais-declaree", "correspond": "conforme",
         "justification": "...", "extraits": []},
    ],
}))
rapport = retour2(OBJECTIFS, TEXTE, llm, formes_declarees=FORMES_DECLAREES)
assert rapport.verdicts_formes == (), rapport.verdicts_formes
assert any("forme non déclarée" in r["raison"] for r in rapport.rejets), rapport.rejets
print("11) un verdict citant une forme jamais déclarée est refusé")

print("\nOK -- retour 2 : conformité texte contre texte (issue #139)")
