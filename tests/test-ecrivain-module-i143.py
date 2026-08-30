"""Issue #143 -- l'ORGANE D'ÉCRITURE de module (D-262) : la chaîne
cadre -> régime -> formes -> écriture -> retour 2. `coderain.ecrivain_module`
orchestre en CODE (`ecrire_module`) trois maillons déjà mergés sur main
(`acte.bloc_cadre`, `formes.valider_declaration`, `retour2.retour2`) autour
d'un unique appel d'écriture LLM (mocké, 100% hors-ligne, D-109) : le module
proposé passe la garde de formes PUIS le retour 2 sur les objectifs du
régime -- UNE re-demande corrective max sur rejet, sinon échec rapporté avec
les rejets, jamais silencieux.

Fixtures 100% synthétiques (D-109) : acte, vécu et modules-épisodes inventés
pour ce test seul -- aucun matériau de campagne réel. Le vocabulaire de
formes (`catalogue/formes/*.json`) est chargé tel quel : public, versionné
dans ce repo, pas un secret de campagne (même choix que test-formes-d261.py).
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coderain.acte import Acte, Jalon, Raccord
from coderain.ecrivain_module import (REGIMES, _bloc_regime, _objectifs_regime,
                                      _prompt_ecriture, ecrire_module)
from coderain.formes import charger_vocabulaire
from coderain.memory import MemoryStore

VOCAB = charger_vocabulaire()

# ---- fixture synthétique -- un acte à trois lectures --------------------
ACTE = Acte(
    id="acte-fabrique", titre="Acte fabriqué -- la dette des cendres",
    statut="ouvert",
    objectif_md="État visé : la dette des cendres est soldée, le campement "
               "tient encore debout.",
    jalons=[
        Jalon(id="jalon-un", statut="vécu",
             intention_md="Le carnet de suie est remis au protagoniste."),
        Jalon(id="jalon-deux", statut="pas-vécu",
             intention_md="Le protagoniste affronte le créancier fabriqué."),
        Jalon(id="jalon-trois", statut="pas-vécu",
             intention_md="La caravane brûlée est reconstruite ou abandonnée."),
    ],
    raccord=Raccord(module_id="module-fabrique-suivant",
                    conditions_entree_md="La dette est soldée ET le "
                    "campement tient encore."),
)

story_dir = tempfile.mkdtemp(prefix="ecrivain-module-store-")
STORE = MemoryStore(story_dir)

MODULE_MD = (
    "## Scène -- le campement des cendres\nUn vieil homme tend un carnet "
    "couvert de suie au protagoniste et dit : \"ta dette n'est pas la "
    "tienne, mais tu la portes quand même.\" Le créancier fabriqué attend "
    "au bout de la route, disposé à négocier ou à se battre."
)
NOTE_MD = ("J'ai choisi de faire porter la dette par un tiers pour garder "
          "le protagoniste dans un choix moral, pas une simple vengeance.")


class StubLLM:
    """Faux organe : une file de réponses JSON, une par appel `.complete`,
    consommées dans l'ordre -- une réponse de trop demandée lève une erreur
    explicite (garantit qu'AUCUN appel supplémentaire n'est fait, 100%
    hors-ligne, D-109)."""
    def __init__(self, reponses: list[dict]):
        self._file = list(reponses)
        self.appels = 0

    def complete(self, messages, **kw):
        self.appels += 1
        if not self._file:
            raise AssertionError("appel LLM inattendu -- file de réponses épuisée "
                                 "(re-demande en boucle ?)")
        return json.dumps(self._file.pop(0), ensure_ascii=False)


def _verdict_conforme(objectif_id: str, extrait: str) -> dict:
    return {"objectif_id": objectif_id, "verdict": "conforme",
            "justification": "ok", "extraits": [extrait]}


def _verdict_forme_conforme(forme_id: str, extrait: str) -> dict:
    return {"forme_id": forme_id, "correspond": "conforme",
            "justification": "ok", "extraits": [extrait]}


ECRITURE_OK = {
    "module_md": MODULE_MD,
    "declaration_formes": [{"id": "propp-08",
                            "justification": "le méfait porte la dette "
                            "héritée que le protagoniste traîne"}],
    "note_intention_md": NOTE_MD,
}

# ============================================================
# 1) régime pont -- module accepté au premier tour
# ============================================================
llm = StubLLM([
    ECRITURE_OK,
    {"verdicts": [_verdict_conforme("raccord", "ta dette n'est pas la tienne")],
     "verdicts_formes": [_verdict_forme_conforme("propp-08",
                         "ta dette n'est pas la tienne")]},
])
rapport = ecrire_module(ACTE, "pont", STORE, llm)
assert rapport.statut == "pret", rapport.to_dict()
assert rapport.module_md == MODULE_MD
assert rapport.note_intention_md == NOTE_MD
assert rapport.formes == ({"id": "propp-08",
                          "justification": ECRITURE_OK["declaration_formes"][0]["justification"]},)
assert rapport.rapport_conformite is not None and rapport.rapport_conformite.conforme_total
assert rapport.rejets == ()
assert llm.appels == 2, llm.appels
print("1) régime pont : module accepté au premier tour, statut 'pret'")

# ============================================================
# 2) déclaration de formes invalide -> re-demande puis échec propre
# ============================================================
ECRITURE_FORME_INVALIDE = {
    "module_md": MODULE_MD,
    "declaration_formes": [{"id": "forme-hors-vocabulaire",
                            "justification": "peu importe"}],
    "note_intention_md": NOTE_MD,
}
llm = StubLLM([ECRITURE_FORME_INVALIDE, ECRITURE_FORME_INVALIDE])
rapport = ecrire_module(ACTE, "pont", STORE, llm)
assert rapport.statut == "echec", rapport.to_dict()
assert rapport.rapport_conformite is None
assert any("hors vocabulaire" in r.get("raison", "") for r in rapport.rejets), rapport.rejets
assert llm.appels == 2, llm.appels  # 1 tentative + 1 re-demande, jamais plus
print("2) déclaration de formes invalide -> une re-demande puis échec propre, motivé")

# ============================================================
# 3) retour 2 non conforme au premier tour -> re-demande corrective
#    transmise avec les rejets, module conforme au second tour -> 'pret'
# ============================================================
llm = StubLLM([
    ECRITURE_OK,
    {"verdicts": [{"objectif_id": "raccord", "verdict": "non-conforme",
                  "justification": "le raccord n'est pas assez servi",
                  "extraits": ["ta dette n'est pas la tienne"]}],
     "verdicts_formes": [_verdict_forme_conforme("propp-08",
                         "ta dette n'est pas la tienne")]},
    ECRITURE_OK,
    {"verdicts": [_verdict_conforme("raccord", "ta dette n'est pas la tienne")],
     "verdicts_formes": [_verdict_forme_conforme("propp-08",
                         "ta dette n'est pas la tienne")]},
])
rapport = ecrire_module(ACTE, "pont", STORE, llm)
assert rapport.statut == "pret", rapport.to_dict()
assert llm.appels == 4, llm.appels
print("3) retour 2 non conforme -> re-demande corrective transmise avec les rejets, "
      "puis 'pret'")

# ============================================================
# 4) retour 2 non conforme aux DEUX tours -> échec propre, rejets transmis,
#    aucune re-demande en boucle (1 max -- StubLLM lèverait sur un 5e appel)
# ============================================================
verdict_non_conforme = {
    "verdicts": [{"objectif_id": "raccord", "verdict": "non-conforme",
                 "justification": "toujours pas assez servi",
                 "extraits": ["ta dette n'est pas la tienne"]}],
    "verdicts_formes": [_verdict_forme_conforme("propp-08",
                        "ta dette n'est pas la tienne")],
}
llm = StubLLM([ECRITURE_OK, verdict_non_conforme, ECRITURE_OK, verdict_non_conforme])
rapport = ecrire_module(ACTE, "pont", STORE, llm)
assert rapport.statut == "echec", rapport.to_dict()
assert rapport.rapport_conformite is not None
assert any(e.get("id") == "raccord" for e in rapport.rejets), rapport.rejets
assert llm.appels == 4, llm.appels
print("4) retour 2 non conforme aux deux tours -> échec propre, rejets transmis, "
      "aucune re-demande en boucle")

# ============================================================
# 5) régime rattrapage -- un objectif par jalon pas-vécu, formulé en texte
#    depuis l'acte (jamais un champ structuré inventé par le LLM)
# ============================================================
objectifs_rattrapage = _objectifs_regime(ACTE, "rattrapage")
assert {o.id for o in objectifs_rattrapage} == {"jalon-jalon-deux", "jalon-jalon-trois"}
assert all("créancier fabriqué" in o.texte or "caravane brûlée" in o.texte
          for o in objectifs_rattrapage)
print("5) régime rattrapage : un objectif par jalon pas-vécu, ancré à l'acte")

# ---- 5b) régime aiguillage -- un objectif ancré à l'objectif de l'acte ----
objectifs_aiguillage = _objectifs_regime(ACTE, "aiguillage")
assert len(objectifs_aiguillage) == 1
assert "dette des cendres" in objectifs_aiguillage[0].texte
assert "révélations" in objectifs_aiguillage[0].texte
print("5b) régime aiguillage : objectif unique, agendas jamais révélations")

# ---- 5c) régime pont -- un objectif ancré au raccord de l'acte ----
objectifs_pont = _objectifs_regime(ACTE, "pont")
assert len(objectifs_pont) == 1 and objectifs_pont[0].id == "raccord"
assert "module-fabrique-suivant" in objectifs_pont[0].texte
print("5c) régime pont : objectif unique ancré au module de raccord")

# ============================================================
# 6) régime inconnu -> échec immédiat, motivé, zéro appel LLM
# ============================================================
llm = StubLLM([])
rapport = ecrire_module(ACTE, "regime-invente", STORE, llm)
assert rapport.statut == "echec", rapport.to_dict()
assert any("régime inconnu" in r.get("raison", "") for r in rapport.rejets), rapport.rejets
assert llm.appels == 0, llm.appels
print("6) régime inconnu -> échec immédiat, motivé, zéro appel LLM")

# ============================================================
# 7) le prompt d'écriture contient bloc_cadre + régime + formes + contraintes
#    -- testé en FORME, zéro appel LLM réel
# ============================================================
prompt = _prompt_ecriture(ACTE, "rattrapage", STORE, VOCAB)
assert "## 1. Remplissage" in prompt and "## 2. Divergence" in prompt \
    and "## 3. Raccord" in prompt  # bloc_cadre
assert "RATTRAPAGE" in prompt  # exigences du régime
assert "jalon-deux" in prompt and "jalon-trois" in prompt  # jalons pas-vécus listés
assert "STOCK DE FORMES DISPONIBLE" in prompt  # bloc formes.bloc_prompt
assert "ÉTATS" in prompt and "POTENTIELS" in prompt  # contraintes transverses
assert "module source" in prompt.lower() or "MODULE SOURCE" in prompt
print("7) le prompt d'écriture assemble bloc_cadre + régime + formes + contraintes")

# ============================================================
# 8) module autonome : n'importe ni engine.py ni le convertisseur -- teste
# les IMPORTS réels, jamais la présence du mot dans un commentaire/docstring
# (le module EN PARLE légitimement -- D-262 §1 -- sans jamais l'importer)
# ============================================================
import coderain.ecrivain_module as mod
src = open(mod.__file__, encoding="utf-8").read()
imports = [ln for ln in src.splitlines()
          if ln.strip().startswith("import ") or ln.strip().startswith("from ")]
assert not any("engine" in ln for ln in imports), imports
assert not any("converter" in ln for ln in imports), imports
print("8) module autonome : aucun import de engine.py ni du convertisseur")

# ============================================================
# 9) declaration_rendu (Issue #183, PRODUCTION) : une couleur par scène,
#    optionnelle -- absente -> declaration_rendu vide, aucune régression
# ============================================================
rapport = ecrire_module(ACTE, "pont", STORE, StubLLM([
    ECRITURE_OK,
    {"verdicts": [_verdict_conforme("raccord", "ta dette n'est pas la tienne")],
     "verdicts_formes": [_verdict_forme_conforme("propp-08",
                         "ta dette n'est pas la tienne")]},
]))
assert rapport.statut == "pret", rapport.to_dict()
assert rapport.declaration_rendu == ()
print("9) declaration_rendu absente -> tuple vide, aucune régression")

# ---- 9b) declaration_rendu fournie -- couleur par scène portée jusqu'au rapport
ECRITURE_AVEC_RENDU = {
    **ECRITURE_OK,
    "declaration_rendu": [{"scene": "Scène -- le campement des cendres",
                           "rendu_md": "registre feutré ; joue les silences, "
                                      "ne révèle rien"}],
}
rapport = ecrire_module(ACTE, "pont", STORE, StubLLM([
    ECRITURE_AVEC_RENDU,
    {"verdicts": [_verdict_conforme("raccord", "ta dette n'est pas la tienne")],
     "verdicts_formes": [_verdict_forme_conforme("propp-08",
                         "ta dette n'est pas la tienne")]},
]))
assert rapport.statut == "pret", rapport.to_dict()
assert rapport.declaration_rendu == (
    {"scene": "Scène -- le campement des cendres",
     "rendu_md": "registre feutré ; joue les silences, ne révèle rien"},)
print("9b) declaration_rendu fournie -> couleur par scène portée jusqu'au rapport")

# ---- 9c) entrée declaration_rendu malformée (scène vide) -> échec motivé
ECRITURE_RENDU_MALFORME = {
    **ECRITURE_OK,
    "declaration_rendu": [{"scene": "", "rendu_md": "registre feutré"}],
}
llm = StubLLM([ECRITURE_RENDU_MALFORME, ECRITURE_RENDU_MALFORME])
rapport = ecrire_module(ACTE, "pont", STORE, llm)
assert rapport.statut == "echec", rapport.to_dict()
assert any("'scene' absente ou vide" in r.get("raison", "") for r in rapport.rejets), \
    rapport.rejets
print("9c) declaration_rendu malformée (scène vide) -> échec motivé, jamais silencieux")

# ---- 9d) vers_scenario_auteur : câble la couleur vers le contrat de champ
#      commun (`scenario-auteur.json` § scenarios[].rendu_md, Issue #182)
#      une fois le node_id connu -- jamais de résolution inventée ici
from coderain.ecrivain_module import vers_scenario_auteur
entrees = vers_scenario_auteur(
    ({"scene": "Scène -- le campement des cendres",
      "rendu_md": "registre feutré ; joue les silences, ne révèle rien"},
     {"scene": "scène sans correspondance", "rendu_md": "peu importe"}),
    {"Scène -- le campement des cendres": "para-1"})
assert entrees == [{"node_id": "para-1",
                    "rendu_md": "registre feutré ; joue les silences, ne révèle rien"}]
print("9d) vers_scenario_auteur : câble vers {node_id, rendu_md} -- scène "
      "sans correspondance ignorée, jamais forcée")

print("\nOK -- ecrivain_module (D-262, issue #143) : chaîne cadre->régime->"
      "formes->écriture->retour 2, une re-demande max, sortie prête pour conversion")
