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
