# ANNEXE A — LES CHAMPS `stats_5e` PAR CLASSE DE RECORD

*Annexe A de la SPEC-P4 (`MRPG-D-175` §5). Rédigée par le poste TECHNIQUE le 2026-08-23.*
*`corpus_version: "2014"` — SRD 5.1 (Wizards of the Coast, CC-BY-4.0). Matériau TIERS destiné à
l'ingestion (`É4`). Les ancres citent la hiérarchie de sections du document SRD 5.1 publié
(vérifiées sur un miroir markdown fidèle du PDF officiel, licence incluse).*

---

## 0. CONVENTIONS DE LA TABLE

1. **`nom` n'est jamais un champ `stats_5e`** : il est *first-class* sur `Record` (le valideur
   l'injecte dans le contrôle de complétude, cf. `schemas.py::Record`). Il apparaît donc **hors
   table**, rappelé pour mémoire.
2. **Deux noms par champ** :
   - **champ** = le nom canonique cible (anglais technique, snake_case) — c'est lui qui fait foi ;
   - **clé actuelle** = la clé telle qu'elle existe déjà sur disque (squelette
     `converter/annexe_a.py` DRAFT v0 + records du specimen). Quand elle diffère, l'harmonisation
     est une décision de seconde passe (`schemas.py` hors périmètre de cette annexe) ; « — » =
     champ nouveau, aucune clé existante.
3. **Obligatoire ⊥ optionnel** — critère déclaré : est *obligatoire* le champ que le convertisseur
   doit toujours produire pour que le record soit **exploitable au jeu** (combat, obstacle,
   identification) ; est *optionnel* le champ que la source ne porte pas toujours (ligne de statblock
   conditionnelle ou rubrique narrative). Un obligatoire sans matière source reste **vide +
   exception signalée**, jamais improvisé (`I-111`) — la complétude se juge à l'ingestion, pas à la
   règle.
