# CADRAGE — I-150 : tension plafond (D-076) vs prose (D-079) sur le poste narrateur

*Lane `lane-10`, Issue [#10](https://github.com/souhelmeskache/souffleur/issues/10).
Fiche source : `specs/moisson-2026-08.md` item #10 (I-150). Décisions référencées
(`D-076`, `D-079`, `D-091`/`D-095`, `I-145`, `I-100`) vivent dans le vault
`C:\Vaults\MVP2\meta-rpg\`, hors périmètre de ce repo — ce document ne prétend
pas en reproduire le contenu ni les trancher ; il cadre la tension telle que
formulée par l'Issue et prépare le terrain d'un bench à coût quasi nul.*

## 1. Le poste concerné

Coderain sépare deux rôles de modèle par tour (voir `coderain/models.py`,
commentaire « one model can serve Director AND Writer ») :

- **Director** — arbitre les règles, l'état, les jets.
- **Writer** (= « poste narrateur ») — produit la prose vue par la joueuse ou
  le joueur, sous les règles de `WRITER_RULES` (`coderain/templates.py`) :
  voix, immersion, détail sensoriel, longueur, continuité.

C'est le poste Writer qui est en jeu ici : c'est lui que la prose (D-079)
qualifie, et lui que le plafond (D-076) borne.

## 2. La tension telle que formulée par l'Issue

Deux décisions déjà actées se recoupent sur ce poste sans coïncider
totalement :

- **D-076 (plafond/frontière)** — fixe une limite de puissance/coût de
  modèle autorisée pour le déploiement standard (au sens large : tous
  postes, tous profils).
- **D-079 (choix de prose)** — fixe quel modèle sert de référence pour la
  qualité de prose attendue au poste Writer.

L'Issue #10 indique que ces deux lectures ne coïncident pas complètement
sur le poste narrateur : le modèle qui satisferait le mieux D-079 (qualité
de prose) peut se situer au-dessus, en-deçà, ou à côté du plafond fixé par
D-076 — et « 2/3 lectures » du poste narrateur sont déjà tranchées côté
vault, la troisième restant ouverte. Le contenu exact de ces deux décisions
et la lecture qui reste ouverte ne sont pas dans ce repo ; ils sont
consignés côté vault (D-091/D-095, tranchées, apportent le contexte
frontière/puissance associé).

## 3. Ce que cette lane livre — et ce qu'elle ne livre pas

**Livré ici** :

- ce cadrage (contexte, terminologie, portée) ;
- un protocole de bench à coût quasi nul (`bench/bench-prose-i150.md`) pour
  mesurer si un modèle « frontière » (au sens de `coderain/models.py` —
  ex. les entrées notées « frontier prose » dans `BYO_ALTERNATIVES`) apporte
  un grain de prose perceptiblement distinct sur le poste Writer, comparé au
  modèle actuellement retenu par D-079 ;
- une garde de test hors-ligne (`tests/test-bench-prose-i150.py`) qui
  vérifie la présence et la forme de ce protocole — comme le reste de la
  suite (`run_tests.py`), zéro appel modèle réel, zéro réseau.

**Non livré ici** (hors périmètre lane, arbitrage méta/vault) :

- le contenu ou la modification de D-076 ou D-079 ;
- le verdict de la troisième lecture du poste narrateur ;
- l'exécution effective des appels modèle du bench (coût réel, même
  quasi nul, sort du hors-ligne garanti par ce repo — voir `README-ci.md`) :
  le protocole est prêt à jouer manuellement par un mainteneur muni d'une
  clé API, résultats à consigner ensuite dans le même fichier de bench.

## 4. Coût quasi nul — ce que ça veut dire ici

« Coût quasi nul » se mesure comme `TokenMeter` le fait déjà pour le
convertisseur (I-145, `coderain/converter/convert.py`) : compter les appels
et les caractères réellement envoyés plutôt que d'estimer. Le protocole de
bench (§ ci-dessous) limite volontairement le nombre de prompts et de
modèles comparés pour rester dans cet esprit — pas un run automatisé, un
échantillon resserré, journalisé à la main.

## 5. Suite

Voir [`bench/bench-prose-i150.md`](../bench/bench-prose-i150.md) pour le
protocole et le tableau de résultats (à remplir lors de l'exécution
manuelle), et [`tests/test-bench-prose-i150.py`](../tests/test-bench-prose-i150.py)
pour la garde de structure hors-ligne.
