# Combat dérivé de la fiche — CA, bonus d'attaque, `attack` (I-463, D-274 §1-2)

Au banc `20260831-202617` (tours 21-27), le joueur n'avait **ni classe d'armure
ni bonus d'attaque dans le moteur**, et aucun outil ne résolvait une attaque de
bout en bout : le Director a simulé sept attaques par `resolve_check` avec une
DEX fabriquée et une CA inventée, puis a joué le monstre lui-même. Chaque nombre
manquant était **estimé** au lieu d'être **refusé**.

## 1. Ce qui est dérivé, jamais stocké

`coderain/modules/rpg.py::derived_combat(player, inventory, items)` est une
fonction **pure** : elle rend `{ac, attack_bonus, proficiency, attack_stat,
weapon, armor}` à partir des `stats`, du `level` et de l'équipement **équipé** ;
`player_combat(store)` est sa lecture sur un save. Rien n'est écrit dans
`state.json` — la valeur se recalcule à chaque lecture.

Règle 5e simple, versionnée dans le code :

- **CA** = `10 + mod DEX` sans armure ; avec une armure équipée,
  `armure: + mod DEX`, ce mod plafonné par le `dex_max:` de l'armure s'il en
  porte un ;
- **bonus d'attaque** = mod de la caractéristique de l'arme + **maîtrise**
  (`proficiency_bonus` : +2 au niveau 1, +1 tous les 4 niveaux) ;
- **dés de dégâts** = ceux de l'arme équipée. Sans arme, l'attaque est à mains
  nues (au FOR) et **n'a aucun dé** : `attack` refuse, il n'en invente pas.

Vocabulaire du socle : le « DEX » de la 5e est la stat `agility`, le « FOR » est
`strength` (`sidecar.DEFAULT_CFG["stats"]`). Les valeurs de `stats` sont **déjà**
des modificateurs.

Un modificateur nécessaire absent des `stats` rend `{"error": ...}` — jamais un
0 par défaut (D-274 §1).

Lecture : section `combat` de `get_world_state`, section `— Combat —` de
`ui_sheet`. Les deux la reçoivent en argument dérivé, aucune ne la persiste.

## 2. Champs lus sur `items.md` (objet équipé)

Le Markdown reste la source de vérité ; le miroir `inventory` de `state.json` ne
porte que `{qty, equipped}`.

| champ | exemple | rôle |
|---|---|---|
| `armure:` | `16` | CA de base de l'armure (remplace le 10 nu) |
| `dex_max:` | `2` | plafond du mod DEX qu'ajoute cette armure (optionnel) |
| `degats:` | `1d8+3` | dés de l'arme — même champ que la fiche créature (I-206) |
| `stat:` | `strength` | caractéristique de l'attaque avec cette arme (optionnel) |
| `finesse:` | `true` | arme de finesse : le meilleur des mods FOR/DEX (optionnel) |

Deux armures (ou deux armes) équipées à la fois : la première dans l'ordre des
slugs l'emporte — la lecture est stable d'un appel à l'autre.

## 3. L'outil `attack(attacker, target)`

`mcp_server.py::attack` — famille des outils de jet, à côté de `roll_check` /
`roll_damage`. `attacker`/`target` valent `"player"` ou un slug (entrée de
`characters.md`, sinon record de créature du module, mêmes champs 5e : `ca`,
`pv`, `attaque_bonus`, `degats`).

Il lit les **deux** fiches, jette le d20 + bonus contre la CA (même discipline
RNG que `roll_check` : `seed` + `nonce`, un cran de `rpg["rolls"]` par jet),
roule les dégâts sur touche, puis **applique par le guichet** (D-141,
`apply_envelope`) : `hp_delta` sur le joueur — avec le `downed`/`dead` de D-271
— ou `deltas.enemies.<slug>.hp_delta` sur la cible. Aucune écriture directe de
`state.json` hors nonce.