4. **Champ sans ancre SRD = champ MOTEUR**, signalé comme tel (⛔ jamais d'ancre inventée). Les
   classes `pnj`, `lieu`, `faction` ne correspondent à AUCUNE statistique définie par le corpus 2014 :
   leurs rubriques propres sont des conventions du moteur, et la table le dit explicitement.
5. Chaque table porte sa ligne `corpus_version` : **les deux versions du corpus n'ont pas les mêmes
   statblocks** (SPEC §6) — toute évolution vers une seconde cible se fera en nouvelle table, jamais
   en mutation de celle-ci.

Comptage global : **6 classes · 23 champs obligatoires (+ `nom` first-class par classe) · 27 champs
optionnels**, dont 8 sans ancre SRD signalés (récapitulation et limites de mesure au §8). 6ᵉ classe
`sort` ajoutée par `MRPG-D-252` point 3 (Issue #63, 2026-08-29) : sorts inédits des appendices de
campagne, sans classe de record d'accueil jusqu'ici.

---

## 1. CLASSE `creature`

`corpus_version: "2014"` — ancre racine : **SRD 5.1 › Monsters › Monster Statistics**
(les sous-sections citées ci-dessous en sont les rubriques).

### Obligatoires

| # | champ (canonique) | type | clé actuelle | ancre SRD 2014 |
|---|---|---|---|---|
| c1 | `type` | string composée `"size type, alignment"` | `type` | Monster Statistics › Size · Type · Alignment |
| c2 | `armor_class` | int | `ca` | Monster Statistics › Armor Class |
| c3 | `hit_points` | string `"avg (NdM+k)"` | `pv` | Monster Statistics › Hit Points |
| c4 | `speed` | string `"30 ft."` | `vitesse` | Monster Statistics › Speed (sous-rubriques Burrow/Climb/Fly/Swim) |
| c5 | `ability_scores` | dict `{str,dex,con,int,wis,cha}` | *(—)* | Monster Statistics › Ability Scores |
| c6 | `attack_bonus` | string `"+5"` | `attaque_bonus` | Monster Statistics › Actions › Melee and Ranged Attacks |
| c7 | `damage` | string `"12 (2d6+5) slashing"` | `degats` | Monster Statistics › Actions › Melee and Ranged Attacks |
| c8 | `challenge` | string `"1/2 (100 XP)"` | `challenge` | Monster Statistics › Challenge (› Experience Points) |

*Pourquoi c5/c6+c7 :* la ligne **Ability Scores** figure dans tout statblock du corpus ; la paire
attaque/dégâts est reprise du squelette DRAFT v0 (`annexe_a.py`) car elle constitue l'unité minimale
de jouabilité au combat — continuité avec l'existant assumée et déclarée.

### Optionnels

| # | champ (canonique) | type | clé actuelle | ancre SRD 2014 |
|---|---|---|---|---|
| o1 | `saving_throws` | string `"Wis +0"` | `jets_sauvegardes` | Monster Statistics › Saving Throws |
| o2 | `skills` | string | *(—)* | Monster Statistics › Skills |
| o3 | `damage_vulnerabilities` | list[string] | *(—)* | Monster Statistics › Vulnerabilities, Resistances, and Immunities |
| o4 | `damage_resistances` | list[string] | *(—)* | idem |
| o5 | `damage_immunities` | list[string] | `immunites_degats` | idem |
| o6 | `condition_immunities` | list[string] | *(—)* | idem (rubrique commune aux immunités d'état) |
| o7 | `senses` | string | *(—)* | Monster Statistics › Senses (Blindsight/Darkvision/Tremorsense/Truesight) |
| o8 | `languages` | string | *(—)* | Monster Statistics › Languages (› Telepathy) |
| o9 | `special_traits_md` | markdown | `traits_md` | Monster Statistics › Special Traits (Innate Spellcasting/Spellcasting/Psionics) |
| o10 | `actions_md` | markdown | *(—)* | Monster Statistics › Actions (Multiattack/Ammunition) |
| o11 | `reactions_md` | markdown | *(—)* | Monster Statistics › Reactions |
| o12 | `limited_usage_md` | markdown | *(—)* | Monster Statistics › Limited Usage |
| o13 | `equipment_md` | markdown | *(—)* | Monster Statistics › Equipment |
| o14 | `legendary_actions_md` | markdown | *(—)* | Monsters › Legendary Creatures › Legendary Actions |
| o15 | `lair_actions_md` | markdown | *(—)* | Legendary Creatures › A Legendary Creature's Lair › Lair Actions |
| o16 | `regional_effects_md` | markdown | *(—)* | Legendary Creatures › A Legendary Creature's Lair › Regional Effects |

*Note o10 :* quand la source ne donne qu'une attaque simple, c6/c7 suffisent ; `actions_md` porte
les blocs d'actions textuels (multiattaque, attaques multiples nommées). Les deux peuvent coexister.

### Exemple (valeurs 100 % factices)

```json
{
 "id": "golem-exemple",
 "classe": "creature",
 "nom": "Golem d'exemple",
 "tags": ["exemple"],
 "anchors": [[1, 999]],
 "stats_5e": {
  "type": "Medium construct, unaligned",
  "ca": 14,
  "pv": "33 (6d8+6)",
  "vitesse": "20 ft.",
  "ability_scores": {"str": 15, "dex": 8, "con": 13, "int": 3, "wis": 6, "cha": 1},
  "attack_bonus": "+4",
  "damage": "6 (1d8+2) bludgeoning",
  "challenge": "1/2 (100 XP)",
  "immunites_degats": ["poison", "psychic"],
  "condition_immunities": ["charmed", "frightened"],
  "senses": "darkvision 60 ft., passive Perception 8",
  "langues": "understands the languages of its creator",
  "traits_md": "Exemple tenace : relance un jet de sauvegarde raté par tour.",
  "actions_md": "Multiattaque : deux frappes d'exemple."
 }
}
```

---

## 2. CLASSE `pnj`

`corpus_version: "2014"` — ⛔ **constat de corpus : le SRD 5.1 ne définit AUCUNE statistique
propre aux PNJ** (pas de section « Nonplayer Characters » dans le document publié). Un PNJ qui se
bât se statue **comme une créature** (§1) ; ses rubriques narratives sont des **conventions du
moteur**, sans ancre SRD — signalées ci-dessous conformément à `I-111`.

### Obligatoires

| # | champ (canonique) | type | clé actuelle | ancre SRD 2014 |
|---|---|---|---|---|
| p1 | `role` | string libre | `role` | ⛔ **SANS ANCRE — champ moteur** (fonction narrative du PNJ) |
| p2 | `description_md` | markdown | `description_md` | ⛔ **SANS ANCRE — champ moteur** |

*(+ `nom` first-class, hors `stats_5e`.)*

### Optionnels

| # | champ (canonique) | type | clé actuelle | ancre SRD 2014 |
|---|---|---|---|---|
| q1 | sous-ensemble combat `creature` (o1→o16, et c1–c8 si le PNJ se bat) | cf. §1 | clés §1 | cf. §1 — mêmes ancres Monster Statistics |

### Exemple (valeurs 100 % factices)

```json
{
 "id": "aubergiste-exemple",
 "classe": "pnj",
 "nom": "Aubergiste d'exemple",
 "tags": ["exemple"],
 "anchors": [[2000, 2400]],
 "stats_5e": {
  "role": "source d'informations locale",
  "description_md": "Personnage d'exemple, tient un comptoir imaginaire."
 },
 "transverse": {"fonction": "point d'appel", "portee": "sa salle"}
}
```

---

## 3. CLASSE `objet`

`corpus_version: "2014"` — ancre racine : **SRD 5.1 › Objects › Statistics for Objects**
(les portes/barrières destructibles y ont AC, PV, immunités et seuil de dégâts).

### Obligatoires

| # | champ (canonique) | type | clé actuelle | ancre SRD 2014 |
|---|---|---|---|---|
| b1 | `armor_class` | int | `ca` | Statistics for Objects › Armor Class (table Object's Armor Class) |
| b2 | `hit_points` | string `"18 (4d8)"` | `pv` | Statistics for Objects › Hit Points (table Object's Hit Points, fragile/resilient par taille) |
| b3 | `description_md` | markdown | `description_md` | ⛔ **SANS ANCRE — champ moteur** (ce qu'est l'objet, ce qu'il ferme/cache) |

*b1/b2 obligatoires **pour un objet destructible** (obstacle jouable) ; un objet purement décoratif
peut les laisser vides — vide ⇒ exception signalée à l'ingestion, jamais improvisée.*

### Optionnels

| # | champ (canonique) | type | clé actuelle | ancre SRD 2014 |
|---|---|---|---|---|
| r1 | `size` | enum Tiny…Gargantuan | *(—)* | Statistics for Objects › Hit Points (clé de lecture de la table) |
| r2 | `damage_threshold` | int | *(—)* | Statistics for Objects › Damage Threshold |
| r3 | `damage_immunities` | list[string] | `immunites_degats` | Statistics for Objects › Objects and Damage Types (poison & psychic par défaut) |
| r4 | `damage_vulnerabilities` | list[string] | *(—)* | idem |
| r5 | `damage_resistances` | list[string] | *(—)* | idem |

### Exemple (valeurs 100 % factices)

```json
{
 "id": "porte-exemple",
 "classe": "objet",
 "nom": "Porte d'exemple renforcée",
 "tags": ["exemple"],
 "anchors": [[5000, 5200]],
 "stats_5e": {
  "ca": 17,
  "pv": "27 (5d10)",
  "description_md": "Porte d'exemple en chêne bandé de fer, fermée par un loquet.",
  "size": "Medium",
  "damage_threshold": 19,
  "damage_immunities": ["poison", "psychic"]
 }
}
```

---

## 4. CLASSE `lieu`

`corpus_version: "2014"` — ⛔ **constat de corpus : le SRD 5.1 ne définit AUCUNE statistique de
lieu.** Seules des composantes annexes existent (pièges, maladies, folie…) ; la fiche d'un lieu est
une convention du moteur. Champs sans ancre **signalés**, pas inventés.

### Obligatoires

| # | champ (canonique) | type | clé actuelle | ancre SRD 2014 |
|---|---|---|---|---|
| l1 | `description_md` | markdown | `description_md` | ⛔ **SANS ANCRE — champ moteur** |

*(+ `nom` first-class, hors `stats_5e`.)*

### Optionnels

| # | champ (canonique) | type | clé actuelle | ancre SRD 2014 |
|---|---|---|---|---|
| s1 | `pieges_md` | markdown | *(—)* | SRD 5.1 › Gamemastering Rules › Traps › Traps in Play (tables Sample Traps) |
| s2 | `habitants` | list[id record `creature`\|`pnj`] | *(—)* | ⛔ **SANS ANCRE — champ moteur** (références d'ids) |

### Exemple (valeurs 100 % factices)

```json
{
 "id": "carrefour-exemple",
 "classe": "lieu",
 "nom": "Carrefour d'exemple",
 "tags": ["exemple"],
 "anchors": [[7000, 7400]],
 "stats_5e": {
  "description_md": "Croisement d'exemple entre trois sentiers imaginaires.",
  "habitants": ["golem-exemple"]
 }
}
```

---

## 5. CLASSE `faction`

`corpus_version: "2014"` — ⛔ **constat de corpus : le SRD 5.1 ne contient RIEN sur les
organisations** (aucune règle, aucun tableau). Tout y est convention du moteur — champs sans ancre
**signalés**, pas inventés.

### Obligatoires

| # | champ (canonique) | type | clé actuelle | ancre SRD 2014 |
|---|---|---|---|---|
| f1 | `description_md` | markdown | `description_md` | ⛔ **SANS ANCRE — champ moteur** |

*(+ `nom` first-class, hors `stats_5e`.)*

### Optionnels

| # | champ (canonique) | type | clé actuelle | ancre SRD 2014 |
|---|---|---|---|---|
| t1 | `membres` | list[id record `pnj`] | *(—)* | ⛔ **SANS ANCRE — champ moteur** (références d'ids) |
| t2 | `posture_envers_joueur` | enum allié/neutre/hostile/inconnue | *(—)* | ⛔ **SANS ANCRE — champ moteur** |

### Exemple (valeurs 100 % factices)

```json
{
 "id": "guilde-exemple",
 "classe": "faction",
 "nom": "Guilde d'exemple",
 "tags": ["exemple"],
 "anchors": [[9000, 9100]],
 "stats_5e": {
  "description_md": "Organisation d'exemple fictive, sans existence hors de cette annexe.",
  "membres": ["aubergiste-exemple"],
  "posture_envers_joueur": "neutre"
 }
}
```

---

## 6. CLASSE `sort` (D-252.3, Issue #63)

`corpus_version: "2014"` — ancre racine : **SRD 5.1 › Spellcasting** (les sous-rubriques citées
ci-dessous en sont les sections). Contrairement aux cinq classes précédentes, `sort` n'accueille
jamais de matériau du SRD lui-même (les sorts de base restent hors Partition, cf. `dnd5e-srd-data`) —
elle accueille les sorts **inédits publiés en appendice** d'une campagne, que le SRD ne définit pas
mais dont les *champs* suivent la même grammaire Spellcasting que tout autre sort 5e.

### Obligatoires

| # | champ (canonique) | type | ancre SRD 2014 |
|---|---|---|---|
| v1 | `niveau` | int 0-9 | Spellcasting › Spell Level (0 = tour de magie/cantrip) |
| v2 | `ecole` | enum `abjuration \| invocation \| divination \| enchantement \| evocation \| illusion \| necromancie \| transmutation` | Spellcasting › Schools of Magic |
| v3 | `temps_incantation` | string `"1 action"` | Spellcasting › Casting a Spell › Casting Time |
| v4 | `portee` | string `"36 mètres"` / `"Personnelle"` / `"Contact"` | Spellcasting › Casting a Spell › Range |
| v5 | `composantes` | string, cite au moins V/S/M (+ matériau éventuel) | Spellcasting › Casting a Spell › Components |
| v6 | `duree` | string `"instantanée"` / `"1 minute"` | Spellcasting › Casting a Spell › Duration |
| v7 | `effet_md` | markdown, texte ancré | Spellcasting › Casting a Spell › Effect (le corps décrivant le sort) |
| v8 | `listes_de_classes` | list[string], classes lanceuses ayant accès au sort | Spellcasting › Spell Lists |

*(+ `nom` first-class, hors `stats_5e`.)*

### Optionnels

| # | champ (canonique) | type | ancre SRD 2014 |
|---|---|---|---|
| w1 | `concentration` | booléen | Spellcasting › Combining Magical Effects (Concentration) |
| w2 | `rituel` | booléen | Spellcasting › Casting a Spell (Ritual) |

*Bornes de valeur (v1 niveau, v2 ecole, v5 composantes, v8 non vide, w1/w2 typage booléen)
vérifiées par `schemas.py::Record._check_sort` — au-delà de la simple présence que couvre
`annexe_a.required_fields` pour toutes les classes.*

### Référence par un creature/pnj lanceur — `sorts_connus`

Un record `creature` ou `pnj` qui incante cite ses sorts par id via la clé réservée
`sorts_connus` (liste d'ids `sort`, `schemas.py::Record._sorts_connus`) — réservée à ces deux
classes lanceuses. Le garde zéro-dangling (`validate_form.py`, `emit.py`) résout chaque id contre
les records classe `sort` de la partition, exactement comme `tokens_initial.node_id` résout vers un
node : un id absent ou pointant vers une autre classe est refusé.

### Exemple (valeurs 100 % factices)

```json
{
 "id": "flamme-torsadee",
 "classe": "sort",
 "nom": "Flamme torsadée",
 "tags": ["exemple", "appendice"],
 "anchors": [[12000, 12200]],
 "stats_5e": {
  "niveau": 3,
  "ecole": "evocation",
  "temps_incantation": "1 action",
  "portee": "36 mètres",
  "composantes": "V, S, M (une pincée de suie)",
  "duree": "instantanée",
  "concentration": false,
  "rituel": false,
  "effet_md": "Un jet de flammes imaginaire inflige 6d6 dégâts de feu.",
  "listes_de_classes": ["magicien", "ensorceleur"]
 }
}
```

Et le PNJ lanceur qui le connaît :

```json
{
 "id": "sorcier-exemple",
 "classe": "pnj",
 "nom": "Sorcier d'exemple",
 "tags": ["exemple"],
 "anchors": [[13000, 13100]],
 "stats_5e": {
  "role": "antagoniste mineur",
  "description_md": "Garde un repaire imaginaire.",
  "sorts_connus": ["flamme-torsadee"]
 }
}
```

---

## 7. VÉRIFICATION CROISÉE — LES 2 RECORDS `creature` DU SPECIMEN

**Corpus mesuré :** `kit-p4/partition-beyond-the-vale-of-madness/records/*.md` (copie du poste ;
le dossier miroir côté dépôt est vide aujourd'hui). **N = 2**, les deux de classe `creature`.

**Définition du taux (déclarée, réfutable) :** *obligatoires présents ÷ obligatoires totaux*,
`nom` exclu (first-class). Champ présent = clé présente dans le bloc `stats_5e` du fichier, quelle
que soit sa valeur.

| record | obligatoires présents | taux | optionnels portés |
|---|---|---|---|
| `blood-man.md` | 7 / 8 | **87,5 %** | `immunites_degats`, `jets_sauvegardes`, `traits_md` |
| `ice-fiend.md` | 7 / 8 | **87,5 %** | `immunites_degats`, `traits_md` |

### Écarts listés

1. **`ability_scores` absent des 2 records** — le seul manquement obligatoire. La conversion
   historique (règles AD&D → 5e via `ruletables.py`) produit CA/PV/attaque/dégâts mais jamais de
   bloc de caractéristiques : la source ne les porte pas toujours. À instruire : soit production
   depuis la source quand elle existe + exception signalée sinon (`I-111`), soit rétrogradation du
   champ en optionnel — **arbitrage méta**, pas de mouvement unilatéral.
2. **Format PV partiel** : `pv` porte des entiers nus (`26`, `28`) là où le format SRD attend
   `"moyenne (NdM+k)"`. Forme, non fond : les dés de vie ne figurent pas dans la source convertie.
3. **Couverture optionnelle faible mais conforme** : 3/16 et 2/16 — normal, la source d'origine ne
   décrit ni sens ni langues ni légendaire ; l'absence d'optionnel n'est pas un défaut.
4. **`annexe_a.py` DRAFT v0 ≠ table ci-dessus** : le squelette exige 6 clés creature (dont
   `attaque_bonus`/`degats`, repris ici) mais ignore `type`, `ability_scores`, `challenge`.
   L'intégration de cette table au contrôle de complétude est la **seconde passe** prévue
   (`schemas.py` hors périmètre P1 de la fiche).
5. **Pas de contrôle de complétude ajouté à `tests/converter_test.py`** (option de la fiche) : tout
   test calé sur cette table serait rouge contre le squelette v0 tant que la seconde passe n'est pas
   faite — le test suivra l'intégration, pas l'inverse.

---

## 8. RÉCAPITULATION ET CE QUE JE N'AI PAS PU ÉTABLIR

| classe | obligatoires (hors `nom`) | optionnels | dont sans ancre (signalés) |
|---|---|---|---|
| creature | 8 | 16 | 0 |
| pnj | 2 | sous-ensemble §1 | 2 (p1, p2) |
| objet | 3 | 5 | 1 (b3) |
| lieu | 1 | 2 | 2 (l1, s2) |
| faction | 1 | 2 | 3 (f1, t1, t2) |
| sort | 8 | 2 | 0 |
| **total** | **23** | **27 + héritage §1** | **8** |

⚠️ Le comptage du §0 (« 24 obl. / 30 opt. ») comptait autrement (héritage §1 déroulé) — la
référence est **ce tableau-ci**, définition figée ci-dessus. Ligne `sort` ajoutée par `D-252.3`
(Issue #63, 2026-08-29) — seule classe des six à ne porter aucun champ sans ancre SRD.

**Ce que je n'ai pas pu établir :**

1. **C'est une mesure de ce qui est écrit, pas de ce que le jeu requiert** : le critère
   obligatoire/optionnel est ma définition déclarée (§0.3), révisable par le méta.
2. **Les ancres citent les titres de sections du SRD 5.1 publié**, vérifiés sur UN miroir markdown
   fidèle (licence CC-BY-4.0 incluse dans le miroir) ; je n'ai pas vérifié la pagination du PDF
   officiel page à page.
3. **Les objets magiques ne sont pas couverts** (chapitre Magic Items du corpus 2014) : la classe
   `objet` de cette annexe vise l'objet-décor/destructible ; une extension éventuelle est une
   décision séparée.
4. **N = 2 records, tous deux `creature`** : le taux ne dit rien de `pnj|objet|lieu|faction` — aucun
   record de ces classes n'existe encore dans le specimen.
5. **La localisation canonique du specimen** : je mesure la copie du poste (`kit-p4/`) ; si une
   copie plus récente existe ailleurs hors dépôt, les chiffres sont à reprendre sur elle.
