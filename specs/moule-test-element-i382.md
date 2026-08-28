# Le MOULE du test d'élément (I-382)

*Registre méta : MRPG-I-382 (vault, hors périmètre de ce repo). Ce fichier
est le résumé opérationnel qui vit dans le repo — l'outillage et le premier
exemplaire sont dans [`tests/fixtures/element_mold.py`](../tests/fixtures/element_mold.py)
et [`tests/test-element-camera.py`](../tests/test-element-camera.py). Le
gabarit de déclinaison pas à pas est dans
[`README-moule-test-element.md`](../README-moule-test-element.md) (racine).*

## Le trou de process que ça comble

On teste le code des briques (mergeable, propre — suites `tests/*_test.py`
existantes) et on teste le bout-en-bout (job `integration` du CI,
`README-ci.md`). Il manquait l'étage entre les deux : **la brique comme
élément joué** — un scénario réduit qui traverse la brique comme le ferait
une vraie partie, avec un verdict mécanique, pas une lecture de code.

## Le contrat du moule

Un test d'élément déclare, dans cet ordre :

1. **Brique visée** — une ligne en tête de fichier : quelle fonction/module
   du repo est sous test (pas « le moteur » en général).
2. **Fixtures d'entrée** — des états synthétiques (D-206/D-109 : jamais de
   matériau de campagne réel, jamais dans un test) construits pour
   provoquer chaque état que la brique doit distinguer.
3. **Scénario réduit joué par un agent-instrument** — le régime D-240 :
   *stimulus bête*, une action fixe et simple, pas un dialogue improvisé
   ni un test de la qualité d'un modèle. Ce repo étant 100 % hors-ligne
   (`CLAUDE.md`, aucun modèle/réseau dans `tests/`), le stimulus est ici le
   texte d'action écrit à la main ; un agent-instrument réel (petit
   modèle, instructions simples) pourrait rejouer le même scénario hors
   CI, sans changer le contrat du moule.
4. **Compteurs de verdict mécaniques** — un `check(nom, condition, détail)`
   par état de fixture, jamais un verdict global fourre-tout ; D-134 :
   jamais de lecture de qualité en petit modèle, une comparaison de
   chaînes/longueurs suffit ou ce n'est pas le bon test.
5. **Borne de coût** — le harnais (`ElementMold`, context manager)
   chronomètre son propre bloc et ajoute un verdict `cout-borne` : un run
   qui dérape (parcourt tout le corpus, boucle) doit échouer, pas tourner.

## L'outillage (`tests/fixtures/element_mold.py`)

- `ElementMold(brique, budget_seconds)` — context manager ; `check(nom,
  condition, détail)` enregistre un verdict ; `report()` affiche les
  compteurs et retourne le verdict global.
- Vérifications mécaniques réutilisables entre briques :
  `absent(sortie, *repères)`, `present(sortie, *repères)`,
  `degraded(rendu_complet, perçu, gardé, perdu)`, `no_markers(sortie,
  *marqueurs)`.
- Vit sous `tests/fixtures/` (pas directement `tests/*.py`) : le glob de
  `run_tests.py` ne ramasse que `tests/*.py`, donc une bibliothèque
  importée n'est jamais exécutée seule comme suite.

## Le premier exemplaire : la caméra (D-184)

`tests/test-element-camera.py` — brique visée : `Store.assemble` /
`Store.lookup` (`coderain/memory.py`) via `mcp_server._assemble_text`, la
brique qui décide ce que le joueur perçoit d'un fait du monde.

| état de fixture | construction | verdict mécanique |
|---|---|---|
| fait hors champ | entrée non déclenchée par l'action jouée | absente de la sortie narrateur |
| fait perçu partiellement | entrée `hidden: true` consultée via `store.lookup()` (canal de rappel, D-082) | titre gardé, corps perdu (dégradé) |
| secret actif | même entrée cachée, déclenchée, assemblée sur le chemin narrateur (`secrets=False`) | zéro marqueur (titre/slug/corps/libellé de section secrète) dans le perçu |

Les fixtures existantes (registre I-226) et la forme « marche de spécimen »
(D-169, matériau synthétique type Toto) ne sont **pas** recréées ici : ce
sont des jeux d'entrée possibles pour de futurs exemplaires du moule, pas un
framework parallèle — le moule les absorbe comme source de fixtures, il ne
les remplace pas.

## Comment lancer

```bash
python tests/test-element-camera.py     # un seul exemplaire
python run_tests.py                     # toute la suite, celui-ci inclus
```

## Décliner sur une autre brique

Voir [`README-moule-test-element.md`](../README-moule-test-element.md).
