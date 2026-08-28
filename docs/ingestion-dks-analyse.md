# INGESTION « DEATH KNIGHT'S SQUIRE » — passe d'analyse v0 (2026-08-25)

*Rapport-forme de la lane `ingestion-dks-analyse`, fiche
[`FICHE-ingestion-dks-analyse-2026-08-25`](../../../Vaults/MVP2/Migration%20Coderain/FICHE-ingestion-dks-analyse-2026-08-25.md)
(mandat [`I-328`](../../../Vaults/MVP2/meta-rpg/registre-items/MRPG-I-328-nouveau-module-death-knights-squire.md),
PV porteur [`H-249`]). MODE ANALYSE : formes et chiffres uniquement, aucun contenu de partition
(`D-109`). Commit travail : **`9742a84d39c136cde8de141c9650a9785086a516`** (fixture de structure
synthétique — le matériau réel vit hors git, voir §5).*

---

## 1. Extraction texte (livrable 1)

Source : PDF 11 141 159 octets, sha256 `6adfffed0264f3abf92314b84f59d833c5133c65033cd81dd0ffe1c8509e272e`,
117 pages (pypdf 6.16.2). Outil reproductible déposé au poste :
`corpus-modules/death-knights-squire/outils/extraire_texte.py`.

| mesure | valeur |
|---|---|
| caractères extraits | **234 151** (~2 001/page) |
| pages avec couche texte exploitable | **116/117 (99,1 %)** |
| pages hors section cartes exploitables | **98/99 (99,0 %)** |
| pages image seules (cartes) | p100–117 (étiquettes `TILEPAGE/SUB-MAP N` seules dans le calque) |
| anomalie d'encodage | p1 uniquement : police de couverture sans CMap ToUnicode, décalage constant **+0x1D** (« The Death Knight's Squire » décodable mécaniquement) |
| caractères hors ASCII imprimable | 2 044 / 235 395 — typographie réelle du document (puces U+2666 ×621, apostrophes U+2019 ×299, guillemets courants), **zéro corruption** |

Texte structuré par section déposé au poste sous `extraction/sections/` (7 sections,
marqueurs `[p.N]` conservés comme ancres) + brut par page (`extraction/texte-par-page/`) ;
toutes les mesures machine dans `extraction/mesures-extraction.json`.

Structure détectée : gamebook DM-less à **entrées nommées** (CAPS + renvois
« go to entry X ») — la route déterministe S1 (`#N` numérotés, `s1_local.py`)
du spécimen ne s'applique pas telle quelle. Sections : règles solo intégrées
p4–8 · backstory p8–9 · aventure p10–81 · pointeurs tilepage/sub-map p82–98 ·
booklet de cartes p99–117.

## 2. Inventaire des statblocks (livrable 2)

Ancrage testé contre `dnd5e-srd-data==0.3.0` (341 monstres embarqués).

