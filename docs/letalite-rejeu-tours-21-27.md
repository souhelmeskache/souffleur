# Rejeu de létalité — tours 21-27 du banc `20260831-202617` (I-463 lane 2, Issue #237)

**Verdict en une phrase :** non — avec la vraie fiche du personnage telle
qu'elle existe aujourd'hui (aucune arme équipée, `inventory: {}`), le combat
n'est pas jouable côté joueur : `attack(player, …)` refuse systématiquement
(D-274 §1, « un nombre absent est un refus ») faute de dés de dégâts, si bien
que la créature ne peut jamais être blessée — la conversion actuelle produit
un combat où le joueur peut uniquement encaisser jusqu'à `downed`.

## Méthode

Au banc, le Director a résolu 7 attaques contre l'« ice-fiend » via
`resolve_check`/`roll_damage`/`apply_envelope` appelés à la main, avec des
nombres **inventés** ad hoc (`ability_scores: {"dex":20}` pour reconstituer
le bonus d'attaque du fiend, `{"str":10}` pour le joueur, CA du joueur
assumée à 10 « sans armure ») — personne ne savait si cette létalité était
celle de la vraie fiche ou celle des inventions. #236 a livré `attack(attacker,
target)` + `derived_combat` (CA/bonus **dérivés** de la fiche, jamais
inventés ; un champ manquant est un refus explicite, jamais un défaut
silencieux). Ce rejeu réutilise ces deux briques, sans y toucher.

**Situation reconstituée au tour 21** (source : save privé
`ttrpg-corpus/saves/beyond-the-vale-of-madness/`, hors périmètre de ce
dépôt — D-109/D-206 ; seuls les champs mécaniques, déjà publiés en clair
dans le corps de l'Issue #237, sont repris ci-dessous) :

| | Valeur réelle (fiche) | Valeur utilisée au banc |
|---|---|---|
| CA joueur | **11** (10 + mod agility 1) | 10 (« sans armure », deviné) |
| Bonus d'attaque joueur | **+2** à mains nues (mod FOR 0 + maîtrise niveau 1) — **mais aucun dé de dégâts** (`inventory: {}`, aucune arme équipée) | +0 (mod STR 10 improvisé, sans maîtrise) |
| CA créature | 15 | 15 (deviné juste — DC 15 = « CA du fiend ») |
| Bonus d'attaque créature | +5 | +5 (deviné juste — DEX 20 factice reconstituant le même mod) |
| Dégâts créature | 9 (1d8+3) slashing | 9 (1d8+3) slashing (identique — lu sur le record réel) |
| PV joueur | 20/20 | 20/20 |
| PV créature | 28 | 28 (jamais entamés) |

Fixture synthétique dérivée de ces valeurs (D-109) : une créature fictive
(`brute-des-glaces-banc`, mêmes champs `ca`/`pv`/`attaque_bonus`/`degats`
que le record réel, nom inventé) et le VRAI bloc `rpg.player` du save
(stats, niveau, inventaire — pas le gabarit `player.md`, resté vide, voir
« Défaut constaté » plus bas). Script complet, rejouable :
[`bench/rejeu-letalite-i463-tours21-27.py`](../bench/rejeu-letalite-i463-tours21-27.py).

Deux passes :

1. **Rejeu littéral** des 7 tours (21 → 27) via `attack()`, à seed fixe, en
   respectant l'alternance réelle du banc (impair = la créature attaque,
   pair = le joueur riposte). Un refus de `attack` est noté tel quel — pas
   contourné (D-274 §1).
2. **Mesure sur 1 000 graines** (0-999), même algorithme que `attack()`
   (`roll_check` puis, sur touche, `roll_damage` — même discipline
   seed+nonce), jusqu'à `downed` du joueur ou 40 tours (plafond du banc).

## Résultat du rejeu littéral (seed = graine du save réel, 1079851431)

```
tour 21 brute-des-glaces-banc -> player               : roll=3 total=8  vs CA 11 hit=False
tour 22               player -> brute-des-glaces-banc : REFUS — missing degats on player
tour 23 brute-des-glaces-banc -> player               : roll=3 total=8  vs CA 11 hit=False
tour 24               player -> brute-des-glaces-banc : REFUS — missing degats on player
tour 25 brute-des-glaces-banc -> player               : roll=5 total=10 vs CA 11 hit=False
tour 26               player -> brute-des-glaces-banc : REFUS — missing degats on player
tour 27 brute-des-glaces-banc -> player               : roll=6 total=11 vs CA 11 hit=True  damage=11
```

Sur cette graine précise, les nombres réels donnent une narration
**différente** du banc (la créature rate trois fois avant de toucher, au
lieu de toucher 4 fois sur 4) — attendu : le banc n'a jamais consommé le
compteur de dés seed+nonce du save (ses jets passaient par des appels
`resolve_check`/`roll_damage` ad hoc), donc aucune reproduction bit-à-bit
n'était possible ni recherchée. Ce qui compte ici : chaque tour où le joueur
attaque est un refus **identique et systématique**, quelle que soit la
graine — `attack` ne jette même pas de dé (D-274 §1, « refus AVANT tout
jet »).

## Mesure sur 1 000 graines

| Métrique | Valeur mesurée (vraie fiche) | Ce qui s'est passé au banc (tours 21-27) |
|---|---|---|
| Chance de toucher, créature → joueur | **74.8 %** (théorique : d20+5 ≥ 11 → 75 %) | 100 % (4 touches / 4 tentatives) |
| Chance de toucher, joueur → créature | **0 %, refus systématique** (aucun dé — pas d'arme équipée) | 0 % (0 touche / 3 tentatives, mais un jet était possible : ~30 % de chance théorique avec les nombres inventés) |
| Dégâts moyens par touche (créature) | 7.49 (1d8+3, théorique 7.5) | 6.25 (moyenne des 4 touches : 5, 5, 8, 7) |
| Dégâts moyens par attaque tentée (créature) | 5.61 | 6.25 |
| Tours médians avant `downed` du joueur | **7** | 7 (tour 27) |
| Tours avant mort de la créature | **jamais** (0 % — le joueur ne peut jamais la toucher) | jamais (28 PV inchangés) |
| Probabilité de victoire du joueur | **0 %** | 0 % (le combat s'est arrêté au tour 27, `downed`) |

(Script : `bench/rejeu-letalite-i463-tours21-27.py`, fonction
`mesure_1000_graines`. Sortie brute reproductible en relançant le script —
aucune graine n'est câblée en dur dans le résultat agrégé.)

## Écart avec le banc

- **Les nombres de la créature, le Director les avait devinés juste.** Le
  DEX 20 fabriqué reconstituait exactement le bonus d'attaque réel (+5), et
  la CA 15 assumée pour la créature était la vraie CA. Sur ce
  personnage-créature précis, l'invention n'a introduit aucun biais
  numérique — coïncidence heureuse, pas une garantie générale (rien dans
  le process de l'époque ne vérifiait cet accord).
- **La CA du joueur était sous-estimée d'1 point** (10 deviné vs 11 réel,
  faute du modificateur d'agility +1) — un biais mineur qui rendait la
  créature *légèrement* plus précise au banc qu'en réalité (80 % vs 75 %
  théorique de chance de toucher).
- **L'écart qui compte n'est pas numérique, il est structurel :** le banc a
  laissé le joueur *tenter* trois ripostes (résolues par `resolve_check`
  sans jamais vérifier qu'une arme existait), alors que la vraie fiche du
  personnage — `inventory: {}`, `player.md` jamais rempli au-delà du
  gabarit — ne porte aucune arme. `attack()`, lui, refuse ces trois tentatives
  avant même de lancer un dé. Le banc a donc *joué* un combat légèrement
  plus favorable au joueur (30 % de chance de toucher par tentative,
  quoique jamais concrétisée sur ces 3 essais) que ce que la conversion
  réelle permet aujourd'hui (0 %, structurellement).

## Défaut constaté (hors périmètre de correction de cette lane)

Le `player.md` du save réel (`ttrpg-corpus/saves/beyond-the-vale-of-madness/`)
est resté au gabarit vide depuis sa création (`stats: strength 0, dexterity 0,
constitution 0, intelligence 0, wisdom 0, charisma 0` — jamais édité), avec
en outre une incohérence de vocabulaire entre le gabarit (qui illustre
`agility` dans son propre commentaire) et le contenu écrit (`dexterity`) —
aucun des deux n'est le nom de champ que lit `derived_combat`
(`STAT_DEX = "agility"`, `coderain/modules/rpg.py:136`). Les stats
*effectivement* utilisées par le moteur vivent dans `state.json` sous
`rpg.player.stats` (elles, bien nommées : `agility: 1`, etc.), pas dans
`player.md` — source de vérité documentée comme telle mais restée
désynchronisée du run réel. Plus significatif : **aucune arme n'a jamais été
ajoutée à l'inventaire du joueur** pour cette partie — la conversion du
module (kit P4) peuple les records de créatures (`ca`/`pv`/`attaque_bonus`/
`degats`), mais rien n'équipe le joueur d'une arme de départ. C'est ce vide
d'équipement, pas un bug de `derived_combat`/`attack` (qui se comportent
exactement selon leur contrat, D-274 §1), qui rend ce combat non jouable
pour le joueur aujourd'hui. Pertinent pour I-1650 (pont complet) : la
question n'est plus seulement « le pont convertit-il bien les créatures ? »
mais aussi « le pont — ou la création de personnage en amont — donne-t-il
au joueur de quoi se battre ? ». Aucune correction n'est faite ici (garde de
la lane) ; à trancher dans I-1650 ou une issue dédiée.

## Rejouer cette mesure

```bash
python bench/rejeu-letalite-i463-tours21-27.py
```

Script autonome, 100 % hors-ligne, fixture entièrement synthétique
(D-109/D-206) — ne lit ni n'écrit rien dans `ttrpg-corpus`.
