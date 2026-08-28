# README-moule-test-element.md — décliner le moule (I-382)

*Doctrine complète : [specs/moule-test-element-i382.md](specs/moule-test-element-i382.md).
Outillage : [tests/fixtures/element_mold.py](tests/fixtures/element_mold.py).
Premier exemplaire : [tests/test-element-camera.py](tests/test-element-camera.py).*

## Gabarit en 5 étapes

Pour tester une brique `<ma-brique>` comme élément joué, créer
`tests/test-element-<ma-brique>.py` :

1. **Nommer la brique** en tête de docstring — la fonction/module exact
   sous test (import direct, pas « le moteur » en général).

2. **Construire les fixtures d'entrée** — matériau 100 % synthétique
   (D-109/D-206, jamais de module réel). Autant de fixtures que d'états
   que la brique doit distinguer.

3. **Écrire le stimulus bête** — une action fixe, écrite à la main, qui
   traverse la brique une fois. Pas de dialogue improvisé, pas de boucle,
   pas de dépendance modèle/réseau (suite de test = hors-ligne,
   `CLAUDE.md`).

4. **Envelopper dans `ElementMold`** et enregistrer un verdict mécanique
   par état de fixture :

   ```python
   from tests.fixtures.element_mold import ElementMold, absent, present

   with ElementMold("ma-brique", budget_seconds=5.0) as mold:
       sortie = ma_brique(fixture, ACTION)
       mold.check("etat-1-nom", absent(sortie, "repère à ne pas voir"),
                   "détail court expliquant le verdict")
       mold.check("etat-2-nom", present(sortie, "repère attendu"))

   assert mold.report(), "au moins un verdict a échoué"
   ```

5. **Vérifier avant/après** :

   ```bash
   python tests/test-element-<ma-brique>.py   # l'exemplaire seul
   python run_tests.py                        # toute la suite reste verte
   ```

## Règles qui ne se négocient pas

- **Un `check()` par état de fixture**, jamais un `assert` global — le
  compteur affiché (`report()`) doit dire lequel a échoué.
- **Verdict mécanique, jamais une lecture de qualité** (D-134) : substring
  présent/absent, égalité, comparaison de longueur. Si la seule façon de
  juger est de « lire si c'est bien écrit », ce n'est pas un test
  d'élément, c'est autre chose.
- **Fixtures synthétiques uniquement** (D-206/D-109) : jamais de matériau
  de campagne réel, même tronqué, même en commentaire.
- **Réutiliser les fixtures existantes** (registre I-226) et la forme
  « marche de spécimen » (D-169) comme *source* de jeux d'entrée avant
  d'en inventer de nouveaux — le moule les absorbe, il ne les duplique pas.
- Le fichier de la brique testée va dans `tests/test-element-<brique>.py`
  (ramassé par `run_tests.py`) ; toute bibliothèque partagée entre
  exemplaires va sous `tests/fixtures/` (pas ramassée par le glob).