**13 occurrences → 10 distincts. Ratio de collision règles-convertisseur :
6 SRD direct · 1 variante SRD · 3 custom (60 % d'ancrage direct).**

| verdict | statblocks |
|---|---|
| SRD direct (6) | `cultist` (p23, 33), `goblin-warrior` (p37), `kobold-warrior` (p45), `skeleton` (p65), `giant-wolf-spider` (p67), `zombie` (p80) |
| Variante SRD (1) | forest-bat ≈ `bat`/`giant-bat` + delta à documenter (p49) |
| Custom (3) | darek-brewmont (PNJ allié combattant, p15) · giant-centipede (p18 — présent du SRD 5.1 canonique mais ABSENT du dataset) · death-knight (antagoniste récurrent p30, 42, 72, 80) |

Collisions relevées : PV persistants inter-rencontres sur le death knight
(« minus dmg already caused » p30) — état qui survit ENTRE les combats, hors
frontière moteur D-200 actuelle ; format non canonique (« Armour Class »,
« CR 1 (200XP) », Proficiency Bonus explicite) ; encounters multi-tokens.
Chaque custom deviendra un record kit à ancre propre à la passe suivante.

## 3. Inventaire des cartes (livrable 3)

**19 pages-cartes** (p99–117, A4 paysage), chacune UNE image JPEG pleine page
(`DCTDecode`, ~902 px de large) : 1 couverture booklet + **12 TILEPAGE**
(p100–111) + **5 SUB-MAP** (p112–116) + **1 carte dessinée** (p117).

- Format réalisable : **export direct du XObject, zéro OCR, zéro traitement
  d'image** (I-328 tenu : jamais lues comme texte).
- Rattachement proposé : ressource attachée au node spatial du pointeur
  correspondant (chaque page-pointeur p82–98 devient un node portant sa carte) ;
  carte dessinée rattachée à l'entrée narrative qui la remet au joueur.
- Références depuis le texte de l'aventure : tilepages 1→7, 2→6, 3→20, 4→13,
  5→13, 6→15, 7→10, 8→16, 9→5, 10→4, 11→2, 12→2 mentions (113 au total).
- Illustrations décoratives (1–3 images/page de texte) : hors périmètre v0.

## 4. Cartographie vers le schéma kit (livrable 4)

Couvert par le schéma Partition v0.3.0 : nodes scene/read_aloud (entrées),
`debouches` (choix conditionnels, D-118 amendée), `charniere_sortie` (D-123),
records creature/pnj/objet, RollTable (table d100 chance rolls p5, plages
contiguës OK), Secret (candidats révélations tardives), Evenement trajectoire/
conditions (D-178/D-182 — la trajectoire « si personne n'intervient » est
explicite dans la backstory), étage aventure complet.

**Écarts nommés (nouveaux types de records nécessaires) :**

| # | écart | proposition forme |
|---|---|---|
| E1 | ressource carte rattachée à un node | primitive `Ressource` {id, fichier, format, node_rattache_id} ou champ `cartes[]` |
| E2 | état persistant inter-combats (PV du death knight) | record à état ou convention patches D-132 — arbitrage frontière moteur/partition (D-200) |
| E3 | encounters multi-tokens + PNJ allié non-SRD | records de rencontre (groupe, tokens initiaux, allié) |
| E4 | instructions procédurales spatiales (placement/direction de lecture) | acceptable en corps_md v0 ; type dédié si géométrie jouable voulue |
| E5 | règles solo auto-gérées (section character creation) | hors kit : instructions globales du scénario installé |

Santé du graphe de renvois : 457 cibles brutes → 431 résolues sur **341 entrées
définies** (287 distinctement ciblées) ; 23 non résolues après recollage
mécanique dont la grande majorité = coupures de ligne du PDF (BLES→BLESSING…).
À recoller avant émission : validate_form refuse tout dangling link.

## 5. Estimation chiffrée de la conversion complète (livrable 5)

Volume : 234 151 caractères · 341 entrées · 457 renvois · 10 statblocks ·
9 combats · 62 jets DC · 32 skill checks · 4 d100 · 13 checks pièges ·
11 gains d'objets · 9 montants gp · 19 cartes.

Passes prévues :

1. **P-conv-0 socle formes** — recollage renvois, segmentation S2 des pointeurs,
   nodes verbatim (341) + table d100 ;
2. **P-conv-1 records** — 10 records dont 3 customs complets + variante,
   collisions instruites record par record ;
3. **P-conv-2 événements & secrets** — trajectoire, conditions, charnière ;
4. **P-conv-3 cartes** — export 19 JPEG + primitive E1 + rattachement ;
5. **P-val validation bout-en-bout** — validate_form/fidelity + doctor.

Points de décision méta/Souhel attendus :

- **D1** route déterministe locale « entrées nommées » (esprit s1_local, zéro
  hallucination) vs route LLM générale (~700 appels estimés au TokenMeter I-145).
  Écrire cette route = code convertisseur ⇒ SORT du P1 de la présente passe
  (livrable 6 : STOP/remontée appliqué — décision demandée).
- **D2** acte méta pour E1 (le schéma est figé par décisions).
- **D3** arbitrage E2 record à état vs patches D-132.
- **D4** politique des 19 cartes : poste uniquement (D-178) — chemins hors-git
  référencés par la partition ; à fixer avant install.

Risques : R1 renvois tronqués ~5 % (détection garantie par validate_form) ;
R2 mots coupés du layout deux-colonnes (ancres byte-exact, lisibilité brute
dégradée) ; R3 champs de statblock sans table → exceptions signalées, jamais
improvisées (I-111) ; R4 combat final partiellement en passe moteur sans D2/D3 ;
R5 volume LLM si route générale.

## 6. Suites vertes avant/après (livrable 6)

**42/42 suites locales AVANT et APRÈS** (run_tests.py, ALL SUITES PASSED ;
trinity_test inclus localement, exclu CI I-270 échec préexistant recensé).
Aucun changement de code produit pendant la passe.

## 7. Dépôt et écarts de protocole consignés

- Dépôt disque (P1) au poste, à l'époque de cette session : `C:\Users\souhe\coderain-ingestion-dks-analyse\corpus-modules\death-knights-squire\`
  (README, outil d'extraction, extraction/ 117 pages + 7 sections, mesures JSON,
  inventaires json+md ×2, cartographie, estimation). Ce dossier était
  **gitignoré par le dépôt lui-même** (`.gitignore` ligne 22, matériau de
  campagne — D-178, cohérent avec cli.py « no material ever enters git ») :
  il ne pouvait pas remonter par commit sans forcer outre une politique explicite.
  *Mise à jour 2026-08-28 (phase 1 assainissement) : le corpus a depuis été
  déplacé hors du repo moteur vers le dépôt privé dédié `ttrpg-corpus` ; le
  chemin ci-dessus est un repère historique, plus l'emplacement actuel — voir
  `coderain/config.py:corpus_dir()`.*
  Le commit porte donc la **forme seule** : fixture synthétique 100 %
  `tests/fixtures/module-fixture-gamebook-s2.txt` (prévue par la fiche :
  « tests\fixtures\ — fixtures de structure si besoin »), zéro contenu réel.
- Le PDF source n'a jamais été modifié ; rien hors P1 touché
  (`git diff --name-only main...HEAD` = la fixture + ce rapport).
- Écart consigné : branche/worktree annoncés « déjà en place » étaient ABSENTS
  à l'arrivée (`git worktree list` sans lane, branche inexistante) ; création
  manuelle selon la convention exacte du README-nouvelle-lane
  (`git worktree add ..\coderain-ingestion-dks-analyse -b ingestion-dks-analyse main`).
