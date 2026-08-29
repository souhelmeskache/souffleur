# CONVERSION DKS — P-CONV-4, enrichissement (D-252) + détection des jets (D-254)

*Rapport-forme de la lane `lane-80` (Issue #80, D-252, D-254). FORMES, MESURES
ET VERDICTS UNIQUEMENT (D-109) — zéro extrait narratif du module au-delà du
minimum d'ancrage technique (ids machine déjà publics dans
[`docs/pconv0-socle-formes.md`](pconv0-socle-formes.md) et
[`docs/pconv1-3-pval-ecarts.md`](pconv1-3-pval-ecarts.md)). La partition
`partition-pconv3` (référence : rapport ci-dessus) a été ré-émise en
`partition-pconv4` hors git (D-178, `corpus_dir()`) via
`outils/emettre_partition_pconv4.py`, sur le modèle des passes précédentes
(`emettre_partition_pconv1/2/3.py`), lui-même privé (dépôt `ttrpg-corpus`,
commit `2787598`) — les quatre extensions D-252 étaient déjà mergées sur
`main` avant le lancement de cette lane (schémas `coderain/converter/schemas.py`
+ suites `tests/pconv_objets_magiques_test.py`,
`tests/test-table-consultation-d252-4.py`,
`tests/document-illustration-d2521-test.py`,
`tests/test-classe-sort-d252c.py`) : cette passe applique ces primitives
existantes au matériau réel, elle n'ajoute aucun code moteur nouveau.*

---

## 1. Vue d'ensemble — partition-pconv4

| mesure | pconv3 (référence) | pconv4 | delta |
|---|---|---|---|
| nodes | 361 | **361** | 0 |
| records | 35 | **35** | 0 |
| — dont objets requalifiés magiques (D-252.2) | 0 | **8** | +8 |
| tables d100 | 5 | **5** | 0 (5/5 restent mode `aleatoire`) |
| secrets | 4 | **4** | 0 |
| tensions | 9 | **9** | 0 |
| ressources | 19 (cartes) | **22** (19 cartes + 3 documents/illustrations) | +3 |
| sorts inédits (D-252.3) | 0 | **0** | 0 |
| jets détectés (D-254) | 0 (mesuré 51 en re-passage lane-75, non ré-émis) | **51** (42 `check` + 9 `saving_throw`) | mesuré directement sur pconv4 |
| verdict `validate_form` | VERT | **VERT** | inchangé |
| coverage gaps/overlaps | 0/0 | **0/0** | inchangé |
| mass_alarms | 4 (nominal, pconv3) | **0** | -4 |
| régime trans-modules (orphelines) | 0 | **0** | inchangé |
| suites locales | ALL SUITES PASSED | **ALL SUITES PASSED** | trinity exclu (I-270) |

## 2. Objets magiques (D-252.2) — 8/25 objets requalifiés

Sur les 25 records `objet` de la partition (17 gains + 8 montants gp), **8**
portent désormais les champs dédiés (`type_objet`, `rarete`, `harmonisation`,
`activation`, `effets_md`) :

| type_objet | rarete | nombre |
|---|---|---|
| arme | rare | 1 |
| arme | peu_commun | 2 |
| merveille | peu_commun | 1 |
| anneau | peu_commun | 1 |
| potion | peu_commun | 1 |
| parchemin | commun | 2 |

