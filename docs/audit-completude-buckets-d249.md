# AUDIT DE COMPLÉTUDE DES BUCKETS — D-249 (2026-08-29)

*Rapport de la lane Issue #53 (registre méta MRPG-D-249). Question posée : la
Partition (spec D-175) sait-elle accueillir TOUT le matériel typique d'une
campagne D&D publiée ? Audit seul — aucune modification de production, aucun
matériau réel ouvert (raisonnement sur la typologie générique des campagnes
publiées). Critère d'inclusion : D-141 « est-ce que ça change en jeu ? »
(`coderain/converter/buckets.py:1-26`).*

---

## 1. La liste RÉELLE des buckets (ancrée)

L'Issue parle de « six primitives » ; l'état réel du schéma en compte **onze,
plus l'étage aventure** — les décisions D-178/D-182/D-216/D-218/D-219 ont déjà
étendu le socle D-175. La liste qui fait foi est `schemas.py` (docstring
`coderain/converter/schemas.py:1` encore daté « six primitives » — à
rafraîchir un jour, hors périmètre ici).

| # | primitive / bucket | ancre | contenu |
|---|---|---|---|
| 1 | **Manifest** | `coderain/converter/schemas.py:141-157` | identité du module, corpus cible 5e (D-174) |
| 2 | **Node** (prose) | `coderain/converter/schemas.py:160-223` ; types `chapitre/section/scene/read_aloud` `schemas.py:15` ; altitudes `scene/scenario/adventure` `schemas.py:18` | corps verbatim ancré, liens conditionnels, `charniere_sortie` (D-123) `schemas.py:194`, rubriques scénario `objectif_md/debouches/heritage` `schemas.py:195-201` |
| 3 | **Record** (5 classes `creature/pnj/objet/lieu/faction`) | `coderain/converter/schemas.py:20,226-353` ; champs par classe `coderain/converter/annexe_a.py:9-15` + [annexe-a-stats-5e.md](annexe-a-stats-5e.md) | clés réservées `ancre_srd/delta_vs_ancre/tokens_initial/persistent` `schemas.py:245` |
| 4 | **RollTable** | `coderain/converter/schemas.py:356-377` | dé `NdM` obligatoire `schemas.py:360-361`, plages contiguës ; pioche moteur `coderain/converter/aval.py:116` |
| 5 | **Secret** (épistémique, D-019) | `coderain/converter/schemas.py:379-397` | porteurs, révélation, conséquence si brûlé ; garde caméra D-184 `coderain/converter/validate_form.py:183-196` |
| 6 | **Patch** (D-132) | `coderain/converter/schemas.py:604-610` | mutation adressée, jamais une réécriture |
| 7 | **Evenement + Aventure** (D-178/D-182) | `coderain/converter/schemas.py:614-767` | trajectoire/conditions, déclencheurs `delai/etat/date` `schemas.py:36`, charnière `schemas.py:699` |
| 8 | **Tension** (D-218) | `coderain/converter/schemas.py:400-435` ; 6 codes `schemas.py:25` | menace/horloge/échéance/coût/choix/révélation |
| 9 | **Ressource** (D-216 §2) | `coderain/converter/schemas.py:438-486` | « générique par construction » `schemas.py:439-447` — mais `RESSOURCE_TYPES = ("carte",)` seul `schemas.py:30` |
| 10 | **Personnage** + destinée (I-341/D-219/D-220) | `coderain/converter/schemas.py:489-546` | sortie de l'ingestion, jalons flous rattachables |
| 11 | **Fenetre** (I-033/D-219) | `coderain/converter/schemas.py:549-601` | 4 dimensions de la conversation d'accord |

Transverses qui comptent pour l'audit :

- **Triage D-141** codé dans le prompt de bucketing : `change-en-jeu` /
  `consulte-a-froid` / `mixte` — `coderain/converter/buckets.py:16-26`.
