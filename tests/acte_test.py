"""L'objet ACTE — le cadre à trois lectures de l'Auteur (D-262, candidate).

Fixture 100% SYNTHÉTIQUE (D-109) : aucun contenu de campagne réel, noms et
intentions fabriqués pour le test uniquement.

Covers:
  round-trip load/render — actes.md relit identique à ce qu'il écrit (fichier
    et texte).
  validate() — garde de forme : acte sans objectif_md refusé, jalon sans
    intention_md refusé, motifs explicites (jamais silencieux).
  remplissage() — comptage vécu/pas-vécu/abandonné sur un cas à jalons mixtes,
    PLUS le rapprochement avec le vécu promu de memory/aventure.md.
  pieces_divergence()/bloc_cadre() — les trois lectures assemblées, sans
    aucun score ni seuil ; les entrées promues y figurent littéralement.
  zéro appel LLM : ce module n'importe ni n'appelle jamais coderain.llm.
"""
import os
import sys
import tempfile

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.acte import (Acte, Actes, Jalon, Raccord, bloc_cadre, load,
                           load_file, pieces_divergence, remplissage, render,
                           save_file, validate)
from coderain.memory import ADVENTURE_FILE, Entry, MemoryStore

# ---- fixture synthétique -------------------------------------------------
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
            Jalon(id="jalon-trois", statut="abandonné",
                 intention_md="Le rival fabriqué est confronté directement."),
        ],
        raccord=Raccord(module_id="module-fabrique-b",
                        conditions_entree_md="La passe est franchie ET le "
                        "pacte tient encore."),
    ),
    Acte(
        id="acte-deux", titre="Acte deux — clos fabriqué", statut="clos",
        objectif_md="État visé : la cité fabriquée est sécurisée.",
        jalons=[Jalon(id="jalon-quatre", statut="vécu",
                     intention_md="La cité fabriquée est prise.")],
        raccord=Raccord(module_id="", conditions_entree_md=""),
    ),
])


# ---- 1. round-trip --------------------------------------------------------
text = render(ACTES)
back = load(text)
assert [a.id for a in back.actes] == [a.id for a in ACTES.actes]
a, b = ACTES.actes[0], back.actes[0]
assert (a.titre, a.statut, a.objectif_md, a.raccord) == \
       (b.titre, b.statut, b.objectif_md, b.raccord)
assert [ (j.id, j.statut, j.intention_md) for j in a.jalons ] == \
       [ (j.id, j.statut, j.intention_md) for j in b.jalons ]
assert render(back) == text, "round-trip texte non octet-stable"

tmp = os.path.join(tempfile.gettempdir(), "actes_fixture_test.md")
save_file(ACTES, tmp)
reloaded = load_file(tmp)
assert render(reloaded) == text, "round-trip fichier non octet-stable"

# acte clos : raccord vide round-trippe proprement (chaîne vide, pas None)
assert reloaded.by_id("acte-deux").raccord.module_id == ""
assert reloaded.by_id("acte-deux").raccord.conditions_entree_md == ""

# ---- 2. validate: fixture bien formée = vide ------------------------------
assert validate(ACTES) == [], validate(ACTES)

# ---- 3. garde de forme: objectif_md absent, jalon sans intention ----------
bad = load(render(ACTES))
bad.actes[0].objectif_md = "   "
bad.actes[0].jalons[0].intention_md = ""
errs = validate(bad)
assert any("objectif_md absent" in e and "acte-un" in e for e in errs), errs
assert any("intention_md absente" in e and "jalon-un" in e for e in errs), errs

# statut hors vocabulaire, id dupliqué (jalon et acte)
bad2 = load(render(ACTES))
bad2.actes[0].statut = "en cours"
bad2.actes[0].jalons[0].statut = "presque-vecu"
bad2.actes.append(Acte(id="acte-un", titre="doublon", objectif_md="x"))
errs2 = validate(bad2)
assert any("statut 'en cours'" in e for e in errs2), errs2
assert any("statut 'presque-vecu'" in e for e in errs2), errs2
assert any("acte[acte-un]: id dupliqué" in e for e in errs2), errs2

# ---- 4. remplissage: comptage mixte + rapprochement vécu ------------------
story_dir = tempfile.mkdtemp(prefix="acte-store-")
store = MemoryStore(story_dir)
store.upsert_entry(ADVENTURE_FILE, Entry(title="Scénario 1", slug="scenario-1",
                                         body="- Le pacte fabriqué a été scellé."))
store.upsert_entry(ADVENTURE_FILE, Entry(title="Scénario 2", slug="scenario-2",
                                         body="- La caravane fabriquée est partie."))

acte1 = ACTES.by_id("acte-un")
rempl = remplissage(acte1, store)
assert rempl["total"] == 3
assert (rempl["vecu"], rempl["pas_vecu"], rempl["abandonne"]) == (1, 1, 1)
assert [v["titre"] for v in rempl["vecu_promu"]] == ["Scénario 1", "Scénario 2"]

# sans store : comptage seul, vécu_promu vide (jamais d'appel implicite)
rempl_sans_store = remplissage(acte1)
assert rempl_sans_store["vecu_promu"] == []
assert rempl_sans_store["total"] == 3

# ---- 5. pieces_divergence: aucun score, juste les pièces ------------------
pieces = pieces_divergence(acte1, store)
assert pieces["objectif_md"] == acte1.objectif_md
assert any("pacte fabriqué" in v["resume_md"] for v in pieces["vecu_recent"])
assert "score" not in str(pieces).lower() and "seuil" not in str(pieces).lower()

# ---- 6. bloc_cadre: les trois lectures + entrées promues, littéralement ---
bloc = bloc_cadre(acte1, store)
assert "## 1. Remplissage" in bloc
assert "## 2. Divergence" in bloc
assert "## 3. Raccord" in bloc
assert "Scénario 1" in bloc and "Le pacte fabriqué a été scellé." in bloc
assert "Scénario 2" in bloc and "La caravane fabriquée est partie." in bloc
assert "module-fabrique-b" in bloc
assert acte1.objectif_md in bloc
for j in acte1.jalons:
    assert j.id in bloc and j.intention_md in bloc

# bloc_cadre sans store : ne casse pas, section 1/2 restent présentes
bloc_sans_store = bloc_cadre(acte1)
assert "## 1. Remplissage" in bloc_sans_store
assert "(aucune entrée promue pour l'instant)" in bloc_sans_store

# ---- 7. zéro appel LLM : ce module n'importe jamais coderain.llm ---------
import coderain.acte as acte_mod
assert "llm" not in acte_mod.__file__  # sanity: bon module chargé
src = open(acte_mod.__file__, encoding="utf-8").read()
assert "coderain.llm" not in src and "from . import llm" not in src and \
       "from .llm" not in src

print("acte_test: OK — round-trip, garde de forme, remplissage, "
      "pieces_divergence, bloc_cadre (trois lectures, vécu promu), zéro LLM")
