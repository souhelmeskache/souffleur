"""Test d'élément — PRODUCTION Auteur : rendu_md par scène (Issue #183).

Brique visée : `coderain.ecrivain_module.ecrire_module` (sortie
`declaration_rendu`, garde de forme `_valider_declaration_rendu`) +
`coderain.ecrivain_module.vers_scenario_auteur` (câblage vers le contrat de
champ commun `scenario-auteur.json` § `scenarios[].rendu_md`, posé par
`Node.attach_scenario` — Issue #182, EXTRACTION). Voir
tests/fixtures/element_mold.py pour la doctrine du moule et
README-moule-test-element.md pour le gabarit.

Fixtures d'états (100% synthétique, D-109/D-206 — aucun matériau réel) :
  1. sortie Auteur avec une couleur par scène -> câblée vers
     {node_id, rendu_md} par `vers_scenario_auteur`, atterrit sur le bon
     `Node.rendu_md` une fois attachée (`Node.attach_scenario`).
  2. une couleur posant une séquence d'événements imposée (« le joueur fait
     X puis Y ») -> refusée par la garde anti-rail du socle (D-065,
     héritée, non dupliquée dans l'Auteur — même choix que le converter,
     `test-element-rendu-md-converter.py`).
  3. absence de declaration_rendu -> `rapport.declaration_rendu` vide,
     aucune entrée câblée, `rendu_md` du node reste vide (aucune régression).

Verdicts mécaniques (D-134) : égalité de chaîne, ValueError levée avec le
bon marqueur, listes vides.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.fixtures.element_mold import ElementMold
from coderain.acte import Acte, Jalon, Raccord
from coderain.ecrivain_module import ecrire_module, vers_scenario_auteur
from coderain.memory import MemoryStore

# le converter reste hors des imports d'ecrivain_module.py (D-262 §5, testé
# ailleurs, test-ecrivain-module-i143.py #8) -- ce test-là, lui, VÉRIFIE
# l'atterrissage bout en bout, donc importe les deux côtés du contrat.
from coderain.converter.schemas import Node

ACTE = Acte(
    id="acte-fabrique", titre="Acte fabriqué -- la veillée des braises",
    statut="ouvert",
    objectif_md="État visé : la veillée des braises est tenue jusqu'au bout.",
    jalons=[Jalon(id="jalon-un", statut="pas-vécu",
                  intention_md="Le feu de camp tient jusqu'à l'aube.")],
    raccord=Raccord(module_id="module-fabrique-suivant",
                    conditions_entree_md="Le feu tient encore."),
)
STORE = MemoryStore(tempfile.mkdtemp(prefix="rendu-md-auteur-store-"))

MODULE_MD = ("## Scène -- la veillée des braises\nAutour du feu, les "
            "silhouettes se taisent. Quelqu'un finira par parler du "
            "créancier fabriqué qui rôde.")
NOTE_MD = ("J'ai choisi le silence collectif pour que la menace du "
          "créancier reste suspendue, jamais nommée trop tôt.")
FORMES_OK = [{"id": "propp-08",
             "justification": "le méfait plane sur la veillée sans se "
             "montrer encore"}]


class StubLLM:
    """Une file de réponses JSON, une par appel -- une réponse de trop
    demandée lève une erreur explicite (100% hors-ligne, D-109)."""
    def __init__(self, reponses: list[dict]):
        self._file = list(reponses)

    def complete(self, messages, **kw):
        if not self._file:
            raise AssertionError("appel LLM inattendu -- file épuisée")
        return json.dumps(self._file.pop(0), ensure_ascii=False)


def _verdict_conforme(objectif_id: str) -> dict:
    return {"objectif_id": objectif_id, "verdict": "conforme",
            "justification": "ok", "extraits": ["braises"]}


def _verdict_forme_conforme(forme_id: str) -> dict:
    return {"forme_id": forme_id, "correspond": "conforme",
            "justification": "ok", "extraits": ["braises"]}


VERDICTS_OK = {"verdicts": [_verdict_conforme("raccord")],
              "verdicts_formes": [_verdict_forme_conforme("propp-08")]}


with ElementMold("ecrivain-module-rendu_md-auteur", budget_seconds=5.0) as mold:

    # ---- 1. couleur par scène -> câblée -> atterrit sur le bon Node ------
    ECRITURE_AVEC_RENDU = {
        "module_md": MODULE_MD, "declaration_formes": FORMES_OK,
        "note_intention_md": NOTE_MD,
        "declaration_rendu": [{"scene": "Scène -- la veillée des braises",
                               "rendu_md": "registre feutré ; joue les "
                                          "silences, ne révèle rien"}],
    }
    rapport1 = ecrire_module(ACTE, "pont", STORE,
                             StubLLM([ECRITURE_AVEC_RENDU, VERDICTS_OK]))
    entrees = vers_scenario_auteur(
        rapport1.declaration_rendu,
        {"Scène -- la veillée des braises": "sc-veillee"})
    node1 = Node("sc-veillee", "chapitre", "La veillée",
                "Autour du feu.", "scene", anchors=[(0, 10)])
    for e in entrees:
        assert e["node_id"] == "sc-veillee"
        node1.attach_scenario("tenir la veillée", rendu_md=e["rendu_md"])
    mold.check(
        "1-couleur-par-scene-atterrit-sur-le-node",
        rapport1.statut == "pret" and len(entrees) == 1
        and node1.rendu_md == "registre feutré ; joue les silences, "
                              "ne révèle rien",
        f"statut={rapport1.statut!r} entrees={entrees!r} "
        f"node.rendu_md={node1.rendu_md!r}")

    # ---- 2. séquence déguisée en couleur -> refusée par le socle ---------
    ECRITURE_SEQUENCE = {
        "module_md": MODULE_MD, "declaration_formes": FORMES_OK,
        "note_intention_md": NOTE_MD,
        "declaration_rendu": [{"scene": "Scène -- la veillée des braises",
                               "rendu_md": "le joueur fait X puis Y"}],
    }
    rapport2 = ecrire_module(ACTE, "pont", STORE,
                             StubLLM([ECRITURE_SEQUENCE, VERDICTS_OK]))
    entrees2 = vers_scenario_auteur(
        rapport2.declaration_rendu,
        {"Scène -- la veillée des braises": "sc-sequence"})
    try:
        Node("sc-sequence", "chapitre", "La veillée", "Autour du feu.",
            "scene", anchors=[(0, 10)], rendu_md=entrees2[0]["rendu_md"])
        seq_refusee, detail = False, "aucune exception levée"
    except ValueError as e:
        seq_refusee, detail = "D-065" in str(e), str(e)
    mold.check("2-sequence-deguisee-refusee-par-socle", seq_refusee, detail)

    # ---- 3. absence de declaration_rendu -> vide, aucune régression ------
    ECRITURE_SANS_RENDU = {
        "module_md": MODULE_MD, "declaration_formes": FORMES_OK,
        "note_intention_md": NOTE_MD,
    }
    rapport3 = ecrire_module(ACTE, "pont", STORE,
                             StubLLM([ECRITURE_SANS_RENDU, VERDICTS_OK]))
    entrees3 = vers_scenario_auteur(
        rapport3.declaration_rendu, {"Scène -- la veillée des braises": "sc-vide"})
    node3 = Node("sc-vide", "chapitre", "La veillée", "Autour du feu.",
                "scene", anchors=[(0, 10)])
    node3.attach_scenario("tenir la veillée")  # aucun rendu_md fourni
    mold.check(
        "3-absence-declaration-rendu-vide",
        rapport3.statut == "pret" and rapport3.declaration_rendu == ()
        and entrees3 == [] and node3.rendu_md == "",
        f"statut={rapport3.statut!r} declaration_rendu={rapport3.declaration_rendu!r} "
        f"entrees={entrees3!r} node.rendu_md={node3.rendu_md!r}")

assert mold.report(), ("test-element-rendu-md-auteur: au moins un "
                       "verdict a échoué")
print("test-element-rendu-md-auteur: OK — Issue #183, "
     "3 verdicts mécaniques + coût borné")
