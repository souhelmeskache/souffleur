# Gabarit d'autorat — secrets (I-159)

*Règle d'autorat pour les entrées `hidden: true` des registres gérés
(`characters.md`, `locations.md`, `factions.md`, `items.md`,
`canon-events.md` — `MemoryStore.gated_registries()`). Périmètre de la lane
Issue #9 : `coderain/validator.py` (le garde), `schemas/validator-secrets.json`
(la forme du rapport), `tests/test-garde-secrets-i159.py` (le harnais).
Zéro matériau de campagne (D-109) — tout exemple ci-dessous est fictif.*

## La règle

**Une entrée `hidden: true` ne porte jamais `pinned: true`, et ne porte
jamais `weight: critical`.**

```markdown
## Le Patron  {#le-patron}
hidden: true
weight: standard        <- jamais "critical" sur une entrée hidden

En secret, le père du joueur.
```

## Pourquoi

`pinned:` et `weight: critical` signifient « toujours dans le contexte,
quelle que soit la scène » — c'est le contrat lu par `assemble()`
(`coderain/memory.py`, la garde `always = e.pinned() or e.weight() ==
"critical"`). Ce test tourne **avant** le test `hidden()` : une entrée à la
fois cachée et épinglée/critique active donc sur CHAQUE haystack, à CHAQUE
passe, à CHAQUE budget — elle atterrit dans la section Secrets sur tous les
tours, y compris ceux où rien ne l'évoque. Le contrat « cachée » (n'apparaît
que sur un déclencheur, D-…, Wave 2) et le contrat « toujours dedans »
(pinned/critical) sont mutuellement exclusifs par construction : combiner
les deux gagne toujours au profit du second, en silence.

Aucun code en aval de `assemble()` ne peut retenir cette fuite sans
court-circuiter la sélection de l'engine — la garde doit donc vivre en amont,
au moment de l'autorat, pas au moment du service.

## Ce qui détecte la violation aujourd'hui

- **`coderain.validator.scan_hidden_forced(store)`** — la fonction pure qui
  scanne les registres gérés et retourne un rapport structuré
  `{registry, slug, why}` par entrée fautive (forme documentée dans
  [`schemas/validator-secrets.json`](../schemas/validator-secrets.json)).
  `why` ne contient jamais le titre ni le corps de l'entrée : un appelant
  peut journaliser ce rapport à n'importe quel niveau de verbosité sans
  divulguer le secret qu'il vient de trouver.
- **`mcp_server._lore_warnings`** appelle cette fonction à chaque
  `load_save` et affiche un COMPTE (jamais un nom) sur le canal que le
  joueur regarde encore ; le détail nominatif part sur `stderr` (la salle
  des machines), jamais sur le canal MCP.
- **`tests/test-garde-secrets-i159.py`** exerce la combinaison sur des
  fixtures synthétiques (hidden+pinned, hidden+critical, et les cas sains
  qui ne doivent PAS déclencher) — c'est le harnais qui garantit que la
  garde continue à mordre même quand aucune campagne réelle n'exerce le cas
  (mesure d'origine I-159 : 0/20 entrées cachées portaient pinned/critical,
  donc la protection ne tenait que par une propriété des DONNÉES, pas du
  code).

## Ce que la garde ne fait pas

C'est un **avertissement**, jamais un blocage : un auteur peut vouloir
exactement cette combinaison (un secret qu'on choisit de forcer en contexte
en permanence n'est alors plus vraiment un secret, mais rien dans le code ne
l'interdit). `scan_hidden_forced` signale ; `_lore_warnings` affiche un
compte ; c'est à l'auteur de lire le détail sur `stderr` et de trancher —
retirer le flag, ou assumer que l'entrée n'est plus cachée en pratique.