**Critère retenu** : les 5 objets déjà marqués `tags: ["gain", "magique"]` à
l'émission P-CONV-1 (armes/anneau/cape à propriété magique permanente) +
2 parchemins de sort nommés et 1 potion nommée (items DMG à rareté connue,
tag `consommable` existant). **Objets examinés et volontairement NON
requalifiés** (judgment call consigné, pas un oubli) : les items `consommable`
de nature végétale/organique sans nom de catalogue DMG (baies, spores) sont
restés des objets ordinaires — leur effet est déjà entièrement porté par
`description_md`, aucune primitive D-252.2 n'y ajoute d'information vérifiable.
**Zéro** `secret_lie_id` posé à cette passe : aucun des 8 objets requalifiés
ne porte de malédiction/identification cachée dans le module (la primitive
existe et est testée synthétiquement — `tests/pconv_objets_magiques_test.py`
— mais n'a aucune matière source à câbler ici).

Un objet est resté à dessein hors du périmètre de requalification malgré sa
portée narrative (l'objet-clé du module, seul moyen de vaincre l'antagoniste
récurrent définitivement) : sa particularité est une règle narrative unique,
pas une propriété magique DMG (pas de rareté/charges/harmonisation à poser
sans l'inventer) — question posée en commentaire d'Issue (voir jalon BLOQUÉ
si applicable) plutôt que tranchée silencieusement.

## 3. Tables à mode consultation (D-252.4) — 0/5, décision table par table

Les 5 tables d100 de la partition ont été examinées individuellement :
chacune répond à « quel score ai-je obtenu ? → quelle entrée suivre ? »
(branchement narratif pur à la lecture d'un jet aléatoire), **aucune** ne
répond à une question directe consultable (l'obstacle, la marchandise, la
distance). Les **5 tables restent en mode `aleatoire`** (inchangé) :

| table | plages | décision |
|---|---|---|
| d100-chanceroll | 3 | aleatoire — branchement pur |
| d100-exploreroom | ≥2 | aleatoire — branchement pur |
| d100-nastyturn | ≥2 | aleatoire — branchement pur |
| d100-riverdwellers | 3 | aleatoire — branchement pur |
| d100-roundthetwist | 5 | aleatoire — branchement pur |

Le mode `consultation` (D-252.4) reste posé et testé synthétiquement
(`tests/test-table-consultation-d252-4.py`, `tests/pconv4_test.py` §3) — DKS
n'en a simplement aucun cas d'usage réel.

## 4. Documents et illustrations montrables (D-252.1) — 3 ressources

Inventaire du matériau montrable au joueur repéré dans la source (lettres,
notes, affiches, inscriptions, illustrations de révélation) : **3** pièces,
émises en `Ressource` typée, rattachées à un node existant :

| id | type | sous_type | porteur/emplacement | état |
|---|---|---|---|---|
| doc-plaque-caveau | document | inscription | node porteur | non_remis |
| doc-pierre-tombale | document | inscription | node porteur | non_remis |
| illu-mosaique-portes | illustration | scene | node porteur | non_remis |

Les **19 cartes existantes restent type `carte`, inchangées** (mêmes ids,
mêmes fichiers `resources/*.jpg`, mêmes pages 99-117). Total ressources :
**22** (19 cartes + 3 documents/illustrations).

## 5. Sorts inédits (D-252.3) — zéro

Tous les sorts cités dans la source (Jump, Detect Evil and Good, Identify,
Thunderwave, Druidcraft, Prestidigitation, Thaumaturgy, Minor Illusion,
Silent Image, Sacred Flame, Command, Charm Person, Cure Wounds, Protection
from Evil and Good) appartiennent au SRD 5e — **zéro** sort hors SRD, donc
**zéro** record `sort` émis. La classe `sort` (D-252.3) reste posée et
testée synthétiquement (`tests/test-classe-sort-d252c.py`).

## 6. Détection des jets (D-254)

D-254 (PR #79) était déjà mergée sur `main` au lancement de cette lane —
`git merge origin/main` dans le worktree ne rapporte aucun delta (branche
déjà à jour). La passe P-CONV-4 exploite donc directement `REVERSE_CHECK_RE`
+ `SKILL_TO_ABILITY_5E` : **51 jets détectés** (42 `check`, 9
`saving_throw`) sur les 361 nœuds — mesure directement reproduite sur la
partition-pconv4 re-émise (le rapport `docs/pconv1-3-pval-ecarts.md` §6
mesurait déjà ce compte en re-passage sur pconv3, sans ré-émission).

## 7. Régime de re-émission (point 6, Issue #80)

- **D-253.1 (échéancier)** : rejoué sur l'`Aventure` de partition-pconv4 —
  `vivantes=0`, `echues=0`, `etats=4`, `avertissements=[]` — identique à la
  mesure pconv3 (`docs/pconv1-3-pval-ecarts.md` §5), cohérent avec un module
  à déclencheurs narratifs sans front daté.
- **D-253.2 (identité/résolution inter-modules)** : `cross_module_report`
  rejoué sur `[partition-pconv4]` seule — `orphelines: []`,
  `slugs_suspects: []` — aucune référence brisée par la re-émission.

Les deux gardes **passent** sur la partition re-émise : la garde
`garder_reportage` n'a, comme pour pconv3, rien à protéger au sens calendaire
sur ce module précis (0 condition vivante/échue) — la re-émission ne perd
aucune condition datée puisqu'il n'en existe aucune.

## 8. Suites vertes

`run_tests.py` : **ALL SUITES PASSED** avant et après cette lane
(`tests/pconv4_test.py` ajouté), zéro régression, trinity exclu (I-270).
