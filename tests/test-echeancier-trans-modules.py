"""D-253.1 (Issue #71) — l'échéancier trans-modules et sa garde de
réadaptation. Fixture 100% synthétique (D-109) : une `Aventure` factice à
trois conditions datées (1 échue, 2 vivantes) plus un déclencheur `etat`
hors périmètre garde, puis trois re-scripts simulés (perte / ré-émission /
solde par Patch) qui exercent le critère de fin de l'Issue #71.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.converter.schemas import Aventure, Patch
from coderain.echeancier import extraire, garder_reportage

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


DATE_POSE = date(2026, 1, 1)
DATE_REFERENCE = date(2026, 1, 15)


def aventure_fixture():
    """3 conditions datées (1 échue, 2 vivantes) + 1 déclencheur etat."""
    return Aventure(
        trajectoire=[
            {"id": "cond-armee-capitale",
             "description_md": "L'armée atteint la capitale.",
             "declencheur": {"type": "delai", "valeur": "30 jours"},
             "anchors": [(0, 20)]},
            {"id": "cond-pont-effondre",
             "description_md": "Le pont s'effondre.",
             "declencheur": {"type": "date", "valeur": "2026-01-10"},
             "anchors": [(21, 40)]},
        ],
        conditions=[
            {"id": "cond-recolte",
             "description_md": "La récolte mûrit.",
             "declencheur": {"type": "date", "valeur": "2026-03-01"},
             "anchors": [(41, 60)]},
            {"id": "cond-garde-mefiante",
             "description_md": "La garde devient méfiante.",
             "declencheur": {"type": "etat", "valeur": "heros repere"},
             "anchors": [(61, 80)]},
        ],
        charniere_md="Le module se referme sur la charnière du chapitre 2.",
    )


# 1) extraction : 2 vivantes, 1 échue, 1 etat, ancrées ----------------------
section("1) extraire() : 2 vivantes, 1 échue, 1 etat, ancrées fichier:offset")
ech = extraire(aventure_fixture(), date_reference=DATE_REFERENCE,
                date_pose=DATE_POSE, fichier="module-01")
assert len(ech.vivantes) == 2, ech.rapport()
assert len(ech.echues) == 1, ech.rapport()
assert len(ech.etats) == 1, ech.rapport()
assert ech.avertissements == []
vivantes_ids = {c.porteur_id for c in ech.vivantes}
assert vivantes_ids == {"cond-armee-capitale", "cond-recolte"}
assert ech.echues[0].porteur_id == "cond-pont-effondre"
assert ech.etats[0].porteur_id == "cond-garde-mefiante"
for c in ech.vivantes:
    assert c.ancre.startswith("module-01:")
# delai "30 jours" posé le 2026-01-01 -> échéance 2026-01-31
armee = next(c for c in ech.vivantes if c.porteur_id == "cond-armee-capitale")
assert armee.echeance == date(2026, 1, 31)
assert armee.type_declencheur == "delai"

# 2) valeur illisible : exclue + avertissement, jamais une exception -------
section("2) declencheur date/delai illisible : signalé, jamais levé")
av_illisible = Aventure(
    trajectoire=[{"id": "cond-brouillon",
                  "description_md": "Front mal saisi.",
                  "declencheur": {"type": "date", "valeur": "bientot"},
                  "anchors": [(0, 5)]}],
    conditions=[], charniere_md="")
ech2 = extraire(av_illisible, date_reference=DATE_REFERENCE,
                 date_pose=DATE_POSE, fichier="module-x")
assert ech2.vivantes == [] and ech2.echues == []
assert len(ech2.avertissements) == 1
assert "cond-brouillon" in ech2.avertissements[0]

# 3) garde : re-script qui PERD une condition vivante -> REFUS -------------
section("3) garder_reportage() : perte d'une condition vivante -> refus nommé")
apres_perte = aventure_fixture()
# on retire "cond-armee-capitale" de l'aventure re-scriptée
apres_perte.trajectoire = [e for e in apres_perte.trajectoire
                           if e.id != "cond-armee-capitale"]
erreurs = garder_reportage(ech.vivantes, apres_perte)
assert len(erreurs) == 1, erreurs
assert "cond-armee-capitale" in erreurs[0]

# 4) garde : re-script qui RÉ-ÉMET la condition telle quelle -> passe ------
section("4) garder_reportage() : ré-émission telle quelle -> passe")
erreurs_reemis = garder_reportage(ech.vivantes, aventure_fixture())
assert erreurs_reemis == [], erreurs_reemis

# 5) garde : re-script qui SOLDE la condition par un Patch explicite -------
section("5) garder_reportage() : soldée par Patch explicite -> passe")
apres_solde = aventure_fixture()
apres_solde.trajectoire = [e for e in apres_solde.trajectoire
                           if e.id != "cond-armee-capitale"]
patch = Patch(cible_id="cond-armee-capitale", operation="delete",
             payload="condition résolue en jeu : l'armée a rebroussé chemin",
             cause="table du 2026-01-20, décision Souhel")
erreurs_soldes = garder_reportage(ech.vivantes, apres_solde,
                                  patches_apres=[patch])
assert erreurs_soldes == [], erreurs_soldes

# 6) garde : les déclencheurs etat sont hors périmètre v0 -------------------
section("6) déclencheurs etat hors périmètre garde v0 (documenté)")
# une ConditionVivante ne peut porter que delai/date par construction de
# extraire() ; on vérifie juste que garder_reportage() ne regarde jamais
# ech.etats — l'appelant qui voudrait les protéger doit le faire lui-même.
assert garder_reportage([], aventure_fixture()) == []

print(f"\nOK — {len(FAIT)} sections : " + ", ".join(FAIT))
