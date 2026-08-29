"""D-261 -- le stock de formes (vocabulaire composable versionné, Propp/
Polti/ATU) et sa garde de forme : `coderain.formes.valider_declaration`
REFUSE toute déclaration d'Auteur non ancrée au vocabulaire versionné, sans
jamais faire d'appel LLM (module de garde pur) ; `coderain.author` étend le
détecteur de répétition I-229 des codes de tension aux formes déclarées.

Fixtures 100% synthétiques (D-109) : scénarios et déclarations inventés
pour ce test seul -- aucun matériau de campagne réel. Le vocabulaire
lui-même (`catalogue/formes/*.json`) est chargé tel quel : il est public et
versionné dans ce repo, pas un secret de campagne.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coderain.formes import Forme, charger_vocabulaire, valider_declaration, bloc_prompt
from coderain.author import (comparer_paire_formes, detecter_campagne_formes,
                              rapport_formes)

# ============================================================
# Le vocabulaire versionné réel (catalogue/formes/) -- pas une fixture,
# c'est le stock consommé tel quel par la garde de forme.
# ============================================================

VOCAB = charger_vocabulaire()

# ---- 0) le stock versionné est complet : Propp 31/31, Polti 36/36, une
# sélection ATU raisonnée (20-40, pas l'index entier) ----
par_source = {}
for f in VOCAB.values():
    par_source[f.source] = par_source.get(f.source, 0) + 1
assert par_source.get("propp") == 31, par_source
assert par_source.get("polti") == 36, par_source
assert 20 <= par_source.get("atu", 0) <= 40, par_source
print("0) stock versionné complet : Propp 31/31, Polti 36/36, ATU en sélection raisonnée")

# ---- 0b) chaque forme porte les 4 champs exigés, exige non vide ----
for f in VOCAB.values():
    assert f.id and f.nom and f.description, f
    assert len(f.exige) >= 1, f"{f.id} sans champ exige"
    # compose_avec pointe uniquement vers des ids qui existent dans le stock
    for cid in f.compose_avec:
        assert cid in VOCAB, f"{f.id} compose_avec un id inconnu : {cid}"
print("0b) chaque forme est composable : exige non vide, compose_avec ancré au stock")

# ============================================================
# 1) déclaration valide -> acceptée
# ============================================================
declaration = [
    {"id": "propp-08", "justification": "le méfait porte la dette de sang "
     "que le personnage traîne depuis l'enfance"},
    {"id": "polti-03", "justification": "la vengeance du personnage répond "
     "directement au crime établi en propp-08"},
]
validees, rejets = valider_declaration(declaration, VOCAB)
assert rejets == [], rejets
assert len(validees) == 2, validees
assert validees[0] == {"id": "propp-08", "justification": declaration[0]["justification"]}
print("1) une déclaration bien formée, ancrée au vocabulaire, est acceptée sans rejet")

# ============================================================
# 2) id inventé -> refusé, message explicite
# ============================================================
validees, rejets = valider_declaration(
    [{"id": "propp-99-invente", "justification": "peu importe"}], VOCAB)
assert validees == [], validees
assert len(rejets) == 1 and "hors vocabulaire" in rejets[0]["raison"], rejets
assert "propp-99-invente" in rejets[0]["raison"], rejets
print("2) un id hors vocabulaire est refusé avec un message explicite")

# ============================================================
# 3) déclaration vide -> refusée
# ============================================================
validees, rejets = valider_declaration([], VOCAB)
assert validees == [] and len(rejets) == 1, rejets
assert "déclaration vide" in rejets[0]["raison"], rejets
print("3) une déclaration vide est refusée avant tout examen d'id")

# ---- 3b) justification vide -> refusée elle aussi (rejet motivé) ----
validees, rejets = valider_declaration(
    [{"id": "polti-01", "justification": "   "}], VOCAB)
assert validees == [] and len(rejets) == 1, rejets
assert "sans justification" in rejets[0]["raison"], rejets
assert "polti-01" in rejets[0]["raison"], rejets
print("3b) une justification vide est refusée, message motivé, jamais silencieux")

# ============================================================
# 4) rejets et acceptations mêlés dans une même déclaration -- jamais
# silencieux, chaque cas porte sa propre raison
# ============================================================
declaration_mixte = [
    {"id": "atu-300", "justification": "le dragon incarne la menace qui pèse sur le village"},
    {"id": "forme-inconnue", "justification": "x"},
    {"id": "propp-02", "justification": "   "},
]
validees, rejets = valider_declaration(declaration_mixte, VOCAB)
assert len(validees) == 1 and validees[0]["id"] == "atu-300", validees
assert len(rejets) == 2, rejets
raisons = {r["raison"] for r in rejets}
assert any("hors vocabulaire" in r for r in raisons), raisons
assert any("sans justification" in r for r in raisons), raisons
print("4) déclaration mixte : chaque forme validée ou rejetée indépendamment, motivée")

# ============================================================
# 5) le bloc de prompt : contient le vocabulaire filtré + exige la
# déclaration / le lien à la pulsion / la part d'adversité. Aucun appel LLM
# ici -- c'est un bloc de texte pur.
# ============================================================
bloc = bloc_prompt(VOCAB, sous_ensemble=["propp-08", "polti-03"])
assert '"propp-08"' in bloc and '"polti-03"' in bloc, bloc
assert '"propp-11"' not in bloc, "le sous-ensemble filtré ne doit pas fuiter d'autres ids"
assert "pulsion" in bloc, bloc
assert "adversité" in bloc, bloc
assert "DÉCLARER" in bloc or "déclar" in bloc.lower(), bloc
print("5) le bloc de prompt filtré porte le vocabulaire restreint + exige déclaration/pulsion/adversité")

# ---- 5b) sans filtre, le bloc porte tout le stock ----
bloc_complet = bloc_prompt(VOCAB)
for source, attendu in (("propp", 31), ("polti", 36)):
    assert bloc_complet.count(f'"source": "{source}"') == attendu, (source, bloc_complet.count(f'"source": "{source}"'))
print("5b) sans sous-ensemble, le bloc de prompt porte le stock complet")

# ============================================================
# 6) extension I-229 aux formes : répétition d'un même id de forme détectée
# à travers deux scénarios synthétiques (D-109)
# ============================================================
declaration_scenario_a, _ = valider_declaration([
    {"id": "propp-08", "justification": "le méfait ouvre le scénario A"},
    {"id": "atu-300", "justification": "un dragon menace le village dans A"},
], VOCAB)
declaration_scenario_b, _ = valider_declaration([
    {"id": "propp-08", "justification": "le méfait ouvre aussi le scénario B, "
     "sur un autre personnage"},
    {"id": "polti-11", "justification": "une énigme structure B"},
], VOCAB)

signaux = comparer_paire_formes("scenario-a", declaration_scenario_a,
                                 "scenario-b", declaration_scenario_b)
assert len(signaux) == 1, signaux
signal = signaux[0]
assert signal.forme_id == "propp-08", signal
assert signal.scenario_a == "scenario-a" and signal.scenario_b == "scenario-b", signal
assert "scénario A" in signal.justification_a, signal
assert "scénario B" in signal.justification_b, signal
print("6) une même forme déclarée dans deux scénarios distincts est signalée (I-229 étendu)")

# ---- 6b) aucune forme partagée -> aucun signal ----
declaration_scenario_c, _ = valider_declaration([
    {"id": "atu-410", "justification": "un sommeil enchanté structure C"},
], VOCAB)
assert comparer_paire_formes("scenario-a", declaration_scenario_a,
                              "scenario-c", declaration_scenario_c) == []
print("6b) deux scénarios sans forme partagée ne produisent aucun signal")

# ---- 6c) à l'échelle campagne : detecter_campagne_formes compare toutes
# les paires, jamais un scénario contre lui-même ----
campagne_signaux = detecter_campagne_formes({
    "scenario-a": declaration_scenario_a,
    "scenario-b": declaration_scenario_b,
    "scenario-c": declaration_scenario_c,
})
assert len(campagne_signaux) == 1, campagne_signaux
assert campagne_signaux[0].forme_id == "propp-08", campagne_signaux
rap = rapport_formes(campagne_signaux)
assert rap["total"] == 1 and rap["par_forme"] == {"propp-08": 1}, rap
print("6c) à l'échelle campagne, seule la paire A/B partage une forme -- jamais un scénario contre lui-même")

print("\nOK -- stock de formes (D-261) : vocabulaire, garde de forme, extension I-229")
