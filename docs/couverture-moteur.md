# Couverture du moteur de règles — mesure (D-275 §6, Issue #235)

*Lane de MESURE PURE : aucun changement de comportement, aucun fichier
touché hors ce document. Objectif : donner au valideur (#105) une carte
fiable de ce que `dnd5e-engine` (le pont `coderain/rules_engine/`) résout
réellement aujourd'hui, croisée avec ce que le module sacrificiel DKS
(D-139, `death-knights-squire`) sollicite comme règles — pour que le
converter (D-275 §6-7) sache d'avance où sont les trous, au lieu de les
découvrir en partie.*

Sources inspectées : `coderain/rules_engine/engine_bridge.py`,
`coderain/rules_engine/monster_bridge.py`, `coderain/rules_engine/__init__.py`,
`mcp_server.py` (outils `roll_check`, `roll_damage`, `death_save`,
`resolve_check`, `start_combat`, `submit_intent`, `monster_turn`,
`end_combat`), le paquet installé `dnd5e-engine==0.3.0` (`specs.py`,
`check.py`, `death_saves.py`, `outcome.py`, `spatial.py`, `dispatch.py`,
`events.py`) et `dnd5e_srd_data` (schéma `monster`/`common`) ; côté DKS,
`docs/ingestion-dks-analyse.md`, `docs/pconv0-socle-formes.md`,
`docs/pconv1-3-pval-ecarts.md`, `docs/pconv4-enrichissement.md`,
`tests/test-dks-regime-trans-modules.py` et `coderain/converter/aval.py`
(détection de jets `CHECK_RE`/`REVERSE_CHECK_RE`).

**Précision sur l'accès au matériau réel** : le module DKS lui-même
(texte, statblocks, cartes) ne vit jamais dans ce dépôt (`D-109` — voir
`CLAUDE.md`) ; il vit dans le dépôt privé `ttrpg-corpus`
(`coderain/config.py::corpus_dir()`). Sur ce poste, ce dépôt privé est
cloné en local (`corpus_dir()` résout vers un chemin existant) — mais rien
n'en a été lu ici au-delà de ce que les rapports-formes déjà versionnés
sous `docs/` publient (comptages, ids machine, verdicts). Le tableau 2
ci-dessous est donc construit à 100 % sur du matériau **déjà public dans
ce dépôt** (rapports P-conv-0 à P-conv-4, `ingestion-dks-analyse.md`,
la fixture synthétique `tests/fixtures/module-fixture-gamebook-s2.txt`),
jamais sur une relecture directe de la partition privée — cohérent avec la
discipline D-109 déjà appliquée par ces mêmes rapports.

---

## 1. Table de couverture moteur (`dnd5e-engine`)

| catégorie de règle | ce qui est résolu par le moteur | référence | limite connue |
|---|---|---|---|
| Jet de compétence | `CheckSpec(kind="skill")` → `skill_check` (proficience, expertise ×2, avantage/désavantage, effets actifs pliés) | `dnd5e_engine/check.py::resolve_check` ; MCP `resolve_check` | aucune — chemin complet |
| Jet de caractéristique | `CheckSpec(kind="ability")` → `ability_check` | idem | aucune |
| Jet de sauvegarde | `CheckSpec(kind="saving_throw")` → `saving_throw`, bucket d'effets par ability (`save.<ability>.bonus`) | idem | aucune |
| Sauvegarde contre la mort | `roll_death_save` : d20 sans modificateur, 10+ succès, nat-20 relève à 1 PV, nat-1 = 2 échecs, 3 succès = stable, 3 échecs = mort | `dnd5e_engine/death_saves.py::roll_death_save` ; orchestrateur (tour du PJ à 0 PV) | **deux systèmes coexistent** : l'outil MCP `death_save` (I-213) passe par `coderain.modules.rpg`, PAS par `dnd5e-engine` — la mécanique dnd5e-engine n'est exercée qu'à l'intérieur d'un combat ouvert par `start_combat` |
| Combat — intents | `PlayerIntent` : `attack`, `move`, `pass`, et d'autres non énumérés par le pont hôte (`dispatch.py` mentionne aussi `CAST_SPELL`, `SKILL_CHECK`, `EQUIP_ITEM` côté taxonomie moteur) | `engine_bridge.py::submit_intent` ; MCP `submit_intent` ; `dnd5e_engine/dispatch.py` | le pont hôte documente seulement `attack`/`move`/`pass` dans sa docstring ; les intents plus riches (sorts, équipement) existent moteur-côté mais ne sont pas mentionnés au niveau du pont coderain |
| Tour de monstre (IA) | `advance_monster_turn` — résolution du tour via le répertoire d'actions typé du `Monster` SRD | `engine_bridge.py::monster_turn` ; MCP `monster_turn` | **si `monster_template_slug` ne résout à rien** (absent ou hors `dnd5e-srd-data`), le tour se réduit à un `pass` — signalé explicitement par `warnings`, jamais silencieux (I-205) |
| Dégâts (formule) | `roll_damage` — dés + modificateur, mêmes graines ⇒ mêmes résultats | MCP `roll_damage` | **hors `dnd5e-engine`** : passe par `coderain.modules.rpg.roll_damage`, pas par le moteur de combat — le moteur calcule ses propres dégâts en interne pendant `submit_intent`/`monster_turn`, jamais ré-exposé nu par le pont |
| Types de dégâts | résistances/immunités/vulnérabilités par type (`damage_resistances`, `damage_immunities`, `damage_vulnerabilities` sur `PartyMemberSpec`/`EncounterMemberSpec`) | `dnd5e_engine/specs.py` | le pont "brute" (I-205) n'installe **aucune** résistance/immunité/vulnérabilité — une seule attaque générique, chiffres bruts injectés |
| Conditions/états | `blinded`, `deafened`, `exhaustion`, `frightened`, `grappled`, `incapacitated`, `paralyzed`, `petrified`, `poisoned`, `prone`, `restrained`, `unconscious`, + `stabilized`/`death` comme événements dédiés | `dnd5e_engine/events.py` (`ConditionApplied`/`ConditionRemoved`, liste des slugs), `Stabilized`, `Death` | l'immunité de condition (`condition_immunities`) existe côté spec mais n'est peuplée que par le layer hôte amont — le pont "brute" DKS ne la peuple jamais |
| État "downed" | PJ à 0 PV → `unconscious` (condition) ; pas d'événement `CharacterUnconscious` dédié, la transition se lit sur `CharacterHpChanged(new_hp=0)` puis la boucle death-save | `dnd5e_engine/outcome.py` (docstring en tête) | terminologie "downed" n'est pas un slug moteur — c'est une lecture hôte de `unconscious` + `hp_current==0` |
| Initiative | `initiative_order` mirroré en lecture depuis `get_live` | `engine_bridge.py::live` | aucune — chaque `PartyMemberSpec`/`EncounterMemberSpec` porte son `initiative` déjà résolu en amont (pas de jet d'initiative dans le pont) |
| Zones/topologie de scène | `SceneTopology` (graphe de zones, `zones`/`edges`) — backend zone OU `GridScene`/`GridTopology` (grille Chebyshev, murs, cases de couverture, terrain difficile) | `dnd5e_engine/specs.py::SceneTopology/GridScene` ; `dnd5e_engine/spatial.py::GridTopology` | le pont `engine_bridge.start_combat` n'utilise QUE le backend zone (`SceneTopology(zones=...)`) — la grille (`GridScene`/`GridTopology`, couverture, ligne de vue, terrain difficile) existe côté moteur mais n'est jamais câblée par `CombatBridge` |
| Monstres — résolution SRD | `monster_template_slug` résolu contre `dnd5e_srd_data` (ex. `goblin-warrior`) → répertoire d'actions typé complet (attaques multiples, résistances, traits) | `engine_bridge.py::_unresolved_template_warnings` ; `lib_loader.get_monster` | seuls les monstres présents dans le corpus SRD embarqué (341 monstres, `dnd5e-srd-data==0.3.0`) résolvent ainsi |
| Monstres — template "brute" | Créature de module (champs FR `ca`/`pv`/`attaque_bonus`/`degats`) → `Monster` générique une-seule-attaque, injecté dans un loader composite | `coderain/rules_engine/monster_bridge.py::install_brute_template`/`encounter_member_from_record` | **portée volontairement minimale (I-205)** : une attaque, pas de multiattaque, pas de résistances/immunités/traits spéciaux, stats non recalculées depuis les caractéristiques (bonus "flat") — comble le trou pour la fumée, pas pour un monstre custom fidèle |
| Issue de combat | `end_combat` → `CombatOutcome` (`ended_reason`: victory/defeat_tpk/flee/forced, `deaths`, `residual_hp`, `xp_awarded`, `loot_drops`, `expended_resources`) | `dnd5e_engine/outcome.py` ; `engine_bridge.py::end_combat` ; MCP `end_combat` | XP répartie également entre survivants (sémantique héritée solo, correcte multi-PJ) ; le loot/HP résiduel monstre/PNJ n'est pas persisté par ce seam (éphémère, propriété du Redis de combat hôte) |

**Nuance transverse** (à ne pas perdre côté valideur) : ce dépôt fait
coexister **deux systèmes de jets distincts** — l'ancien `coderain.modules.rpg`
(outils MCP `roll_check`/`roll_damage`/`death_save`, jets hors combat "legacy",
I-213 ; désormais aussi `attack` — I-463, D-274 §1-2, mergé sur `main`
pendant cette lane — qui résout toucher + dégâts + application de bout en
bout à partir de la fiche dérivée `derived_combat`, CA/bonus d'attaque/dés
calculés à la volée, jamais stockés) et `dnd5e-engine` (outils MCP
`resolve_check`/`start_combat`/`submit_intent`/`monster_turn`/`end_combat`).
`coderain/rules_engine/__init__.py` documente explicitement cette
coexistence : "les jets simples hors combat restent dans
`coderain.modules.rpg`, NON touché". Un vocabulaire de règles sollicitées
doit donc savoir de quel système une scène a besoin — pas seulement quelle
catégorie 5e.

---

## 2. Table de sollicitation DKS (scène / catégorie → règle)

*Le module DKS n'a pas de partitions/fixtures narratives dans CE dépôt
(D-109) — seuls des rapports-formes agrégés existent sous `docs/`. Le
découpage n'est donc pas récupérable scène par scène depuis ce dépôt ;
la table ci-dessous agrège par **catégorie de règle mesurée** sur
l'ensemble des 361 nodes de la partition, avec la source du chiffre.*

| catégorie | règle sollicitée | mesure | source |
|---|---|---|---|
| Combat | rencontres avec statblocks (SRD direct, variante SRD, custom) | **9 combats** (unité de charge estimée v0) ; 10 créatures/PNJ distincts résolus en records (6 ancre SRD directe, 1 variante SRD, 3 custom complets) | `docs/ingestion-dks-analyse.md` §5 ; `docs/pconv1-3-pval-ecarts.md` §2 |
| Combat — état persistant inter-combats | un antagoniste récurrent (death-knight) conserve ses PV entre 3 rencontres (p30/42/72/80), hors frontière moteur D-200 au moment de l'analyse | absorbé comme fonctionnalité moteur générale `etat-persistant-inter-combats` (hors `dnd5e-engine`, côté coderain) | `docs/pconv1-3-pval-ecarts.md` §2 ; `docs/ingestion-dks-analyse.md` §2 |
| Combat — encounters multi-tokens | rencontres avec plusieurs jetons + PNJ allié (Darek Brewmont) | **11 poses `tokens_initial`** | `docs/pconv1-3-pval-ecarts.md` §2 |
| Jet de compétence / caractéristique | phrasé `"<verbe> <compétence>, DC N"` détecté par `REVERSE_CHECK_RE` | **42 `check`** (sur 51 jets détectés au total) | `docs/pconv1-3-pval-ecarts.md` §6 ; `docs/pconv4-enrichissement.md` §6 ; `coderain/converter/aval.py` |
| Jet de sauvegarde | phrasé `"<ability> save, DC N"` détecté par `REVERSE_CHECK_RE` | **9 `saving_throw`** (sur 51) | idem |
| DC divers (avant extension de la détection) | mentions de `DC N` toutes formes confondues, mesure amont à la détection typée | **62 jets DC** (mesure v0 large) / **32 skill checks** (sous-ensemble) | `docs/ingestion-dks-analyse.md` §5 |
| Hasard / table de décision | tables d100 (chance rolls, exploration, mauvais tour, PNJ riverains, rebondissement) — branchement narratif pur, jamais un tirage consultable | **5 `RollTable`**, toutes en mode `aleatoire` | `docs/pconv0-socle-formes.md` §4 ; `docs/pconv4-enrichissement.md` §3 |
| Pièges | checks liés à des pièges (détection/désamorçage) | **13 checks pièges** (mesure v0) | `docs/ingestion-dks-analyse.md` §5 |
| Objets / butin | gains d'objets, montants d'or, objets magiques requalifiés (arme/anneau/potion/parchemin/merveille) | **11 gains d'objets**, **9 montants gp** (v0) → **25 objets** (17 gains + 8 gp) en P-conv-1, dont **8 requalifiés magiques** en P-conv-4 | `docs/ingestion-dks-analyse.md` §5 ; `docs/pconv1-3-pval-ecarts.md` §2 ; `docs/pconv4-enrichissement.md` §2 |
| Sorts | sorts cités dans la source (Jump, Thunderwave, Sacred Flame, Cure Wounds, Charm Person, etc.) | **0 sort hors SRD** — tous déjà couverts par le SRD 5e, aucun record `sort` émis | `docs/pconv4-enrichissement.md` §5 |
| Trajectoire / échéancier | déclencheurs narratifs de l'antagoniste + condition monde | **4 déclencheurs, tous de type `etat`** (aucun `date`/`delai`) | `docs/pconv1-3-pval-ecarts.md` §5 ; `tests/test-dks-regime-trans-modules.py` §4 |
| Secrets / tensions | révélations tardives, tensions traversantes (menace/horloge/échéance/coût/choix/révélation) | **4 secrets, 9 tensions** | `docs/pconv1-3-pval-ecarts.md` §4 |
| Cartes / matériel montrable | plans de site (tilepages/sub-maps), documents/illustrations montrables au joueur | **19 cartes** + **3 documents/illustrations** = 22 ressources | `docs/pconv1-3-pval-ecarts.md` §3 ; `docs/pconv4-enrichissement.md` §4 |
| Navigation / choix conditionnels | débouchés typés à partir des options ♦ verbatim | **485 liens typés conditionnels** (`condition_textuelle` = clause source) | `docs/pconv0-socle-formes.md` §5 |
| Instructions procédurales spatiales | placement/direction de lecture (hors géométrie jouable) | acceptées en `corps_md` v0, aucune primitive dédiée demandée | `docs/pconv1-3-pval-ecarts.md` §6 (écart E4) |

*Catégories nommées dans le mandat mais non mesurées comme telles dans les
rapports DKS disponibles (chute, poison, poursuite, négociation, lumière,
épuisement) : elles ne ressortent pas des comptages publiés — le
gamebook DKS encode probablement une partie de ces effets via des checks
génériques (skill/ability/save) ou via `corps_md` narratif plutôt que
comme catégories mécaniques distinctes. Aucune mesure fiable n'a pu être
établie pour elles depuis ce dépôt seul ; les marquer "non mesuré",
pas "absent".*

---

## 3. Écarts — trous prévisibles à combler au converter (D-275 §6-7)

Les points suivants sont des **trous prévisibles**, à traiter en amont au
converter/à la partition (déclaration explicite des règles sollicitées),
**jamais en partie** (jamais découverts en tour de jeu réel) :

- **Death save à deux systèmes** : le vocabulaire de partition doit
  distinguer une sauvegarde contre la mort résolue par `coderain.modules.rpg`
  (`death_save` MCP, hors combat moteur) de celle résolue par
  `dnd5e-engine` à l'intérieur d'un combat ouvert (`start_combat`) — les deux
  ne partagent ni le même code ni le même état.
- **Dégâts hors combat** (`roll_damage` MCP) contournent totalement
  `dnd5e-engine` — une scène qui déclare "combat.damage" doit préciser si
  c'est un jet de dégâts isolé (legacy) ou un dégât résolu à l'intérieur
  d'un `submit_intent`/`monster_turn` (moteur).
- **Monstres custom via le pont "brute" (I-205)** : toute créature DKS
  hors SRD (`death-knight`, `giant-centipede`, PNJ allié `darek-brewmont`)
  perd, au combat, ses résistances/immunités/vulnérabilités, sa
  multiattaque et ses traits spéciaux — le moteur ne joue qu'une attaque
  générique paramétrée. C'est un contournement documenté, pas une
  couverture réelle des règles de ces créatures.
- **État persistant inter-combats** (PV du death-knight entre 3
  rencontres) : absorbé côté coderain (feature générale), **hors
  périmètre `dnd5e-engine`** — le moteur ne connaît qu'un combat à la
  fois, sans mémoire d'un combat à l'autre.
- **Topologie de scène — zone uniquement** : le pont `start_combat` ne
  câble jamais `GridScene`/`GridTopology` (grille, couverture, ligne de
  vue, terrain difficile) — toute scène DKS qui sollicite une géométrie
  fine (pièges positionnels, lignes de vue, couverture) ne peut aujourd'hui
  s'exprimer qu'en zones nommées, sans les règles de couverture/LoS 5e.
- **Pièges (13 checks mesurés)** : aucune catégorie moteur dédiée
  "trap" — un piège se résout comme un `check`/`saving_throw` isolé
  (`resolve_check` ou legacy `roll_check`), jamais comme un objet mécanique
  distinct côté moteur. Le vocabulaire de partition doit le nommer
  explicitement (`condition.trap` / `check.trap-*`) plutôt que de le
  confondre avec un check générique.
- **Catégories non mesurées côté DKS mais nommées au mandat** (chute,
  poison, poursuite, négociation, lumière, épuisement) : `dnd5e-engine`
  couvre nativement `poisoned` et `exhaustion` comme conditions (voir
  table 1), mais aucune mesure DKS ne confirme leur sollicitation réelle
  dans ce module précis — trou de VISIBILITÉ (pas forcément de
  couverture) à vérifier au prochain accès matériau.
- **Tables d100** : toutes en mode `aleatoire` (branchement narratif) —
  le mode `consultation` (D-252.4) existe côté schéma mais n'a aucun cas
  d'usage DKS ; un vocabulaire de règles sollicitées ne doit pas
  présumer qu'une table DKS est "consultable".
- **Objet-clé du module** : particularité narrative unique (moyen de
  vaincre l'antagoniste), volontairement non requalifiée en objet
  magique DMG — aucune règle moteur ne la couvre ; reste `corps_md`
  narratif pur, hors du système de règles sollicitées.

---

## 4. Vocabulaire fermé de règles sollicitées

Slugs kebab-case proposés pour que le valideur (#105) exige qu'une
partition déclare, scène par scène, les règles qu'elle sollicite. Chaque
slug renvoie soit à une entrée couverte de la table 1, soit à un écart de
la section 3 (marqué explicitement `non-couvert`/`partiel`).

| slug | statut | référence |
|---|---|---|
| `check.skill` | couvert | `CheckSpec(kind="skill")` — `dnd5e_engine/check.py` |
| `check.ability` | couvert | `CheckSpec(kind="ability")` — idem |
| `check.saving_throw` | couvert | `CheckSpec(kind="saving_throw")` — idem |
| `check.legacy` | couvert (système parallèle) | `roll_check` MCP → `coderain.modules.rpg`, hors `dnd5e-engine` |
| `check.trap` | non-couvert (pas de catégorie moteur dédiée) | écart §3 — se résout aujourd'hui via `check.skill`/`check.saving_throw` sans marquage "piège" |
| `combat.attack` | couvert | `PlayerIntent.intent_type == "attack"` — `engine_bridge.py::submit_intent` |
| `combat.move` | couvert | `PlayerIntent.intent_type == "move"` — idem |
| `combat.pass` | couvert | `PlayerIntent.intent_type == "pass"` — idem |
| `combat.cast_spell` | partiel (documenté moteur, pas au pont hôte) | `dnd5e_engine/dispatch.py::ActionType.CAST_SPELL` — jamais mentionné par la docstring `submit_intent` du pont coderain |
| `combat.death_save` | couvert (dans un combat moteur ouvert) | `dnd5e_engine/death_saves.py::roll_death_save` |
| `combat.death_save.legacy` | couvert (système parallèle, hors combat) | `death_save` MCP → `coderain.modules.rpg`, hors `dnd5e-engine` |
| `combat.damage` | couvert (interne au moteur, jamais exposé nu) | résolu dans `submit_intent`/`monster_turn`, pas de tool `roll_damage` côté moteur |
| `combat.damage.legacy` | couvert (système parallèle) | `roll_damage` MCP → `coderain.modules.rpg` |
| `combat.attack.legacy` | couvert (système parallèle, hors `dnd5e-engine`) | `attack` MCP (I-463, D-274 §1-2) → `coderain.modules.rpg::derived_combat`/`player_combat` — toucher + dégâts + application en un seul outil, chiffres dérivés de la fiche à la volée, jamais stockés ; refuse plutôt que d'inventer un défaut |
| `combat.monster_turn.srd` | couvert | `monster_template_slug` résolu contre `dnd5e-srd-data` — `engine_bridge.py::_unresolved_template_warnings` |
| `combat.monster_turn.brute` | partiel (contournement I-205) | `coderain/rules_engine/monster_bridge.py` — une attaque, zéro trait spécial |
| `combat.monster_turn.unresolved` | non-couvert (signalé, pas résolu) | `monster_template_slug` absent/non résolu → `pass` + `warnings` explicites |
| `combat.persistent_state` | non-couvert par `dnd5e-engine` (fonctionnalité coderain) | absorbé côté hôte, hors frontière moteur D-200 |
| `combat.outcome` | couvert | `end_combat` → `CombatOutcome` — `dnd5e_engine/outcome.py` |
| `condition.downed` | couvert (lecture composée) | `unconscious` + `hp_current==0` — `dnd5e_engine/outcome.py` (docstring) |
| `condition.stabilized` | couvert | `Stabilized` event — `dnd5e_engine/death_saves.py` |
| `condition.dead` | couvert | `Death` event — idem |
| `condition.poisoned` | couvert | slug de condition — `dnd5e_engine/events.py` |
| `condition.exhaustion` | couvert | idem |
| `condition.frightened` / `blinded` / `deafened` / `grappled` / `incapacitated` / `paralyzed` / `petrified` / `prone` / `restrained` | couvert | idem |
| `initiative.order` | couvert | mirror `initiative_order` — `engine_bridge.py::live` |
| `scene.zone_topology` | couvert | `SceneTopology` — seul backend câblé par `start_combat` |
| `scene.grid_topology` | non-couvert (câblage hôte manquant) | `GridScene`/`GridTopology` existent moteur-côté, jamais utilisés par `CombatBridge` |
| `scene.cover` / `scene.line_of_sight` / `scene.difficult_terrain` | non-couvert (dépend de `scene.grid_topology`) | `dnd5e_engine/spatial.py::GridTopology` |
| `monster.srd_direct` | couvert | ancrage direct `dnd5e-srd-data` |
| `monster.srd_variant` | couvert (delta documenté) | ex. `forest-bat` ≈ `bat`/`giant-bat` — `docs/pconv1-3-pval-ecarts.md` |
| `monster.custom_brute` | partiel | pont "brute" I-205 |
| `loot.item_gain` | non-couvert par `dnd5e-engine` (porté par le converter/schémas coderain) | `docs/pconv1-3-pval-ecarts.md` §2 |
| `loot.magic_item` | non-couvert par `dnd5e-engine` (D-252.2, côté schéma converter) | `docs/pconv4-enrichissement.md` §2 |
| `table.random` | non-couvert par `dnd5e-engine` (mécanique côté converter/hôte) | `RollTable` mode `aleatoire` |
| `table.consultation` | non-couvert par `dnd5e-engine` (existe côté schéma, zéro cas DKS) | D-252.4 |
| `narrative.trajectory` / `narrative.secret` / `narrative.tension` | non-couvert par `dnd5e-engine` (mécanique narrative coderain, pas règles 5e) | `docs/pconv1-3-pval-ecarts.md` §4-5 |

---

## Verdict sur les 4 points du mandat (Issue #235)

1. **Inventaire moteur** : livré en table 1, exhaustif sur les sources
   lues (`engine_bridge.py`, `monster_bridge.py`, `__init__.py`,
   `mcp_server.py`, `dnd5e-engine==0.3.0`).
2. **Inventaire sollicitations DKS** : livré en table 2, **par catégorie
   agrégée** (pas scène par scène — le découpage scène par scène n'est
   pas récupérable depuis ce dépôt, seuls des rapports-formes agrégés
   existent sous `docs/`). Le matériau réel de la partition (accessible
   localement via `corpus_dir()` mais hébergé dans le dépôt privé
   `ttrpg-corpus`) n'a volontairement pas été relu directement — la table
   s'appuie à 100 % sur les comptages déjà publiés dans ce dépôt (D-109).
3. **Croisement/écarts** : livré en section 3.
4. **Vocabulaire fermé** : livré en section 4.

Point 2 est donc **partiellement contraint par l'accès au matériau** :
le découpage scène par scène demandé au mandat n'a pas pu être produit
depuis ce dépôt seul (seules des mesures agrégées existent) — voir le
mot `Refs` (pas `Closes`) choisi pour la PR de cette lane.
