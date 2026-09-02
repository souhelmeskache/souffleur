# README-ci.md — le CI de la boucle (D-189)

*Installé par la lane `ci-integration-continue` le 2026-08-23, fiche
`FICHE-ci-integration-continue-2026-08-23` (vault). Un workflow, deux jobs.*

## Ce que fait le CI

| job | déclencheur | contenu |
|---|---|---|
| **tests** (gate) | tout push (toutes branches) + `main` | chaque `tests/*.py` est un script autonome lancé avec Python 3.14 sur Windows ; **sans exclusion** (`trinity_test.py` compris : son profil de connexion est déclaré hermétiquement dans le test depuis I-270, commit `0cb07c6`) |
| **integration** | `main` uniquement, après job 1 vert | bout-en-bout **hors-ligne** : conversion déterministe (route S1) de la fixture 100 % synthétique `tests/fixtures/module-fixture-s1.txt`, puis vérifications verdict VERT / hash manifest / comptages / couverture exacte. Aucun secret, aucun réseau, aucun matériau réel |

## Comment lire un rouge

1. Onglet **Actions** → clic sur le run → job en rouge.
2. Le log du step fautif montre les suites `FAILED: ...`.
3. **Artefacts** (en bas de la page du run) : `logs-<branche>-<run>` contient la
   sortie complète des suites échouées. C'est ce fichier que lit le triage.

## La règle du gate

Une branche ne merge sur `main` que si son run est **vert**
(aucun échec préexistant recensé depuis I-270). Un test cassé poussé sur une
branche ⇒ run rouge + artefact ; c'est la preuve que le gate mord.
La branch protection côté GitHub (réglage console, geste de Souhel) transforme
cette règle en interdiction technique.
