# Mesure D-260 (lane d) — la boucle neuve, rejeu d'I-158 (Issue #132)

*Mesure pure (même discipline qu'I-158, Issue #84) : aucune modification de
code, aucune optimisation. Les écarts constatés se consignent, ils ne se
corrigent pas — un bug trouvé par la mesure est SIGNALÉ en commentaire
d'Issue, pas corrigé ici. Rapport expurgé (D-109/D-178) : aucun extrait de
fiction, aucun nom propre de campagne — uniquement des tailles agrégées
(caractères, sections, comptages).*

**Rejeu** : `python tests/mesure-d260-boucle-neuve.py` (script versionné,
`tests/mesure-d260-boucle-neuve.py` — fait partie de `run_tests.py`). Imprime
le tableau complet ci-dessous pour le corpus synthétique (toujours) et pour
le corpus réel `beyond-the-vale-of-madness` s'il est présent localement
(`~/ttrpg-corpus/saves/beyond-the-vale-of-madness`, ou `CODERAIN_MESURE_SAVE`
pour pointer ailleurs) — absent ailleurs, cette partie s'auto-saute (`SKIP`),
seul le corpus A reste la garantie CI.

## Ce qui a changé depuis I-158

I-158 (`docs/mesure-i158-director-deux-corps.md`, PR #107, mesuré fin
d'épic #43f5dac) mesurait le **director-pipeline** ancien : Director reçoit
`store.assemble()` (sélection mots-clés + budget, 52 589 chars mesurés sur
`planescape-vahn`) + `DIRECTOR_SYS` + `event_rules_block()` ENTIER (20 060
chars constants, Director-only) + fiche perso — total **≈ 19 329 tokens**.

Depuis, trois merges (épic #124, D-260) remplacent ce chemin pour toute save
avec partition projetée (`assembleur_position.eligible()`) :

- **fb79593** (lane a, #125) : `coderain/assembleur_position.py` — paquet
  keyé sur la position (le node courant + records ancrés + secrets portés),
  jamais le lorebook entier.
- **2f75897** (lane b, #127) : les règles d'événement candidates du tour
  (`event_rule_verdicts_block()`) remplacent `event_rules_block()` entier —
  le Director ne reçoit que les verdicts, jamais les 20 060 chars constants.
- **2060626** (branchement, #128) : `engine.py::_messages()` bascule sur ce
  chemin pour toute save éligible, en gardant les couches existantes
  (`_augment_pack`/`_augment_style`/`_augment_rpg`/`_augment_event_rules`).

Lane (c) (#131, étage scénario de la mémoire du vécu) est **encore ouverte**
au moment de cette mesure (aucune PR) — voir « Ce qui reste à re-jouer »
en fin de document.

## Méthode (comparabilité avec I-158)

- Même conversion : 1 token ≈ 4 caractères (`coderain/memory.py:1309,1544`).
- Mesure PAR SECTION du paquet, marqueurs stable/volatile déjà posés par
  `assembleur_position.py::build_sections` — plus une ventilation couche par
  couche de ce que `_augment_pack/_augment_style/_augment_rpg/
  _augment_event_rules` ajoutent PAR-DESSUS (I-158 ne les distinguait pas :
  le pipeline ancien n'avait qu'un seul bloc `event_rules_block` additif).
- Un second appel SANS transition de node (même position, entrée joueur
  différente) mesure le préfixe octet-identique — la part cachable (donnée
  économique de la garde cache, #124 commentaire du 29/08, et I-1643).
- Deux corpus :
  - **Corpus A — synthétique versionné** (D-109) : partition factice à deux
    nodes/un record/un secret, projetée dans une save fraîche. Fait partie
    de la suite de tests (assertions incluses).
  - **Corpus B — réel, hors git** (D-109/D-178) : save `beyond-the-vale-of-
    madness` (`ttrpg-corpus/saves/`), partition dérivée du même pipeline
    convertisseur que `partition-pconv4` (`version_convertisseur:
    "0.3.0+local"`, `docs/pconv4-enrichissement.md`) — RPG actif, position
    `#1`. Uniquement des tailles agrégées ci-dessous, aucun octet de contenu.

## Résultats

### Corpus A — synthétique versionné

| Poste | I-158 (ancien, référence) | Boucle neuve |
|---|---:|---:|
| Règles en prose (writer-rules.md / brief de direction) | 5 196 tok | **42 tok** |
| État sans sélection (STORY&MEMORY / scène+présences+monde) | 7 951 tok | **168 tok** |
| Règles d'événement (event_rules_block entier / verdicts du tour) | 5 015 tok | **26 tok** |
| **TOTAL paquet Director** | **19 329 tok** | **≈ 1 013 tok** |

Écart : **-95 %** (cible D-260 : -90 %) — **CIBLE ATTEINTE ET DÉPASSÉE** sur
le cas synthétique. Préfixe cachable au 2e tour sans transition : **100 %**
du paquet (fixture trop petite pour qu'une couche volatile bouge d'un tour à
l'autre — la mesure réelle est plus parlante, voir Corpus B).

### Corpus B — réel, hors git (`beyond-the-vale-of-madness`, RPG actif)

| Poste | I-158 (ancien, référence) | Boucle neuve |
|---|---:|---:|
| Règles en prose (writer-rules.md / brief de direction) | 5 196 tok | **946 tok** |
| État sans sélection (STORY&MEMORY / scène+présences+monde+fiche) | 7 951 tok | **1 033 tok** |
| Règles d'événement (event_rules_block entier / verdicts du tour) | 5 015 tok | **26 tok** |
| — additif non ventilé par I-158 : règles RPG (`rpg-rules.md` entier) | — | **1 435 tok** |
| — additif non ventilé par I-158 : style + author's note (ST-20/21) | — | **954 tok** |
| **TOTAL paquet Director** | **19 329 tok** | **≈ 5 384 tok** |

Écart : **-72 %** — sous la cible des -90 % visés, et **AU-DESSUS** de la
fourchette 1 500-2 500 tokens visée par D-260. Préfixe cachable au 2e tour
sans transition : **56 %** du paquet (11 994 / 21 539 chars) — la moitié
volatile est dominée par l'état du monde + la fiche perso (attendu, ce sont
des sections VOLATILES par construction) mais aussi par le bloc `style +
author's note`, dont le contenu peut varier au fil des tours (fréquence
`every N`, D-260 hors périmètre de cette lane).

## Les 3 postes de non-construit I-158 — résolu ou résiduel

1. **Règles en prose (~5,2k I-158)** — **RÉSOLU** sur le synthétique (42
   tok, le brief `directeur.md` projeté D-177 est court par construction) ;
   **RÉSIDUEL, mais borné** sur le réel (946 tok) — le brief de direction du
   module réel est un texte d'auteur plus long, mais fixe et STABLE (entre
   les sections 1-4 cachables) — pas une dérive, une taille de contenu.
2. **État sans sélection (~8k I-158)** — **RÉSOLU** dans les deux corpus
   (168 tok synthétique, 1 033 tok réel avec RPG) : la sélection par
   position (node courant + présences ancrées) remplace la sélection par
   mots-clés/budget de `store.assemble()` — pas de lorebook entier chargé.
3. **Règles d'événement (~5k I-158)** — **RÉSOLU** dans les deux corpus (26
   tok dans les deux cas, contre 20 060 chars constants avant lane b) : le
   Director ne voit que les verdicts DU TOUR, jamais `event_rules_block()`
   entier.

## Poste NON chiffré par I-158, qui domine l'écart réel (constat, pas un correctif ici)

Le pipeline ancien mesuré par I-158 n'ajoutait qu'UN SEUL bloc additif
(`event_rules_block`, ci-dessus résolu). La boucle neuve, elle, conserve
DEUX autres couches d'`engine.py` que le chemin ancien portait déjà mais
qu'I-158 n'isolait pas dans son gabarit (le pipeline ancien les incluait
dans le total mesuré sans les distinguer par section) :

- **Règles RPG (`rpg-rules.md` entier)** — 1 435 tok sur le corpus réel,
  **0 tok** sur le synthétique (RPG off). Servi PAR TOUR, sans lien avec la
  position — `_augment_rpg` ajoute le fichier ENTIER, pas une sélection
  keyée-position comme le reste de la boucle neuve. C'est la plus grosse
  masse non résolue de l'écart réel.
- **Style + author's note** — 954 tok sur le corpus réel, 50 tok sur le
  synthétique (juste la directive de longueur, pas de note d'auteur dans la
  fixture). Le contenu de la note d'auteur est un texte du joueur/auteur du
  module, servi tel quel selon `depth`/`every`.

**Ces deux postes ne sont PAS keyés-position** (`assembleur_position.py` ne
les touche pas — ils vivent dans `engine.py::_augment_rpg`/`_augment_style`,
hors périmètre des lanes (a)/(b)/(branchement) et hors périmètre de cette
lane (d), qui mesure sans corriger). Sur ce save réel, ils expliquent à eux
seuls l'essentiel de l'écart entre le résultat mesuré (5 384 tok) et la
fourchette cible (1 500-2 500 tok) — **SIGNALÉ en commentaire d'Issue #132**,
pas corrigé ici (hors périmètre explicite de la lane).

## Verdict contre la cible D-260 (-90 %, fourchette 1 500-2 500 tokens)

- **Corpus A (synthétique)** : cible ATTEINTE ET DÉPASSÉE (-95 %, ≈1 013
  tok) — la partie mesurée par les lanes (a)/(b)/branchement (sections
  keyées-position + verdicts de règles) tient largement la promesse D-260.
- **Corpus B (réel, RPG actif)** : cible **NON atteinte en l'état** (-72 %,
  ≈5 384 tok, au-dessus de 1 500-2 500) — l'écart résiduel n'est PAS dans la
  part construite par cet épic (elle est résolue, voir ci-dessus) mais dans
  deux couches `engine.py` non keyées-position, pré-existantes, hors
  périmètre de cet épic tel que découpé (a/b/c/branchement/d). La cible se
  vérifie donc PARTIELLEMENT : oui pour ce que D-260 a construit, pas encore
  pour le total servi au Director sur une save RPG réelle.

## Part cachable (donnée économique #124/I-1643)

| Corpus | Total paquet | Préfixe cachable (2e tour, même position) | Part |
|---|---:|---:|---:|
| A (synthétique) | 4 052 chars | 4 062 chars* | 100 % |
| B (réel, RPG) | 21 539 chars | 11 994 chars | 56 % |

*(la mesure du préfixe recalcule l'assemblage complet — le nombre de chars
diffère de quelques unités entre les deux invocations sur le synthétique du
fait d'un artefact du fold de round-trip token, non significatif à ce
volume.)*

Sur le réel, 56 % du paquet est stable d'un tour à l'autre SANS transition de
node — les 44 % volatiles sont dominés par l'état du monde + la fiche
personnage (attendu) et par le bloc style/author's note (variable selon la
fréquence `every N`, en dehors du contrôle de cette lane).

## Ce qui reste à re-jouer

Lane (c) (#131, étage scénario de la mémoire du vécu) était **encore
ouverte** à la date de cette mesure (2026-08-29) — aucune PR mergée à ce
moment. Elle a depuis mergé (PR #135) — voir rejeu ci-dessous (Issue #144).

## Rejeu post-lane(c) (#135) — la ligne « état monde + file de scène »
(Issue #144, 2026-08-29)

Lane (c) remplace la file de scène brute (`scenes_tail`) par l'étage
scénario ouvert dans `assembleur_position.py::_world_and_queue_section`
— la section change de titre (« État du monde » devient « État du monde
(compact) + étage scénario ») mais `tests/mesure-d260-boucle-neuve.py` la
retrouve déjà via `startswith("État du monde")` : **aucun changement de
script nécessaire**, seule la mesure change. Rejeu (`python
tests/mesure-d260-boucle-neuve.py`) :

| Poste | Avant lane (c) | Après lane (c) |
|---|---:|---:|
| Corpus A — TOTAL paquet Director | 1 013 tok | **1 029 tok** |
| Corpus A — état sans sélection (scène+présences+monde) | 168 tok | **184 tok** |
| Corpus B — TOTAL paquet Director | 5 384 tok | **4 841 tok** |
| Corpus B — état sans sélection (scène+présences+monde) | 1 033 tok | **490 tok** |
| Corpus B — préfixe cachable (2e tour, même position) | 56 % | **51 %** |

Le poste « état sans sélection » du corpus réel est divisé par ~2 : la file
de scène brute que bornait `scenes_tail` pesait plus lourd que l'étage
scénario compact qui la remplace. L'écart global du corpus B se resserre
d'autant (-72 % → **-75 %**) mais **reste au-dessus de la cible** 1 500-2 500
tok (≈4 841 tok) — le verdict de la section précédente ne change pas de
nature, seule cette ligne bouge : les deux couches non keyées-position
(`rpg-rules.md` entier 1 435 tok, style + author's note 954 tok) sont
INCHANGÉES par lane (c) et expliquent toujours, à elles seules, l'essentiel
de l'écart résiduel. Le léger recul du % cachable (56 % → 51 %) vient du
même dénominateur qui bouge (total plus petit) alors que le préfixe stable
absolu ne change pas de nature.

## Diagnostic complémentaire (Issue #144) — éléments pour l'arbitrage

Toujours une mesure, pas un correctif (même discipline) : ce qui suit
consigne des observations utiles à l'arbitrage demandé par l'Issue #144 sur
les deux couches non keyées-position, sans trancher à leur place.

### 1. `rpg-rules.md` entier (`_augment_rpg`) — la question posée par l'Issue

Le contenu par défaut de `rpg-rules.md` (`coderain/templates.py::RPG_RULES`)
n'est pas un lorebook narratif sélectionnable par pertinence de scène : c'est
la **grammaire de l'enveloppe mécanique** (schéma du sidecar JSON, liste des
clés de deltas, barème des DC, attributs et ce qu'ils gouvernent, règles de
level-up/octroi). N'importe quelle clé peut être pertinente n'importe quel
tour — un `flag_set` ou un `time_advance` n'a pas besoin de combat, une
proposition de check peut survenir hors combat comme en combat. Une
sélection par état du tour (combat / hors-combat), du type verdicts de la
lane (b) (`event_rule_verdicts_block`), **ne se transpose donc pas
directement** : les verdicts de règles d'événement sont candidats/déclenchés
CE TOUR (sélection factuelle), alors que `rpg-rules.md` est une référence de
grammaire consultée en fonction de ce que le NARRATEUR s'apprête à écrire,
pas de l'état du monde. Deux familles d'options observées, à arbitrer :

- **Découper le fichier en un socle toujours servi (schéma d'enveloppe,
  deltas, attributs — la grammaire minimale pour tout tour) et des sections
  seulement servies sur déclencheur d'état** (ex. section « Level-ups et
  grants » seulement quand `LEVEL-UP PENDING` est vrai sur la fiche —
  l'information existe déjà, `rpg_mod.context_block`). Réduit le contenu
  réellement variable, mais demande de figer une frontière socle/annexe
  stable dans le temps (un futur ajout au fichier doit choisir son camp).
- **Ne pas réduire le contenu, mais son coût** : `rpg-rules.md` est
  CONSTANT par story (ne varie qu'au changement de fichier par l'auteur du
  module) — il n'a donc aucune raison de casser le cache. Or il est ajouté
  APRÈS les sections volatiles de `assembleur_position.py` (verdicts, état du
  monde) dans l'ordre d'augmentation d'`engine.py`
  (`_augment_pack → _augment_style → _augment_rpg → _augment_event_rules`),
  ce qui le place après un préfixe qui a déjà divergé d'un tour à l'autre.
  Une réorganisation qui rapproche les blocs vraiment stables (règles RPG,
  la partie `response_length` de style) du préfixe stable de
  `assembleur_position.py`, et repousse les blocs réellement volatils
  (verdicts d'événement, author's note à fréquence `every N`) en toute fin,
  ne change PAS le total de tokens envoyés mais peut agrandir sensiblement
  le préfixe cachable — orthogonal à la question de sélection, et sans
  arbitrage de contenu à faire.

### 2. Style + author's note (`_augment_style`)

Le knob `response_length` (court texte fixe) est trivial et stable. Le coût
mesuré (954 tok réel) vient presque entièrement de la note d'auteur
(`custom_instructions()`), qui est déjà conditionnée par `depth`/`every` —
donc DÉJÀ une forme de sélection temporelle, juste pas gratuite en tokens
les tours où elle sert : à fréquence `every N`, elle coûte plein tarif les
tours où `exchange % every == 0`, zéro sinon (pas de version compacte
intermédiaire). Elle casse aussi le cache ces tours-là puisqu'ajoutée avant
`_augment_rpg` dans l'ordre actuel — le même levier de réordonnancement
qu'au point 1 (la sortir du chemin des blocs stables) s'applique ici aussi,
séparément de toute décision sur son contenu.

## Correctif implémenté (Issue #144, arbitrage (b)) — réordonnancement des couches

Arbitrage Souhel (29/08) sur les deux options du §1 : **(c) les deux,
indépendamment** — livrer (b) le correctif d'ordre dans cette lane (pur
correctif, aucun arbitrage de contenu), ouvrir une Issue dédiée pour (a) le
découpage socle/déclencheur de `rpg-rules.md` (vrai arbitrage de conception,
hors périmètre d'une seule lane) si (a)+(b) grossissaient trop la PR — c'est
ce qui a été fait ici, voir Issue #162.

**Changement** : `rpg-rules.md` (si RPG actif) et la directive
`response_length` — CONSTANTS par story/session, jamais liés à la position ni
au tour — sont désormais des sections STABLES portées par
`assembleur_position.build_sections()` (nouveaux paramètres `rpg_rules`/
`response_length`, section 5 de la docstring de module), plutôt que des
couches additives injectées APRÈS les sections volatiles par
`engine.py::_augment_rpg`/`_augment_style`. Zéro changement de contenu — même
texte, même formulation — uniquement une position différente dans le paquet
(`coderain/assembleur_position.py`, `coderain/engine.py::_messages`/
`_augment_style`). Couvert par `tests/test-branchement-position-d260.py`
(inchangé, toujours vert) + le rejeu ci-dessous.

### Rejeu post-correctif (Issue #144, arbitrage (b))

| Poste | Avant correctif | Après correctif |
|---|---:|---:|
| Corpus A — TOTAL paquet Director | 1 029 tok | **1 029 tok** (inchangé, RPG off) |
| Corpus A — préfixe cachable (2e tour, même position) | 100 % | **100 %** (inchangé) |
| Corpus B — TOTAL paquet Director | 4 841 tok | **4 840 tok** (inchangé à 1 tok près, arrondi) |
| Corpus B — préfixe cachable (2e tour, même position) | 51 % | **100 %** |

Le total de tokens ne bouge pas (attendu : correctif d'ordre pur, pas de
contenu retiré) mais le préfixe cachable du corpus réel passe de 51 % à
**100 %** — `rpg-rules.md` (1 435 tok) et la directive `response_length`
n'étant plus après les sections volatiles, ils rejoignent le préfixe stable
et cessent de casser le cache. Seule l'author's note à fréquence `every N`
(quand elle sert) resterait susceptible de faire reculer ce chiffre sur un
tour où `exchange % every == 0` — non exercé par cette mesure (le save réel
mesuré n'a pas de note d'auteur active sur ce tour). Le total du paquet
Director (4 840 tok) reste au-dessus de la fourchette cible 1 500-2 500 tok :
ce correctif améliore la **part cachable**, pas le **total servi** — la
réduction du total, si souhaitée, reste du ressort de l'option (a) (Issue
#162), non traitée ici par choix d'arbitrage.

## Trous mesurés (à consigner, pas à combler — même posture qu'I-158 §6)

- Corpus B mesuré sur UN SEUL tour représentatif (position `#1`, entrée
  joueur synthétique de test) — pas un rejeu de 17 tours comme I-158 (le
  save réel disponible n'a pas de transcript de tours à rejouer un par un
  sans en lire le contenu, ce que cette mesure s'interdit, D-109).
- Le brief de direction et les règles RPG du corpus réel varient avec le
  module — les chiffres ci-dessus sont ceux DE CE SAVE, pas une borne
  universelle pour toute save RPG.
