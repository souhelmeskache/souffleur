# CONVERSION DKS — passes P-CONV-1 à P-VAL, rapport d'écarts consolidé (2026-08-29)

*Rapport-forme de la lane `lane-75` (Issue #75, mandat I-328, D-216). FORMES,
MESURES ET VERDICTS UNIQUEMENT (`D-109`) — zéro extrait narratif du module
au-delà du minimum d'ancrage technique (ids machine déjà publics dans
[`docs/pconv0-socle-formes.md`](pconv0-socle-formes.md)). Les passes P-CONV-1
à P-CONV-3 et P-VAL ont été exécutées et mergées sur `main` les 26-27 août
2026 (commits `98e3e28`, `ac4bd3a`, `01f3aac`, `a7a718b`, `8827ea4`) sans que
leur rapport-forme individuel soit versé sous `docs/` — ce document comble ce
trou et couvre en plus l'application des deux règles de régime trans-modules
D-253.1/D-253.2 à la partition réelle (point 4 de l'Issue #75, `lane-75`,
[`tests/test-dks-regime-trans-modules.py`](../tests/test-dks-regime-trans-modules.py)).*

---

## 1. Vue d'ensemble — partition finale (partition-pconv3)

| mesure | valeur |
|---|---|
| nodes | **361** (343 entrées verbatim + 1 ouverture + 17 pointeurs S2, inchangé depuis P-conv-0) |
| records | **35** = 10 créatures/PNJ + 25 objets |
| tables | **5** `RollTable` d100 contiguës |
| secrets | **4** |
| tensions | **9** (D-218) |
| ressources | **19** cartes (`type: carte`, D-216 §2) |
| trajectoire / conditions (Aventure) | **3 / 1** — les 4 déclencheurs sont tous de type `etat` (aucun `date`/`delai`) |
| verdict `validate_form` | **VERT** à chaque passe (form_errors/coverage_gaps/overlaps/unanchored = 0) |
| suites locales | ALL SUITES PASSED à chaque commit (44→52 fichiers sur la période, trinity exclu I-270) |

## 2. Records (P-CONV-1) — statblocks custom + collision règles-convertisseur

