# Processeur d'entrée v-min — table de routage, LE PACK, la métrique (I-373)

*Périmètre de la lane Issue #34 : `coderain/input_processor.py` (le
processeur, pur), `coderain/engine.py` (le point d'accroche —
`Engine.route_input`, `Engine._augment_pack`, `Engine.turn`),
`tests/test-processeur-entree-i373.py` (le harnais). Le ticket cite un
"registre méta MRPG-I-373" et un "schéma des chaînes §6" du vault MVP2 —
inaccessibles depuis ce repo ; ce document explicite les hypothèses prises à
leur place (voir aussi le commentaire `BLOQUÉ :` posté sur l'Issue #34).*

## La table de routage (D-092)

| Entrée                              | Registre       | Où ça part |
|--------------------------------------|----------------|------------|
| `"..."` ou `«...»`                  | parole         | segment routé, aucune écriture |
| `(...)`                              | intériorité    | extrait vers `memory/interiorite-stub.md` (réceptacle stub D-233b, colonne `dit`) |
| texte nu                             | action         | segment routé, aucune écriture |
| ligne entière préfixée d'un `—`      | parole (trou N4) | segment routé, aucune écriture |
| `annuler` / `undo` (entrée entière)  | commande méta  | `Engine.undo_last` |
| `rejouer` / `retry` / `redo` (entrée entière) | commande méta | `Engine.swipe_generate` |
| tout le reste (guillemet/parenthèse non apparié, etc.) | — | LE PACK, avec une proposition de lecture |

**Hypothèse non confirmée — "la ligne PAROLE qui n'a jamais existé (trou
N4)"** : faute d'accès au vault, on route toute ligne préfixée d'un tiret
cadratin `—` vers `parole`, sur la convention française du dialogue en prose
sans guillemets. Si le schéma des chaînes désigne autre chose, corriger
`input_processor.EMDASH_RE` (et son usage dans `process()`) — c'est le seul
endroit où cette hypothèse est encodée.

## LE PACK

Ce que la table ne sait pas router (guillemet ouvert jamais refermé,
parenthèse orpheline, etc.) ne se voit jamais forcé dans un registre : il
monte dans `ProcessedInput.pack`, une liste de `PackItem(text, proposition)`.
`Engine._augment_pack` l'ajoute au prompt système du Director sous un bloc
`# PACK D'ENTRÉE NON ROUTÉ`, explicitement étiqueté "propositions de lecture,
PAS des faits établis". Le processeur ne décide jamais à la place du
Director — voir aussi la garde de provenance [I-462](garde-agentivite-i462.md),
dont l'esprit ("ne jamais écrire un fait sans savoir qui l'a établi") motive
ce choix : rien issu du pack n'est jamais écrit dans un registre géré par
`input_processor` ou `Engine.route_input`.

## Les commandes méta (I-237)

`annuler`/`rejouer` (et leurs synonymes anglais) ne sont reconnus que quand
ils constituent l'ENTRÉE ENTIÈRE (après dépouillement de la ponctuation
finale) — jamais un mot noyé dans une phrase ("il faut annuler le mariage"
reste une action). `Engine.turn` les intercepte avant tout : aucun tour
n'est stocké, aucun appel modèle n'a lieu, la commande dispatche directement
vers son propriétaire déclaré :

- `annuler` → `Engine.undo_last()` (déjà existant, déjà testé —
  `tests/undo_test.py`)
- `rejouer` → `Engine.swipe_generate()` (déjà existant, déjà testé)

Le processeur ne réimplémente ni l'un ni l'autre — il les appelle.

## La métrique native

`ProcessedInput.pack_ratio` = part (en caractères) de l'entrée qui a fini
dans LE PACK plutôt que routée mécaniquement. Émise à chaque tour normal
(pas sur une commande) via le même canal que les events RPG existants
(`Engine._rpg_events`, consommés par `maybe_fold()`), donc sans nouvelle
plomberie côté UI. `input_processor.classify_pack_ratio` en donne une lecture
qualitative dans les mots du ticket : `>= 80%` = "ne trie pas" (le
processeur ne fait quasiment aucun travail), `<= 5%` = "triche" (il prétend
tout router sans jamais admettre l'ambiguïté).

## Ce que ce v-min ne fait pas

- Il ne préserve pas l'ordre relatif exact entre segments routés et texte nu
  quand ils s'entremêlent dans la même ligne (v-min : la classification est
  correcte, l'ordre de reconstruction ne l'est pas forcément) — sans
  conséquence aujourd'hui puisque rien ne réassemble un texte à partir des
  segments.
- Le support biographique D-233b n'existe pas : `memory/interiorite-stub.md`
  est un réceptacle nommément provisoire, à rebrancher dès que D-233b est
  livré (chercher `STUB_INTERIORITE`).
- `opening()` et `continue_story()` ne passent pas par le routeur : ils ne
  reçoivent jamais de texte libre joueur, donc rien à router.
