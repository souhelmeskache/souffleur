# LE STOCK DE FORMES — vocabulaire composable versionné (D-261)

Quand l'Auteur doit écrire du scénario (cas 2/3 de D-117 — le joueur hors des
sentiers), il ne crée pas librement : il **choisit dans un stock de formes
narratives publiques éprouvées**, les assemble et les colorie à la campagne.
Ce dossier est ce stock.

## Trois index, une colonne vertébrale

| fichier | source | contenu |
|---|---|---|
| `propp.json` | Vladimir Propp, *Morphologie du conte* (1928) | 31 fonctions du conte merveilleux, ENCHAÎNABLES dans un ordre typique |
| `polti.json` | Georges Polti, *Les 36 situations dramatiques* (1895) | 36 situations dramatiques |
| `atu.json` | index Aarne-Thompson-Uther (classification folkloriste internationale) | une sélection raisonnée d'environ 30 contes-types, PAS l'index entier |

Amendement 1 de D-261 : cet index COMPOSABLE est la colonne vertébrale — les
atomes type tropes (TV Tropes et assimilés) restent hors périmètre, en
surface seulement, jamais ingérés ici. **Zéro scraping TV Tropes.**

## Licence — domaine public uniquement

Les trois systèmes cités (fonctions de Propp, situations de Polti, index
Aarne-Thompson-Uther) sont des **classifications structurelles** dans le
domaine public ou largement documentées comme référence académique libre —
aucune n'est un texte narratif protégé. Les descriptions de ce dossier sont
des **paraphrases originales, écrites pour ce repo**, jamais une copie d'une
traduction ou édition protégée. Aucun texte de conte, aucune œuvre nommée
n'est reproduit ici : les formes sont décrites par leur fonction structurelle
seule (ce qu'elles demandent, avec quoi elles s'enchaînent), jamais par un
résumé d'une œuvre précise sous droits.

## Le schéma d'entrée

Chaque forme, dans chacun des trois fichiers JSON, porte exactement ces
champs :

```json
{
  "id": "propp-08",
  "nom": "Méfait ou manque",
  "source": "propp",
  "description": "2 à 4 lignes — ce que la forme raconte structurellement.",
  "exige": ["ce que la forme demande : adversité, coût, renversement…"],
  "compose_avec": ["ids d'autres formes avec lesquelles celle-ci s'enchaîne"]
}
```

- `id` — stable, préfixé par la source (`propp-`, `polti-`, `atu-`), jamais
  réutilisé pour une autre forme une fois publié.
- `exige` — ce que la forme EXIGE du récit pour fonctionner (amendement 3 de
  D-261 : les briques portent l'efficacité, jamais l'unicité — une forme
  choisie doit répondre à une pulsion de personnage ET satisfaire sa part
  d'adversité).
- `compose_avec` — les ids avec lesquels cette forme s'enchaîne
  naturellement ; permet à l'Auteur de composer une suite de formes plutôt
  que d'en piocher une seule isolée.

## Consommation

`coderain/formes.py` charge ce stock (`charger_vocabulaire()`) et porte la
garde de forme sur toute déclaration d'Auteur qui s'en réclame
(`valider_declaration`) — voir ce module pour le contrat complet. Ce dossier
ne contient QUE le vocabulaire versionné ; aucun code n'y vit.
