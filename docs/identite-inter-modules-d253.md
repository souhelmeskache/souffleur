# Identité inter-modules — convention de slug (D-253.2, Issue #72)

*Registre méta MRPG-D-253 règle 2 — comble le trou §3.2 de
[`docs/audit-2-materiel-campagne-d252.md`](audit-2-materiel-campagne-d252.md).
FORMES ET RÈGLES UNIQUEMENT, exemples synthétiques (D-109) : aucun
matériau de campagne réel.*

## Le problème

Un PNJ, une faction ou un lieu peut réapparaître dans PLUSIEURS modules
d'une même campagne convertis séparément (`coderain/converter`). Chaque
module ne connaît que sa propre partition (`Partition.ids()`,
`coderain/converter/schemas.py`) : rien, avant D-253.2, ne garantissait
qu'une entité récurrente porte le même identifiant d'un module à l'autre —
la reconnaissance reposait sur une convention tacite, jamais vérifiée.

## La règle

**Une entité = un slug pour toute la campagne, quel que soit le module.**

Le slug est l'id kebab de la primitive qui porte l'entité — typiquement un
`Record` de classe `pnj`, `faction` ou `lieu` (`RECORD_CLASSES`,
`coderain/converter/schemas.py:20`). Une fois qu'un module a introduit une
entité récurrente sous un slug donné, tout module ultérieur de la même
campagne qui la référence ou la re-décrit RÉUTILISE ce même slug — il ne
lui en forge pas un nouveau.

### Comment se forge le slug

- **Format** : kebab minuscule ASCII, déjà imposé par `check_id`
  (`coderain/converter/schemas.py:135-141`, regex
  `^[a-z0-9]+(?:-[a-z0-9]+)*$`) — ce contrat ne change pas.
- **Normalisation recommandée** : dériver le slug du nom canonique retenu
  par l'auteur via la translittération déjà utilisée à l'installation d'un
  module (`coderain/converter/install.py::_slugify` — accents français
  translittérés, minuscule, tirets). Rien n'oblige cette fonction précise ;
  ce qui compte est que le slug soit **figé dès sa première apparition**
  dans la campagne et jamais redérivé à chaque module suivant.
- **Langue** : le nom source peut être en anglais ou en français selon le
  corpus ; le slug se fixe sur le nom que l'auteur retient comme canonique
  pour la campagne, une fois pour toutes.
- **Collisions** : si le slug naturel d'une NOUVELLE entité heurte un id
  déjà pris par une entité DIFFÉRENTE ailleurs dans la campagne, il se
  désambiguïse explicitement (suffixe `-2`, qualificatif de lieu/faction,
  etc.) — jamais silencieusement. Voir aussi le mécanisme de suffixage déjà
  en place côté scénarios/saves (`coderain/memory.py::_unique_slug`), même
  logique appliquée manuellement ici puisque rien n'installe encore ces
  slugs automatiquement multi-module.

### Renommage diégétique (alias)

Un PNJ démasqué, une faction qui change de nom en jeu, un lieu rebaptisé :
l'entité **garde son slug d'origine** pour toute la campagne. Le nom qui
change est un ATTRIBUT porté par la primitive (`Record.nom`, ou une entrée
de `Record.transverse`/`tags` pour les noms d'usage successifs), jamais un
nouveau slug ni un nouvel id.

### Exemple synthétique — cas conforme

Module A (`garde-du-pont`) introduit un PNJ récurrent :

```python
Record("garde-huygens", "pnj", "Huygens",
       {"role": "garde", "description_md": "Garde du pont-levis."},
       anchors=[(0, 10)])
```

Module B (`siege-du-fort`), plus loin dans la campagne, RÉFÉRENCE ce même
PNJ (par exemple via `Node.heritage[].porte`, D-183) sous le **même slug**
`garde-huygens` — même s'il ne le redéfinit pas lui-même. La garde de
résolution (ci-dessous) le confirme : la référence de B résout contre
l'ensemble de la campagne, pas seulement contre B.

### Contre-exemple — slug suspect

Module B introduit à la place un *nouveau* PNJ `capitaine-huygens` avec le
même nom d'usage déclaré `"Huygens"`. Rien n'interdit mécaniquement que ce
soit vraiment une entité différente (un parent, une coïncidence de nom) —
mais la garde le SIGNALE : deux slugs distincts portant le même nom
d'usage sont probablement la même entité mal identifiée, à trancher par
l'auteur (fusion sous un seul slug, ou confirmation qu'il s'agit bien de
deux personnages distincts).

## La garde de résolution inter-modules

`coderain/converter/validate_inter_module.py::cross_module_report`

```python
from coderain.converter.validate_inter_module import cross_module_report

rapport = cross_module_report([partition_module_a, partition_module_b])
rapport["orphelines"]      # liste de chaînes — échec explicite si non vide
rapport["slugs_suspects"]  # liste de chaînes — signalement, jamais un refus
```

- Prend un **ensemble** de `Partition` (plusieurs modules convertis d'une
  même campagne) et vérifie que toute référence pouvant viser une entité
  hors de sa partition d'origine — `heritage.porte`, `rattachement`
  (personnage/fenêtre), et les autres références du même genre listées
  dans `schemas.py` (lien, débouché, secret, patch, ressource, sort,
  événement) — résout vers une entité existant **quelque part dans
  l'ensemble fourni**, pas nécessairement dans son propre module.
- Une référence qui ne résout dans **aucune** des partitions fournies est
  un **échec explicite**, listée dans `orphelines` avec le module, la
  primitive source et l'id ciblé.
- Deux slugs distincts (classes `pnj`/`faction`/`lieu`) partageant le même
  nom d'usage déclaré sont **signalés** dans `slugs_suspects` — jamais un
  refus : ça peut être une coïncidence légitime.
- **La garde intra-module zéro-dangling existante
  (`coderain/converter/validate_form.py::validate_form`) reste
  inchangée** — elle continue de vérifier une seule partition à la fois ;
  `cross_module_report` ajoute l'étage inter-modules par-dessus, elle ne le
  remplace pas. Une référence inter-modules conforme est *dangling* vue
  d'une seule partition (attendu) et *résolue* vue de l'ensemble de la
  campagne.
- **Rétrocompatibilité totale** : fonction appelable, jamais invoquée
  automatiquement par le pipeline existant — aucun crochet obligatoire.
  L'appelant (CI d'une lane multi-modules, script de revue, contrôle
  manuel) décide quand et sur quel ensemble de modules l'exécuter.

Tests de référence : `tests/test-identite-inter-modules-d253.py` (deux
mini-partitions synthétiques partageant un PNJ récurrent — cas conforme,
référence orpheline, slugs suspects, pas de faux positif).
