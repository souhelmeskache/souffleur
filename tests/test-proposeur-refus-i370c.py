"""I-370c -- le PROPOSEUR personnage+contrat et la boucle de refus (D-232
étapes (3)-(4), D-245 arbitrage discussion immédiate) contre
`coderain/proposeur.py`.

Fixtures 100% synthétiques (D-109) : candidats d'acte et envies joueur
inventés, aucun matériau de campagne réel.

Vérifie le critère de fin de l'Issue #52 :
  1. une proposition ancrée sort (chaque élément pointe un candidat/envie
     connu) ;
  2. un refus simulé DOIT capturer une friction avant toute reproposition --
     une tentative sans friction capturée est refusée (ValueError) ;
  3. une fois la friction capturée, la reproposition informée par elle sort,
     et diffère de la refusée sur ses éléments CENTRAUX (pas un rafistolage) ;
  4. la proposition refusée reste dans l'historique, jamais réécrite ni
     supprimée (trace, D-186/D-232) ;
  5. pas de quota codé en dur -- un second cycle refus/friction/reproposition
     fonctionne exactement pareil ;
  6. le rendu montrable au joueur (`rendu_joueur`) ne fuit aucun id interne,
     aucune ancre_source, aucun statut -- grep spoiler à zéro.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coderain.proposeur import (
    CandidatActe, ElementPropose, EnvieJoueur, Proposition,
    RegistreProposeur, CENTRAL, SECONDAIRE,
    valider, valider_ancrage, rendu_joueur,
)

# ---- matière source synthétique --------------------------------------------

candidats = [
    CandidatActe(id="acte-forge-abandonnee", resume="Une forge à l'abandon."),
    CandidatActe(id="acte-caravane-perdue", resume="Une caravane disparue."),
    CandidatActe(id="acte-pillards-route", resume="Des pillards rôdent sur la route."),
]
envies = [
    EnvieJoueur(id="envie-artisan", texte="Je veux jouer un artisan."),
    EnvieJoueur(id="envie-voyageur", texte="Je veux voyager beaucoup."),
]
registre = RegistreProposeur()

# ---- 1) première proposition, ancrée -------------------------------------

p1 = Proposition(
    id="prop-1",
    personnage=[
        ElementPropose(label="role", texte="Un forgeron itinérant",
                       ancre_source="acte-forge-abandonnee", portee=CENTRAL),
    ],
    contrat=[
        ElementPropose(label="clause_centrale",
                       texte="Reforger l'outil perdu dans la forge abandonnée",
                       ancre_source="acte-forge-abandonnee", portee=CENTRAL),
        ElementPropose(label="clause_secondaire",
                       texte="Réapprovisionner en minerai en chemin",
                       ancre_source="envie-artisan", portee=SECONDAIRE),
    ],
)
assert valider(p1) == [], f"p1 devrait être valide: {valider(p1)}"
assert valider_ancrage(p1, candidats, envies) == [], \
    "p1: chaque ancre_source doit pointer un candidat/envie connu"
registre.proposer(p1)
assert registre.derniere() is p1
print("1) première proposition ancrée acceptée dans le registre")

# ---- 2) reproposition SANS friction capturée -> refusée --------------------

registre.refuser("prop-1")
assert registre.derniere().statut == "refusee"

p2_aveugle = Proposition(
    id="prop-2-aveugle",
    personnage=[ElementPropose(label="role", texte="Un caravanier",
                                ancre_source="acte-caravane-perdue",
                                portee=CENTRAL)],
    contrat=[ElementPropose(label="clause_centrale",
                             texte="Retrouver la caravane disparue",
                             ancre_source="acte-caravane-perdue",
                             portee=CENTRAL)],
)
try:
    registre.proposer(p2_aveugle)
    raised = False
except ValueError:
    raised = True
assert raised, "une reproposition sans friction capturée doit être refusée (D-245)"
assert p2_aveugle not in registre.propositions, \
    "une proposition rejetée par le garde ne doit pas entrer dans l'historique"
print("2) reproposition à l'aveugle (sans friction capturée) refusée")

# ---- 3) capture de la friction, puis reproposition informée et DIFFÉRENTE -

friction = registre.capturer_friction(
    "prop-1", "le joueur ne veut pas d'un personnage sédentaire (forge) --"
              " il veut du mouvement")
assert friction.proposition_refusee_id == "prop-1"
assert friction in registre.frictions

p2 = Proposition(
    id="prop-2",
    personnage=[
        ElementPropose(label="role", texte="Un caravanier chevronné",
                       ancre_source="acte-caravane-perdue", portee=CENTRAL),
    ],
    contrat=[
        ElementPropose(label="clause_centrale",
                       texte="Retrouver la caravane disparue sur la route",
                       ancre_source="acte-caravane-perdue", portee=CENTRAL),
        ElementPropose(label="clause_secondaire",
                       texte="Négocier avec les voyageurs croisés en chemin",
                       ancre_source="envie-voyageur", portee=SECONDAIRE),
    ],
    friction_source_id=friction.id,
)
assert valider(p2) == []
assert valider_ancrage(p2, candidats, envies) == []
registre.proposer(p2)
assert registre.derniere() is p2
assert p1.centraux().isdisjoint(p2.centraux()), \
    "la reproposition doit différer de la refusée sur ses éléments centraux"
print("3) friction capturée puis reproposition informée et centralement "
      "différente acceptée")

# ---- 4) la proposition refusée reste tracée, jamais réécrite --------------

assert p1 in registre.propositions
assert p1.statut == "refusee"
assert p1.personnage[0].texte == "Un forgeron itinérant", \
    "la proposition refusée ne doit jamais être réécrite"
print("4) la proposition refusée reste en trace, inchangée")

# ---- 5) pas de quota -- un second cycle refus/friction/reproposition marche

registre.refuser("prop-2")
try:
    registre.proposer(Proposition(
        id="prop-3-aveugle",
        personnage=[ElementPropose(label="role", texte="x",
                                   ancre_source="acte-forge-abandonnee",
                                   portee=CENTRAL)]))
    raised2 = False
except ValueError:
    raised2 = True
assert raised2, "le garde s'applique identiquement au second refus (pas de quota)"

friction2 = registre.capturer_friction(
    "prop-2", "le joueur voulait de la caravane mais pas du négoce -- il "
              "veut de l'action, pas de la diplomatie")
p3 = Proposition(
    id="prop-3",
    personnage=[ElementPropose(label="role", texte="Un éclaireur solitaire",
                               ancre_source="acte-caravane-perdue",
                               portee=SECONDAIRE)],
    contrat=[ElementPropose(label="clause_centrale",
                            texte="Traquer les pillards de la route",
                            ancre_source="acte-pillards-route",
                            portee=CENTRAL)],
    friction_source_id=friction2.id,
)
assert p2.centraux().isdisjoint(p3.centraux())
registre.proposer(p3)
assert registre.derniere() is p3
assert len(registre.propositions) == 3  # p1, p2, p3 -- p2_aveugle jamais entrée
assert len(registre.frictions) == 2
print("5) aucun quota codé en dur -- un second cycle refus/friction/reproposition"
      " fonctionne à l'identique")

# ---- 6) rendu joueur : zéro spoiler (ids internes, ancres, statuts) -------

sortie = rendu_joueur(p3)
spoiler_markers = (
    "prop-1", "prop-2", "prop-3", "acte-forge-abandonnee",
    "acte-caravane-perdue", "acte-pillards-route", "envie-artisan",
    "envie-voyageur", "ancre_source", "friction", "refusee", "en_attente",
    "retenue",
)
for marker in spoiler_markers:
    assert marker not in sortie, f"fuite spoiler dans le rendu joueur: {marker!r}"
assert "Traquer les pillards de la route" in sortie
assert "Un éclaireur solitaire" in sortie
print("6) rendu joueur exempt de tout id interne / ancre_source / statut")

print("ALL OK -- test-proposeur-refus-i370c.py")