- **Visibilité** : `mj_only` à l'unité segmentée `schemas.py:127,138`
  (`coderain/converter/segmentation.py:27` « DM-only sidebars ») ; régime
  dérivé, pas autoral : « hidden = routing, not deletion […] the camera stays
  perception » `coderain/converter/projection.py:12-13`. Le tout-privé-par-
  défaut demandé par D-249 est donc DÉJÀ la mécanique en place.
- **Checks indexés** : `aval.CHECK_RE` `coderain/converter/aval.py:20`
  (extension au phrasé réel des DC = remontée P-CONV-1,
  [pconv0-socle-formes.md](pconv0-socle-formes.md) §4.3).
- **Système complet (grille D-249)** : `emit.write_partition` crée déjà TOUS
  les dossiers de buckets, même vides —
  `coderain/converter/emit.py:74-75` (`nodes, records, tables, secrets,
  patches, tensions, resources, personnages, fenetres`). L'exigence « tous
  les buckets existent dans toutes les campagnes converties » est satisfaite
  par construction ; elle restera vraie pour tout type ajouté à une primitive
  existante (aucun dossier nouveau requis pour les extensions proposées §3).

## 2. Inventaire du matériel typique × couverture × verdict

Typologie construite depuis la structure générique des campagnes D&D publiées
(chapitres d'aventure à lieux clés, appendices de monstres/objets/sorts,
booklet de cartes, handouts, tables) — sans ouvrir le matériau du projet.
Verdicts : **COUVERT** (primitive directe), **COMPOSITION** (couvert par
assemblage de primitives existantes), **TROU** (proposition §3),
**HORS-PARTITION** (justifié D-141).

