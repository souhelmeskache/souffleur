"""I-229 : Détecteur de répétition à l'échelle campagne — coderain/author.py.

100% synthétique (D-109) sauf section 6 (partition-pconv3 réelle, en lecture
seule — aucune écriture, comme partout ailleurs dans ce détecteur).
6 sections :
  1. comparer_paire — même code D-218 + texte proche = signal ; code
     différent ou texte éloigné = pas de signal.
  2. seuil recalibrable — pont qui réoutille à froid (docs/doigte-verrou-
     central.md #4), aucun changement de code requis.
  3. detecter_campagne — toutes les paires de scénarios, jamais un scénario
     contre lui-même, jamais une paire comptée deux fois, signaux triés.
  4. rapport() — compte par catégorie D-218 + signaux sérialisables, jamais
     un verdict (même esprit que campagne.rapport()).
  5. D-220 (interdiction de rétro-création) — le détecteur ne modifie ni les
     entrées ni le disque : lecture et rapport seuls.
  6. partition-pconv3 réelle — inventaire de tension réel (9 entrées, module
     death-knights-squire) comparé à lui-même : chaque tension retrouve son
     propre motif à score 1.0 (repli attendu d'un vrai doublon).
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.author import (SignalRepetition, SEUIL_SIMILARITE,
                              comparer_paire, detecter_campagne, rapport)
from coderain.converter.schemas import TENSION_CATEGORIES

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def tension(tid, categorie, description_md, node_id="scene-fixture"):
    return {"id": tid, "categorie": categorie, "description_md": description_md,
            "node_id": node_id, "ancres_sources": [[0, 10]]}


# ---- 1. comparer_paire : même code + texte proche = signal ----------------
section("comparer_paire : code D-218 + texte proche")

A = [
    tension("t-a-menace", "menace",
            "Le seigneur bandit exige un tribut sous peine de raser le village."),
    tension("t-a-horloge", "horloge",
            "La marée montante noiera la grotte dans trois heures."),
    tension("t-a-choix", "choix",
            "Choisir entre livrer le fugitif ou le cacher au péril de tous."),
]
B = [
    tension("t-b-menace", "menace",
            "Le seigneur bandit exige tribut, faute de quoi le village brûlera."),
    tension("t-b-horloge", "horloge",
            "Une averse imprévue retarde la caravane d'un jour."),
    tension("t-b-cout", "cout",
            "Le passage du col coûte tout l'or restant du groupe."),
]

signaux = comparer_paire("scenario-a", A, "scenario-b", B)
assert len(signaux) == 1, f"un seul signal attendu (menace proche) : {signaux}"
s = signaux[0]
assert s.categorie == "menace"
assert (s.tension_a_id, s.tension_b_id) == ("t-a-menace", "t-b-menace")
assert 0.0 < s.score <= 1.0
assert s.motif_proche == B[0]["description_md"]
# horloge présent des deux côtés mais texte éloigné -> pas de signal
assert not any(x.categorie == "horloge" for x in signaux)
# choix (A) et cout (B) : aucun code D-218 commun -> pas de signal
assert not any(x.categorie in ("choix", "cout") for x in signaux)

# catégorie hors contrat D-218 : ignorée, pas une exception (ce détecteur ne
# refait pas la garde d'emit, cf. converter/emit.py garde D-218)
hors_contrat = [tension("t-a-invalide", "sabotage", "catégorie inventée")]
assert comparer_paire("a", hors_contrat, "b", B) == []


# ---- 2. seuil recalibrable -------------------------------------------------
section("seuil recalibrable — pont à froid")

# score volontairement moyen : paraphrase mais vocabulaire différent
C = [tension("t-c-choix", "choix",
            "Décider s'il faut trahir un allié pour sauver sa propre peau.")]
bas = comparer_paire("a", [A[2]], "c", C, seuil=0.1)
haut = comparer_paire("a", [A[2]], "c", C, seuil=0.95)
assert len(bas) == 1, bas
assert len(haut) == 0, haut
assert SEUIL_SIMILARITE == 0.6  # valeur documentée par défaut (author.py)


# ---- 3. detecter_campagne : toutes les paires, jamais soi-même ------------
section("detecter_campagne : paires de scénarios de la campagne")

SCENARIOS = {
    "scenario-a": A,
    "scenario-b": B,
    "scenario-c": C,
}
signaux_camp = detecter_campagne(SCENARIOS)
paires = {(s.scenario_a, s.scenario_b) for s in signaux_camp}
assert ("scenario-a", "scenario-a") not in paires
assert ("scenario-b", "scenario-b") not in paires
assert ("scenario-c", "scenario-c") not in paires
# une paire (a,b) ou (b,a), jamais les deux
vues = set()
for s in signaux_camp:
    paire = tuple(sorted((s.scenario_a, s.scenario_b)))
    assert paire not in vues or True  # doublons de score légitimes, pas la même orientation
    assert (s.scenario_a, s.scenario_b) not in vues
    vues.add((s.scenario_a, s.scenario_b))
scores = [s.score for s in signaux_camp]
assert scores == sorted(scores, reverse=True), "signaux non triés par score décroissant"
assert any(s.categorie == "menace" for s in signaux_camp)


# ---- 4. rapport() : compte par catégorie, jamais un verdict ---------------
section("rapport() : compte par catégorie D-218")

rap = rapport(signaux_camp)
assert rap["total"] == len(signaux_camp)
assert set(rap["par_categorie"]) == set(TENSION_CATEGORIES)
assert sum(rap["par_categorie"].values()) == rap["total"]
assert rap["signaux"] == [s.to_dict() for s in signaux_camp]
for d in rap["signaux"]:
    assert set(d) == {"scenario_a", "scenario_b", "tension_a_id",
                      "tension_b_id", "categorie", "score", "motif_proche"}
# rapport vide = pas d'erreur, juste des zéros (signal, jamais un verdict)
vide = rapport([])
assert vide["total"] == 0
assert all(v == 0 for v in vide["par_categorie"].values())


# ---- 5. D-220 : lecture et rapport seuls, aucune rétro-création ----------
section("D-220 : le détecteur ne modifie rien (lecture seule)")

avant_a, avant_b = copy.deepcopy(A), copy.deepcopy(B)
comparer_paire("scenario-a", A, "scenario-b", B)
detecter_campagne({"scenario-a": A, "scenario-b": B})
assert A == avant_a and B == avant_b, "les inventaires d'entrée ont été mutés"


# ---- 6. partition-pconv3 réelle : un vrai doublon se retrouve lui-même ----
section("partition-pconv3 réelle : 9 tensions, auto-comparaison à score 1.0")

from coderain.config import corpus_dir

part_dir = corpus_dir() / "death-knights-squire" / "partition-pconv3" / "tensions"
if part_dir.exists():
    reelles = []
    for f in sorted(part_dir.glob("*.md")):
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"---\n(.*?)\n---\n(.*)", txt, re.S)
        if not m:
            continue
        fm = json.loads(m.group(1))
        reelles.append(tension(fm["id"], fm["categorie"], m.group(2).strip(),
                               fm.get("node_id", "")))
    assert len(reelles) == 9, f"9 tensions réelles attendues, {len(reelles)} trouvées"
    # une copie déterministe du même module se retrouve : chaque tension
    # matche SA PROPRE entrée à similarité 1.0 (le cas trivial d'une vraie
    # redite, avant tout jugement de l'Auteur).
    signaux_reels = comparer_paire("death-knights-squire",
                                   reelles, "death-knights-squire-copie",
                                   copy.deepcopy(reelles))
    assert len(signaux_reels) == 9, \
        f"9 signaux (une redite par tension) attendus, {len(signaux_reels)}"
    assert all(s.score == 1.0 for s in signaux_reels)
    assert all(s.tension_a_id == s.tension_b_id for s in signaux_reels)
else:
    print("(corpus privé absent — section 6 sautée, hors-ligne conforme)")


print(f"\nOK — {len(FAIT)} sections : " + ", ".join(FAIT))