Retour : `{attacker, target, roll, attack_bonus, total, target_ac, hit,
damage: {formula, dice, total}|null, applied: {...}|null}` (`damage`/`applied`
à `null` sur un raté — rien n'a été jeté ni appliqué).

**Un nombre absent est un REFUS** : pas de CA sur la cible, pas de dés sur
l'attaquant, pas de PV sur une cible que la rencontre ne connaît pas encore →
`{"error": "missing <champ> on <fiche>"}`, prononcé **avant** tout jet (aucun dé
consommé pour rien). Aucun `default=` n'est consulté — en particulier pas ceux
de `monster_bridge.py:214-216` (`ca` absent → 10, `attaque_bonus` absent → 0,
en silence), que `attack` ne traverse jamais ; leur correction est une lane
séparée.

Test d'élément : [`tests/test-element-attaque-i463.py`](../tests/test-element-attaque-i463.py)
(fixtures 100 % synthétiques, D-109/D-206).

## 4. Lecture du bloc projeté — un seul chemin (I-463 volet #316(a), Issue #317)

Mesuré au banc (nuit 06/09, partie 02, tours 13 et 23) : la projection
(`coderain/converter/projection.py::project_into_save`, §2 « records →
characters registry ») écrit le bloc de stats d'un record de module
(`ca`, `pv`, `attaque_bonus`, `degats`, immunités...) en **JSON dans le
CORPS** de l'entrée `characters.md` — ses `attrs` ne portent que
`{"importance": "4"}` pour une créature. Une créature entièrement connue du
module se bouchait quand même (6 `bouchage_enregistre` mesurés sur une
créature dont CA/attaque_bonus/degats étaient déjà écrits) : `attack`
lisait `e.attrs`, jamais le corps, et ne retombait sur `get_record()` que
si l'entrée n'existait pas du tout — ce qui n'était pas le cas ici.

`mcp_server._creature_stats(store, slug)` est le **chemin de lecture
unique** d'un bloc de stats non-joueur, dans cet ordre :

1. entrée `characters.md` de ce slug — le bloc JSON du **corps** est
   parsé (`json.JSONDecoder().raw_decode`, tolère du texte transverse
   ajouté après le JSON — projection.py §2 y ajoute parfois des lignes
   `- clé: valeur`), puis les `attrs` de l'entrée sont fusionnés PAR-DESSUS
   (compat : les fixtures qui écrivent `ca`/`pv`/... directement en attrs,
   comme `tests/test-element-attaque-i463.py`, continuent de fonctionner
   à l'identique) ;
2. à défaut d'entrée : `coderain.converter.aval.get_record()` sur la
   partition du module courant (`_module_partition()`) ;
3. à défaut des deux : `None` — c'est TOUJOURS l'appelant qui prononce le
   refus (jamais un défaut fabriqué ici, D-274 §1).

Deux appelants, zéro lecture dupliquée :

- **`attack`** (`_attack_fiche`) — la fiche `npc` d'une attaque appelle
  `_creature_stats` puis lit `ca`/`attaque_bonus`/`degats`/`pv` dessus,
  exactement comme avant, mais désormais sur l'union corps+attrs ;
- **`start_combat`** (`coderain/mcp/jets_combat.py`) — tout membre
  d'`encounter` sans `monster_template_slug` est résolu via son
  `entity_id` : `_creature_stats` fournit les chiffres,
  `monster_bridge.encounter_member_from_record` construit le membre et
  installe le template 'brute' (`brute:<slug>`). Le record absent est un
  refus explicite AVANT toute ouverture de combat
  (`{"error": "unknown encounter member ..."}`), jamais un tour ouvert
  sans comportement pour ce membre. Un membre qui porte déjà
  `monster_template_slug` traverse inchangé (zéro coût de lecture pour
  l'usage historique, voir `tests/test_rules_engine.py`).

Tests : [`tests/test-element-lecture-fiche-projetee-i317.py`](../tests/test-element-lecture-fiche-projetee-i317.py)
(lecture du corps JSON sans bouchage + repli `get_record()` quand
l'entrée manque), [`tests/test-start-combat-membre-slug-i317.py`](../tests/test-start-combat-membre-slug-i317.py)
(membre d'encounter résolu par slug, refus explicite sur slug inconnu),
[`tests/test-rejeu-tours-blood-man-i317.py`](../tests/test-rejeu-tours-blood-man-i317.py)
(rejeu structurel des tours 13/23 mesurés, fixture synthétique D-109).