| # | matériel | couverture | verdict |
|---|---|---|---|
| 1 | Texte encadré à lire à voix haute | node `read_aloud` `schemas.py:15` ; réingestion PAR FONCTION (grille D-249) via `transverse.fonction/charge` du Record `schemas.py:268-275` (un dialogue informe comment jouer le PNJ) | **COUVERT** — la consigne de conversion « fonction, pas format » est une règle de passe, pas un manque de schéma |
| 2 | Prose descriptive, lore, background | nodes `chapitre/section/scene` `schemas.py:15,160` ; consulté-à-froid `buckets.py:19-20` | **COUVERT** |
| 3 | Statblocks de monstres | record `creature` + `ancre_srd`/`delta_vs_ancre` `schemas.py:245,279-302` ; champs [annexe-a-stats-5e.md](annexe-a-stats-5e.md) §1 | **COUVERT** |
| 4 | PNJ (rubriques narratives + combat) | record `pnj` `schemas.py:20`, annexe A §2 (combat = sous-ensemble creature) | **COUVERT** |
| 5 | Factions / organisations | record `faction`, annexe A §5 (`membres`, `posture_envers_joueur`) | **COUVERT** |
| 6 | Lieux à clé (keyed areas) | node `scene` + record `lieu` (`habitants`, `pieges_md`) annexe A §4 | **COUVERT** |
| 7 | Rencontres placées (groupes, poses de jetons) | `tokens_initial` E3 `schemas.py:304-334`, garde zéro-dangling `emit.py:27-32` | **COUVERT** |
| 8 | Tables aléatoires (rencontres, rumeurs, trinkets, d100) | `RollTable` `schemas.py:356` ; pioche moteur `aval.py:116` — moteur ET matière, conforme grille D-249 | **COUVERT** |
| 9 | Tables de CONSULTATION non aléatoires (prix, DC par obstacle, temps de voyage) | aucune primitive : `RollTable` exige un dé `NdM` `schemas.py:360-361` | **TROU mineur** → §3.4 |
| 10 | Cartes et plans (booklet, tilepages) | `Ressource` type `carte` `schemas.py:30,438-486`, poste uniquement (D-217) | **COUVERT** |
| 11 | Handouts — documents à MONTRER (lettres, journaux, affiches) | rien : `RESSOURCE_TYPES = ("carte",)` `schemas.py:30` ; ça change en jeu (remis au joueur, relisible, indice) | **TROU** → §3.1 |
| 12 | Illustrations à montrer (révélation d'une scène/créature) | rien (même constat que #11) ; décoratif exclu ligne 13 | **TROU** (jumeau de #11) → §3.1 |
| 13 | Illustrations décoratives | ne change rien en jeu ; déjà tranché « hors périmètre » [ingestion-dks-analyse.md](ingestion-dks-analyse.md):69 | **HORS-PARTITION** (D-141) |
| 14 | Chronologies / timelines de campagne | `Aventure.trajectoire` + `Evenement` déclencheurs `delai/etat/date` `schemas.py:36,614-767` — la chronologie publiée EST une trajectoire « si personne n'intervient » | **COUVERT** |
| 15 | Secrets, encarts MJ, révélations tardives | `Secret` `schemas.py:379-397` + `mj_only` `schemas.py:127` + garde D-184 `validate_form.py:183-196` | **COUVERT** |
| 16 | Énigmes / puzzles | présentation = node (+ Ressource si visuel), solution = `Secret` (statut, `revelation.declencheur`, `consequence_si_brule` `schemas.py:391-393`) ; procédural spatial = E4 « acceptable en corps_md » [ingestion-dks-analyse.md](ingestion-dks-analyse.md):87 | **COMPOSITION** |
| 17 | Pièges | `lieu.pieges_md` annexe A §4 s1 (ancre SRD Traps) + objet destructible annexe A §3 | **COUVERT** |
| 18 | Objets mondains, trésor monétaire | record `objet` annexe A §3 ; montants gp verbatim dans les corps (mesurés [pconv0-socle-formes.md](pconv0-socle-formes.md) §5) | **COUVERT** |
| 19 | Objets MAGIQUES | trou documenté par l'annexe elle-même : « Les objets magiques ne sont pas couverts » [annexe-a-stats-5e.md](annexe-a-stats-5e.md):339-341 | **TROU** → §3.2 |
| 20 | Sorts nouveaux (appendices de campagne) | aucune classe : `RECORD_CLASSES` `schemas.py:20` n'a pas `sort` ; un sort change en jeu (liste des lanceurs, effets) | **TROU** → §3.3 |
| 21 | Règles spéciales de campagne (poursuite, folie, solo, downtime maison) | précédent E5 : « hors kit : instructions globales du scénario installé » [ingestion-dks-analyse.md](ingestion-dks-analyse.md):88 — la règle vit côté moteur/scénario installé, la Partition porte la matière | **HORS-PARTITION** (E5, cohérent D-141 : c'est le moteur qui change le jeu, pas une donnée piochable) |
| 22 | Options joueur inédites (backgrounds, dons, sous-classes) | la construction du personnage est une SORTIE de l'ingestion via `Personnage`/`Fenetre` `schemas.py:489-601` ; une option de construction n'est pas de la matière d'aventure | **HORS-PARTITION** v0 (remontée méta si un module converti en dépend mécaniquement) |
| 23 | Accroches / débuts alternatifs | `debouches` (D-118 amendée) `schemas.py:77-91` + `Fenetre` F1-F4 | **COUVERT** |
| 24 | Synopsis / background d'aventure | nodes + backstory → trajectoire ([ingestion-dks-analyse.md](ingestion-dks-analyse.md):77-78) | **COUVERT** |
| 25 | Table des matières, crédits, licence, index | ne change rien en jeu | **HORS-PARTITION** (D-141) |
| 26 | Guides de prononciation, glossaires | ne change rien en jeu (au mieux corps_md d'un node si collé à la prose) | **HORS-PARTITION** (D-141) |
| 27 | Conseils au MJ (« running this adventure », intentions dramatiques) | réingérés par fonction : `transverse` fonction/charge/agenda/portee `schemas.py:268-275` + `Tension` 6 codes `schemas.py:25,400-435` | **COMPOSITION** |
| 28 | Conclusion / « further adventures » | `charniere_sortie` (D-123, jamais une fin) `schemas.py:194`, `Aventure.charniere_md` `schemas.py:699` | **COUVERT** |

## 3. Les trous et leurs propositions

Constat central : **aucun trou n'exige une nouvelle primitive.** La Ressource
a été posée « générique par construction » précisément pour ça
(`schemas.py:439-447`) ; les quatre trous sont des EXTENSIONS de primitives
existantes — chacune un acte méta (le schéma est figé par décisions), aucune
implémentée ici.

### 3.1 Handouts + illustrations montrables (lignes 11-12) — extension `RESSOURCE_TYPES`

Étendre `RESSOURCE_TYPES` (`schemas.py:30`) de `("carte",)` à
`("carte", "document", "illustration")`. Toute la mécanique existe déjà :
ancrage `node_id|page`, `fichier` côté poste jamais dans git (D-217),
`description_md`, ancres sources, garde zéro-dangling `emit.py:54-58`.
Visibilité : rien à ajouter — tout-privé-par-défaut, la remise au joueur est
une DÉRIVATION au moment du besoin (même régime que la caméra,
`projection.py:12-13`) ; le déclencheur de remise, quand la source le
conditionne, est un `Secret` dont le contenu pointe la ressource (composition,
pas nouveau champ). Un handout textuel garde son texte verbatim en
`description_md` ancrée ; le fichier image reste au poste.

### 3.2 Objets magiques (ligne 19) — extension de la classe `objet`

Champs optionnels à ajouter à l'annexe A §3 (ancre racine SRD 5.1 › Magic
Items) : `rarete`, `attunement`, `effets_md`, `charges`. Les charges qui se
dépensent rejoignent la mécanique `persistent` déjà posée
(`schemas.py:336-353`) — un état qui survit aux frontières de combat. Décision
déjà réservée par l'annexe : « une extension éventuelle est une décision
séparée » ([annexe-a-stats-5e.md](annexe-a-stats-5e.md):341).

### 3.3 Sorts nouveaux (ligne 20) — 6e classe de record `sort`

Ajouter `sort` à `RECORD_CLASSES` (`schemas.py:20`) + sa table annexe A
(ancre racine SRD 5.1 › Spellcasting : niveau, école, incantation, portée,
composantes, durée, effet_md). Fréquence faible dans les campagnes publiées
mais présence réelle (appendices) ; sans classe, un sort inédit n'a aucune
ancre pour le `special_traits_md` d'un lanceur qui le cite.

### 3.4 Tables de consultation non aléatoires (ligne 9) — trou mineur, deux sorties

(a) si la table n'est consultée qu'à froid → `corps_md` d'un node suffit,
hors-extension (D-141) ; (b) si le moteur doit y piocher mécaniquement
(prix en jeu, DC paramétrés) → assouplir `RollTable` avec un mode sans dé
(clé de consultation au lieu de plage) plutôt qu'une primitive neuve.
Recommandation : (a) par défaut, (b) seulement sur cas réel rencontré en
conversion — pas d'acte méta préventif.

## 4. Verdict d'ensemble

| compte | valeur |
|---|---|
| lignes d'inventaire | **28** |
| couvertes (COUVERT + COMPOSITION) | **18** (16 + 2) |
| trous | **5 lignes → 4 propositions** (§3.1 couvre les lignes 11-12 ; §3.2, §3.3 ; §3.4 mineur) |
| hors-Partition justifiées D-141 | **5** (lignes 13, 21, 22, 25, 26) |
| nouvelle primitive nécessaire | **0** — toutes les propositions sont des extensions de primitives existantes |

La question d'origine (« faut-il une 7e primitive Ressource ? ») est doublement
close : la Ressource existe déjà (D-216 §2, `schemas.py:438`), et l'audit ne
révèle aucun matériel typique qui exigerait une primitive de plus — les trous
restants sont des VALEURS de types ou des CHAMPS à étendre, pas des formes
nouvelles. La conversion DKS peut reprendre dès l'arbitrage des extensions
§3.1 (bloquante pour les handouts/illustrations si le module en porte) ; §3.2
et §3.3 se traitent au premier module qui en a besoin ; §3.4 sur cas réel.
