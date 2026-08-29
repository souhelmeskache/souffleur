"""D-263 (Issue #147) : les organes Auteur au pont MCP — gardes en outils,
jugement par la session au forfait, zéro appel API.

Fixture 100% SYNTHÉTIQUE (D-109) : actes.md fabriqué pour le test, aucun
matériau de campagne réel.

Couvre les critères testables de l'Issue #147 (le 2e = golden outils
existants, le 3e = suites existantes, `run_tests.py`) :
  1. auteur_bloc_cadre : bloc cadre rendu complet (trois lectures + régime +
     formes + objectifs), acte/régime/actes.md introuvables refusés motivés.
  2. auteur_valider_ecriture : déclaration invalide (id hors vocabulaire,
     justification vide) REFUSÉE avec raison, jamais silencieuse ; module_md/
     note_intention_md vides refusés ; garde passée -> prompt de conformité
     prêt à l'emploi, jamais un appel LLM.
  3. auteur_verdicts_conformite : verdict avec extrait introuvable dans le
     texte INVALIDÉ ; objectif_id/forme_id non transmis refusé ; zéro score
     agrégé (RapportConformite-like : verdicts/rejets/conforme_total/ecarts).
  4. zéro import de client LLM dans les nouveaux outils : mcp_server.py
     n'importe ni coderain.retour2 ni coderain.ecrivain_module (les deux
     seuls organes de ce périmètre qui touchent coderain.llm), même pattern
     que le test anti-LLM de la PR #142 (acte_test.py).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.acte import Acte, Actes, Jalon, Raccord, save_file
from coderain.memory import Library

import mcp_server

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


# --------------------------------------------------------- fixture builders --
ACTES = Actes(actes=[
    Acte(
        id="acte-un", titre="Acte un — la caravane fabriquée", statut="ouvert",
        objectif_md="État visé : la caravane atteint la passe fabriquée, "
                    "le pacte tient encore.",
        jalons=[
            Jalon(id="jalon-un", statut="vécu",
                 intention_md="Le pacte est scellé avec la faction fabriquée."),
            Jalon(id="jalon-deux", statut="pas-vécu",
                 intention_md="La caravane franchit la passe fabriquée."),
        ],
        raccord=Raccord(module_id="module-fabrique-b",
                        conditions_entree_md="La passe est franchie."),
    ),
])

TMP = Path(tempfile.gettempdir()) / "se_pont_mcp_auteur_d263"
if TMP.exists():
    import shutil
    shutil.rmtree(TMP)
TMP.mkdir(parents=True)
actes_path = TMP / "actes.md"
save_file(ACTES, actes_path)

mcp_server._engine = None
mcp_server._store = None
mcp_server._auteur_ctx = {}

# ------------------------------------------------------------- section 1 ----
section("1) auteur_bloc_cadre : bloc complet, régime pont")
out = mcp_server.auteur_bloc_cadre("acte-un", "pont", str(actes_path))
assert "error" not in out, out
assert "## 1. Remplissage" in out["bloc_cadre"]
assert "## 2. Divergence" in out["bloc_cadre"]
assert "## 3. Raccord" in out["bloc_cadre"]
assert "PONT :" in out["bloc_regime"]
assert "STOCK DE FORMES DISPONIBLE" in out["bloc_formes"]
assert "ÉTATS et des POTENTIELS" in out["contraintes_transverses"]
assert out["objectifs"] == [{"id": "raccord",
                             "texte": "Le module rend atteignable le raccord "
                             "vers module-fabrique-b — conditions d'entrée : "
                             "La passe est franchie."}]
assert mcp_server._auteur_ctx["objectifs"] == out["objectifs"]

section("1b) auteur_bloc_cadre : régime rattrapage liste les jalons pas-vécus")
out_r = mcp_server.auteur_bloc_cadre("acte-un", "rattrapage", str(actes_path))
assert "jalon-deux" in out_r["bloc_regime"]
assert out_r["objectifs"] == [{"id": "jalon-jalon-deux",
                               "texte": "Le module fait vivre le jalon "
                               "'jalon-deux' : La caravane franchit la "
                               "passe fabriquée."}]

section("1c) auteur_bloc_cadre : refus motivés (régime/acte/fichier inconnus)")
assert "régime inconnu" in mcp_server.auteur_bloc_cadre(
    "acte-un", "n-importe-quoi", str(actes_path))["error"]
err_acte = mcp_server.auteur_bloc_cadre("acte-fantome", "pont", str(actes_path))
assert "acte introuvable" in err_acte["error"]
assert err_acte["actes_disponibles"] == ["acte-un"]
err_path = mcp_server.auteur_bloc_cadre("acte-un", "pont",
                                        str(TMP / "n-existe-pas.md"))
assert "introuvable" in err_path["error"]
err_nopath = mcp_server.auteur_bloc_cadre("acte-un", "pont", "")
assert "actes_path vide" in err_nopath["error"]

# -------------------------------------------------- section 2 (valider) -----
mcp_server.auteur_bloc_cadre("acte-un", "pont", str(actes_path))  # repose le contexte

section("2) auteur_valider_ecriture : module_md/note vides refusés")
out2 = mcp_server.auteur_valider_ecriture("", "[]", "")
assert out2["ok"] is False
raisons = [r["raison"] for r in out2["rejets"]]
assert any("module_md absent" in r for r in raisons)
assert any("note_intention_md absente" in r for r in raisons)

section("2b) auteur_valider_ecriture : déclaration hors vocabulaire refusée")
out2b = mcp_server.auteur_valider_ecriture(
    "Le module fabriqué mène à la passe.",
    json.dumps([{"id": "forme-inexistante", "justification": "x"}]),
    "Note d'intention fabriquée.")
assert out2b["ok"] is False
assert any("hors vocabulaire" in r["raison"] for r in out2b["rejets"]), out2b

section("2c) auteur_valider_ecriture : justification vide refusée")
out2c = mcp_server.auteur_valider_ecriture(
    "Le module fabriqué mène à la passe.",
    json.dumps([{"id": "propp-01", "justification": ""}]),
    "Note d'intention fabriquée.")
assert out2c["ok"] is False
assert any("sans justification" in r["raison"] for r in out2c["rejets"]), out2c

section("2d) auteur_valider_ecriture : garde passée -> prompt de conformité")
MODULE_MD = ("Le module fabriqué mène la caravane à la passe. \"La passe "
            "franchie, le pacte tient encore.\"")
out2d = mcp_server.auteur_valider_ecriture(
    MODULE_MD,
    json.dumps([{"id": "propp-01",
                "justification": "l'éloignement de la garde ouvre la route"}]),
    "Note d'intention fabriquée, écrite au passé.")
assert out2d["ok"] is True
assert out2d["formes_validees"] == [
    {"id": "propp-01",
     "justification": "l'éloignement de la garde ouvre la route"}]
prompt = out2d["conformite_prompt"]
assert "RETOUR 2" in prompt["system"] or "compliance judge" in prompt["system"]
assert "OBJECTIFS TRANSMIS" in prompt["payload"]
assert "TEXTE À JUGER" in prompt["payload"] and MODULE_MD in prompt["payload"]
assert prompt["objectifs"] == mcp_server._auteur_ctx["objectifs"]
assert mcp_server._auteur_ctx["module_md"] == MODULE_MD
assert mcp_server._auteur_ctx["declaration_formes"] == out2d["formes_validees"]

# ------------------------------------------------ section 3 (verdicts) ------
section("3) auteur_verdicts_conformite : sans contexte -> erreur motivée")
mcp_server._auteur_ctx = {"objectifs": mcp_server._auteur_ctx["objectifs"]}
err3 = mcp_server.auteur_verdicts_conformite(json.dumps({"verdicts": []}))
assert "error" in err3

# repose un contexte complet
mcp_server.auteur_bloc_cadre("acte-un", "pont", str(actes_path))
mcp_server.auteur_valider_ecriture(
    MODULE_MD,
    json.dumps([{"id": "propp-01",
                "justification": "l'éloignement de la garde ouvre la route"}]),
    "Note d'intention fabriquée.")

section("3b) verdict avec extrait introuvable dans le texte -> invalidé")
bad_verdicts = {
    "verdicts": [{"objectif_id": "raccord", "verdict": "conforme",
                 "justification": "la caravane atteint la passe",
                 "extraits": ["ce passage n'existe nulle part dans le texte"]}],
    "verdicts_formes": [{"forme_id": "propp-01", "correspond": "conforme",
                         "justification": "cohérent",
                         "extraits": ["la caravane à la passe"]}],
}
out3b = mcp_server.auteur_verdicts_conformite(json.dumps(bad_verdicts))
assert out3b["verdicts"] == [], out3b
assert any("extrait introuvable" in r["raison"] for r in out3b["rejets"]), out3b
# l'écart correspondant : objectif non couvert (verdict rejeté) -> aucun score
assert out3b["conforme_total"] is False
assert any(e["type"] == "objectif" and e["verdict"] == "non-couvert"
          for e in out3b["ecarts"])
assert "score" not in str(out3b).lower()

section("3c) objectif_id/forme_id non transmis -> refusé")
unknown_obj = {
    "verdicts": [{"objectif_id": "objectif-fantome", "verdict": "conforme",
                 "justification": "x", "extraits": []}],
}
out3c = mcp_server.auteur_verdicts_conformite(json.dumps(unknown_obj))
assert out3c["verdicts"] == []
assert any("objectif non transmis" in r["raison"] for r in out3c["rejets"])

section("3d) verdicts valides et ancrés -> conforme_total")
good_verdicts = {
    "verdicts": [{"objectif_id": "raccord", "verdict": "conforme",
                 "justification": "le texte mène la caravane à la passe",
                 "extraits": ["mène la caravane à la passe"]}],
    "verdicts_formes": [{"forme_id": "propp-01", "correspond": "conforme",
                         "justification": "cohérent avec la déclaration",
                         "extraits": ["la caravane à la passe"]}],
}
out3d = mcp_server.auteur_verdicts_conformite(json.dumps(good_verdicts))
assert len(out3d["verdicts"]) == 1 and out3d["verdicts"][0]["verdict"] == "conforme"
assert len(out3d["verdicts_formes"]) == 1
assert out3d["rejets"] == []
assert out3d["conforme_total"] is True
assert out3d["ecarts"] == []

# --------------------------------------------------- section 4 (anti-LLM) ---
section("4) zéro import de client LLM dans les nouveaux outils")
src = Path(mcp_server.__file__).read_text(encoding="utf-8")
tree = __import__("ast").parse(src)
imported_modules = set()
for node in __import__("ast").walk(tree):
    if isinstance(node, __import__("ast").Import):
        imported_modules.update(a.name for a in node.names)
    elif isinstance(node, __import__("ast").ImportFrom):
        module = node.module or ""
        # `from coderain import retour2` -> le nom importé compte, pas
        # seulement le module d'origine (`coderain`).
        if node.level:  # import relatif, ne concerne pas ce fichier top-level
            continue
        imported_modules.add(module)
        for a in node.names:
            imported_modules.add(f"{module}.{a.name}" if module else a.name)
assert "coderain.retour2" not in imported_modules and \
      "retour2" not in imported_modules, \
      "mcp_server.py importe retour2.py (touche coderain.llm -> openai)"
assert "coderain.ecrivain_module" not in imported_modules and \
      "ecrivain_module" not in imported_modules, \
      "mcp_server.py importe ecrivain_module.py (touche coderain.llm -> openai)"
assert "coderain.llm" not in imported_modules and "llm" not in imported_modules
assert "openai" not in imported_modules and not any(
    m.startswith("openai.") for m in imported_modules)
# sanity : coderain.llm porte bien l'import openai attendu (le module existe,
# ce test vérifie que mcp_server.py ne l'importe pas LUI-MÊME, pas qu'aucun
# autre organe déjà en place — rules_engine, préexistant, hors périmètre de
# cette lane — ne le touche transitivement)
llm_src = (ROOT / "coderain" / "llm.py").read_text(encoding="utf-8")
assert "from openai import OpenAI" in llm_src

print("\nALL D-263 PONT MCP AUTEUR (#147) CHECKS PASSED: " + ", ".join(FAIT))
