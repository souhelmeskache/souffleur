# Mesure F1.4 (Issue #342) — prérequis des débouchés de scénario

*Mesure pure (fiche brique 1, §F1.4) : aucune évaluation runtime des
prérequis (F1.1), aucun nouveau type (F1.2), aucune modification de la
partition émise. Rapport chiffres-seuls (D-109/D-282 règle 4 — dépôt
public) : aucun extrait de corps_md/objectif_md du module, uniquement des
comptes et des ids machine.*

**Rejeu** : `python -m coderain.converter mesure-f14 <partition_dir> --md
<fichier.md>` (`coderain/converter/mesure_f14.py`, testé par
`tests/test-mesure-prerequis-scenario-f14.py` sur fixture synthétique).

## Partition mesurée

- Module : `beyond-the-vale-of-madness` (hors repo, `ttrpg-corpus` /
  `corpus_dir()`) — partition convertie `partition-beyond-the-vale-of-
  madness`, `version_convertisseur: 0.3.0+local`.
- Date de la mesure : 2026-09-06 (partition convertie le 2026-08-25).
- 61 nœuds au total : **4 nœuds d'altitude `scenario`** (`para-1`, `para-3`,
  `para-12`, `para-60` — ids machine confirmant le PV vault H-776) et
  **57 nœuds d'altitude `scene`**.

## Nœuds scénario — objectif_md

- Nœuds scénario sans `objectif_md` : **0 / 4**.

## Par nœud de scénario

| node | débouchés | sans prérequis | types présents | négations | cible_id | ouvre_vers_md |
|---|---|---|---|---|---|---|
| `para-1`  | 2 | 1 (`entree-grottes`) | flag | 0 | 2 | 0 |
| `para-3`  | 2 | 1 (`chateau-fuite`) | entite_vivante (via `non`) | 1 | 2 | 0 |
| `para-12` | 3 | 3 (`grottes-cour`, `grottes-falaise`, `grottes-retour`) | — | 0 | 3 | 0 |
| `para-60` | 2 | 1 (`sortie-butin`) | flag | 0 | 0 | 2 |

Débouchés SANS prérequis, tous nœuds scénario confondus (id machine) :
`entree-grottes`, `chateau-fuite`, `grottes-cour`, `grottes-falaise`,
`grottes-retour`, `sortie-butin` — **6 sur 9**.

## Total scénario

- Débouchés total : **9**.
- Débouchés sans prérequis : **6** (3 avec).
- Types de prérequis : `entite_vivante` 1, `flag` 2, `quete_etat` 0.
- Négations (`non(<atome>)`, D-187) : 1.
- Cible : `cible_id` 7, `ouvre_vers_md` 2.

## Total scène (57 nœuds, agrégé)

- Débouchés total : **0**.
- Débouchés sans prérequis : 0 (0 avec).
- Types de prérequis : `entite_vivante` 0, `flag` 0, `quete_etat` 0.
- Négations : 0. Cible : `cible_id` 0, `ouvre_vers_md` 0.

Les nœuds d'altitude `scene` ne portent structurellement aucun débouché —
`attach_scenario` (`coderain/converter/schemas.py`) exige l'altitude
`scenario` (fiche SCÉNARIO §1). Le compte 0 confirme cette contrainte sur
la partition réelle, il ne signale rien à corriger.

## Signaux d'axe (D-282 règle 4)

Occurrences, dans le `corps_md` des 4 nœuds scénario, de motifs suggérant
un prérequis d'axe LIEU ou HORLOGE non déclaré en `prerequis_etat`
structuré (motifs listés dans `coderain/converter/mesure_f14.py`,
`SIGNAUX_AXE`) :

| axe | occurrences | nœuds touchés |
|---|---|---|
| lieu     | 0 | — |
| horloge  | 2 | `para-1`, `para-60` |

## Réponse au critère C1.4

Sur cette partition réelle, **6 débouchés de scénario sur 9 sont sans
prérequis** (`entree-grottes`, `chateau-fuite`, `grottes-cour`,
`grottes-falaise`, `grottes-retour`, `sortie-butin`). Ce nombre est > 0 :
conformément au critère déclaré, F1.1 et l'item vault I-194 reçoivent la
question « le module les porte-t-il, ou le convertisseur les rate-t-il ? »
avec ces 6 ids.

Par ailleurs, 2 occurrences d'un motif d'axe HORLOGE sont détectées dans le
corps de nœuds scénario (`para-1`, `para-60`) sans `prerequis_etat` de ce
type déclaré — signal à instruire par F1.1/F1.2 (D-282 règle 4 : le module
porte déjà ce besoin en texte).