**10 créatures/PNJ distincts**, chacun devenu un record propre avec ancre
dédiée (point 3 de l'Issue #75) :

| verdict | slugs | mécanisme |
|---|---|---|
| ancre SRD directe (6) | `cultist`, `goblin-warrior`, `kobold-warrior`, `skeleton`, `giant-wolf-spider`, `zombie` | `ancre_srd` référence `dnd5e-srd-data==0.3.0`, zéro copie de stats |
| variante SRD documentée (1) | `forest-bat` | `ancre_srd=bat` + `delta_vs_ancre` (pv/ca/taille/vitesse/cr) — jamais orpheline sans ancre |
| custom complet (3) | `darek-brewmont` (PNJ allié), `giant-centipede` (absent du dataset SRD malgré présence dans le SRD 5.1 canonique), `death-knight` (antagoniste récurrent) | stats extraites par `statblock_core` (filet anti-typo dialecte source : Armour Class britannique, CR "N (YXP)", attaques `nom +bonus → dés`), `ConversionException` si AC/HP absents |

**Collision règles-convertisseur E2 tranchée** : `death-knight` porte
`persistent: ["pv"]` — les PV du death knight survivent entre ses trois
rencontres (p30/42/72/80). Ceci a été absorbé comme **fonctionnalité
moteur générale** (`etat-persistant-inter-combats`, commit `a7a718b`,
`tests/test_etat_persistant.py`), pas une rustine DKS : la grammaire
`persistent: attr1, attr2` déclarée côté auteur est réutilisable par tout
module futur. Écart source consigné au record : `INITWON` (p41) porte
32 PV contre 28 ailleurs dans le module — retenu à 28, écart documenté dans
`death-knight.md`, jamais moyenné ni deviné.

**25 objets** (17 gains + 8 montants gp de 20 à 2000 gp), dont l'objet clé
du module (pieu de l'arbre rouge) — recompte mécanique robuste aux lignes
coupées par le layout PDF (écart nommé au commit : la regex v0 sous-comptait
les phrases de gain coupées).

**11 poses `tokens_initial` (E3)** — encounters multi-tokens + PNJ allié :
forme `[{node_id, count, placement_md}]`, garde zéro-dangling en émission
(`emit.write_partition` refuse tout `node_id` inconnu).

## 3. Cartes en Ressource (P-CONV-3) — point 2 de l'Issue #75

**19 pages-cartes → 19 records `Ressource` de type `carte`**, jamais
interprétées comme texte :

| mesure | valeur |
|---|---|
| export | direct `DCTDecode` (zéro OCR, zéro traitement d'image), 902 px de large |
| pages couvertes | 99–117, contiguës, vérifiées `== range(99, 118)` |
| rattachement | `node_id` (17 pointeurs S2 `tilepage-N`/`submap-N`) — primitive générique `Ressource{id, type, node_id/page, fichier, anchors}`, premier cas d'usage `carte` (D-216 §2) |
| **113 pointeurs de placement du texte** | résolus vers les nodes-pointeurs S2 (pas directement vers les fichiers image) — chaque référence textuelle "Find tilepage N" cite le node porteur, qui porte à son tour la Ressource ; zéro dangling sur cette chaîne (`validate_form` couvre `ressource.node_id`) |
| fichiers poste | 19 JPEG (`resources/*.jpg`), **hors git** (D-217 poste uniquement) — le dépôt ne porte jamais le binaire, seule la partition référence son chemin poste |
| taille totale | > 1 Mo (mesure de non-vacuité, pas un contenu cité) |

## 4. Événements, secrets, tensions (P-CONV-2)

Trajectoire de l'antagoniste (backstory) + condition monde extraites en
3 `Evenement` de rubrique `trajectoire` + 1 de rubrique `condition` — chacun
avec `perturbations` typées (`transplantee`/`abandonnee`, garde anti-rail
D-120 §5.1), 4 secrets (`Secret`, garde caméra D-184 respectée : aucune fuite
en clair dans `directeur.md`), 9 tensions traversantes (`Tension`, D-218,
catégories menace/horloge/échéance/coût/choix/révélation, chacune ancrée sur
un `node_id` réel).

## 5. Régime trans-modules appliqué à la partition réelle (point 4, Issue #75)

Point neuf de cette lane (`tests/test-dks-regime-trans-modules.py`, section 4
sur la partition-pconv3 réelle, chargée en mémoire depuis `corpus_dir()`) :

**Règle 1 — échéancier D-253.1** (`coderain/echeancier.py::extraire`) :
les 4 déclencheurs (3 trajectoire + 1 condition) sont **tous de type
`etat`** — aucun `date`/`delai`. Mesure : `vivantes=0`, `echues=0`,
`etats=4`, `avertissements=0`. Conséquence directe : la garde de
ré-émission (`garder_reportage`) n'a, pour ce module précis, **rien à
protéger au sens calendaire** — les 4 conditions restent listées pour
inventaire complet (`Echeancier.etats`, hors périmètre garde v0 documenté
dans `echeancier.py`), mais un futur re-script de DKS ne peut pas être
mécaniquement refusé sur ce module pour perte de condition datée. Ce n'est
pas un défaut du convertisseur : c'est une mesure sur le module lui-même
(gamebook à déclencheurs narratifs, pas de front daté).

**Règle 2 — identité/résolution inter-modules D-253.2**
(`coderain/converter/validate_inter_module.py::cross_module_report`) :
appliquée à `[partition-pconv3]` seule (DKS est à ce jour l'unique module
converti de sa campagne) — verdict **`orphelines: []`**. La garde tourne
sans échec, ce qui confirme que toute référence inter-primitives de DKS
résout déjà à l'intérieur de son propre module (cohérent avec le zéro
dangling de `validate_form` §1). `slugs_suspects` vide de fait, aucun
deuxième module n'existant encore pour partager un nom d'usage. La
convention de slug (kebab, figé à la première apparition) est déjà
respectée par construction — les 35 records DKS sont tous des slugs kebab
uniques, aucune collision à désambiguïser.

## 6. Écarts ouverts (PRIMITIVE GENERALE proposée, point 5 de l'Issue #75)

| # | écart | statut | proposition |
|---|---|---|---|
| **checks=0** | `mapping-regles.json` porte `checks: 0` à CHAQUE passe (pconv0 → pconv3). `coderain/converter/aval.CHECK_RE` attend la forme `"DC N <ability> check"` ; le phrasé réel mesuré dans la source est `"<verbe> <compétence/caractéristique>[,] DC N"` (ex. formes : `"Make a perception check, DC N"`, `"roll survival, DC N"`, `"wisdom save, DC N"`) — DC systématiquement APRÈS le nom de compétence, jamais avant. | **ouvert, non résolu par cette lane** (remontée initiale pconv0, jamais reprise en pconv1 malgré l'annonce du rapport pconv0 §4.3) | Généraliser `CHECK_RE` à l'ordre inverse (`<skill_or_ability>[,]? DC N (check\|save\|saving throw\|roll)`) + table de correspondance compétence→caractéristique 5e (perception/survival→wisdom, stealth→dexterity, thieves' tools→dexterity, etc.). C'est une forme générique — d'autres modules à phrasé "compétence d'abord" en bénéficieraient — jamais une rustine DKS. **Décision à trancher hors P1 de cette lane** : la table compétence→caractéristique touche `aval.py` (régime de jet D-089, facteurs A-F) et mérite son propre passage, pas un patch en fin de pipeline de conversion. Signalé en commentaire d'Issue. |

Aucun autre écart nommé aux passes P-conv-1/2/3/P-val n'est resté sans
verdict : E1 (Ressource) posé au schéma D-216 §2, E2 (état persistant)
absorbé comme fonctionnalité moteur générale, E3 (encounters multi-tokens)
couvert par `tokens_initial`, E4 (instructions procédurales spatiales)
resté en corps_md verbatim (accepté v0, aucune primitive dédiée demandée),
E5 (règles solo) hors kit par construction (installation du scénario, pas
matériel de partition).

## 7. Suites vertes

`run_tests.py` : **ALL SUITES PASSED** avant et après le point 5 de cette
lane (`tests/test-dks-regime-trans-modules.py` ajouté), zéro régression sur
les 52+ suites existantes, trinity exclu (I-270, échec préexistant).
