# CONVERSION DKS — P-CONV-0 socle des formes (2026-08-26)

*Rapport-forme de la lane `conversion-dks-pconv0`, fiche
[`FICHE-conversion-dks-pconv0-2026-08-26`](../../../Vaults/MVP2/Migration%20Coderain/FICHE-conversion-dks-pconv0-2026-08-26.md)
(mandat [`I-328`](../../../Vaults/MVP2/meta-rpg/registre-items/MRPG-I-328-nouveau-module-death-knights-squire.md),
routes [`D-216`](../../../Vaults/MVP2/meta-rpg/registre-decisions/D216-la-conversion-dks-teste-le-systeme-global-primitives-generiques.md)/[`D-217`](../../../Vaults/MVP2/meta-rpg/registre-decisions/D217-ressources-extraites-poste-technique-uniquement.md)).
FORMES ET CHIFFRES UNIQUEMENT, aucun contenu de partition ([`D-109`]).
Commit travail : **`36343d91e387b25a9bd28debe0a7394933e06d79`**.*

---

## 1. Route déterministe « gamebook à entrées nommées » (livrable 1)

Livré dans le périmètre P1 exact (`s1_local.py`, `cli.py`) :

| pièce | rôle |
|---|---|
| `GamebookFormat` | les formes sont PARAMÈTRES (`D-216`) : regex tête/continuation/pointeur/renvoi, jetons exclus, bornes de nom, seuils de recollage — pas un hack DKS |
| `scan_gamebook` | détection des têtes, graphe de renvois, tuilage exact `[0, len(source))`, résolution en cascade |
| `build_gamebook_partition` | nodes verbatim + liens typés + tables, mesures mécaniques |
| `extract_d100_tables` | tables de jets inline → primitives `RollTable` |
| `assemble_pages` | jointure reproductible des pages extraites (+ offsets de pages) |

Physique de mise en page exploitée (mesurée sur la source réelle) : une TÊTE
est un bloc de lignes CAPS séparé du corps par lignes vides ; les coupures PDF
fusionnent (`CULTISTCOMBA`+`T` → `CULTISTCOMBAT`, `SEARCH CAVE`,
`REPLENI SH`) ; un suffixe `?`/`!` tombe du slug mais reste au titre
(`ALLCLEAR?`) ; les noms de 3 lettres comptent (`RIP`, `RUN`) ; un bloc CAPS
collé sous un verbe de renvoi est du MATÉRIAU DE CIBLE, jamais une tête —
sauf promotion croisée quand un autre renvoi d'une AUTRE page le vise
(`SOUTHPATH`, `THUNDERWEB`, `WALKINGSTICK`, `NIMBLEFINGERS`, `QUIETSTEPS`,
`STONEDOORS`).

Zéro appel LLM, zéro token : la route entière est du code
(l'anti-hallucination par offsets de la maison est hérité telle quelle :
chaque node cite son span, `validate_fidelity` couvre chaque octet exactement
une fois — gaps 0, overlaps 0, unanchored 0).

## 2. Recollage des renvois (livrable 2)

Source scannée p10–98 : **486 occurrences** de renvois ; sur la fenêtre de
l'analyse v0 (p10–83) : **457 — parité exacte** avec `renvois_bruts` v0.

Cascade de résolution (déterministe, chaque niveau mesuré) :

| niveau | principe | résultat |
|---|---|---|
| 1. jointure progressive | les tokens capturés se concatènent du plus long au plus court (`BLES SING`→BLESSING, `DUKEITOU T`→DUKEITOUT, `TUNNE LVISION`→TUNNELVISION) | 459 |
| 2. préfixe unique | cible tronquée en fin de ligne, un seul nom défini commence par elle | (inclus) |
| 3. voisin toléré | coquille DE LA SOURCE : distance ≤ 2 unique, FLAGGUÉ dans les mesures | 2 |
| — | irrécupérable | **1** |

**485/486 résolus.** Les 2 tolérés : `ZEALOTSSNOMORE`→`ZEALOTSNOMORE` et
`VALIANTDEAFEAT`→`VALIANTDEFEAT` (le module lui-même orthographie deux fois).

**Irrécupérable motivé (1)** : `INTHEKNOW` (p52, « Are you a rogue? If so, go
to INTHEKNOW »). Aucune tête de ce nom n'existe nulle part dans la source.
L'analyse v0 ne le voyait PAS dans ses 23 dangling car sa ligne-cible collée
était comptée comme UNE TÊTE DEFINIE (faux positif auto-résolu) — la route
P-CONV-0 supprime ce masque.

Les **23 dangling de l'analyse v0 sont tous résolus mécaniquement** :
coupures de ligne par jointure (BLES, COAST, DUKEITOU, MOVE, NOROOMTR,
QUIETP, SEARCHC, STUDYDESI, TUNNE), têtes `?!` désormais détectées (ALLCLEAR,
AMBUSH, ENOUGHOFTHIS, ENTRANCETRAP, WELLWHATNOW, WHATAWAITS, WHATSTHIS,
WHATTRAPS), têtes courtes (RIP, RUN), têtes coupées fusionnées (REPLENISH,
RISE), multi-mots (SEARCHCAVE, ZOMBIEBATTLE).

## 3. Segmentation S2 des pointeurs p82–98 (livrable 3)

**17 nodes-pointeurs** (`tilepage-1`…`tilepage-12`, `submap-1`…`submap-5`),
structure S2, corps verbatim, OPTIONS liées vers les entrées (ex.
`tilepage-1` → `checksuccess`, `trapfail`, `quietentry`). La référence de
carte est PORTÉE PAR LE NODE : id machine (`tilepage-N`/`submap-N`) + titre
verbatim (`TILEPAGE 1`, `SUBMAP 5`) + phrase source « Find tilepage N in the
Maps Booklet » conservée in extenso.

⛔ **Remontée E1** : la primitive `Ressource` n'a PAS été posée au schéma.
Elle n'est nécessaire ni au tuilage ni à la validité de la partition — le
rattachement effectif des 19 JPEG est la passe P-conv-3 (l'analyse v0 l'a
placée là). Poser E1 exige un acte méta (le schéma est figé par décisions) :
**décision D2 attendue**, l'id/titre des 17 pointeurs sert d'ancre stable
entre-temps.

## 4. Partition émise (livrables 4)

`corpus-modules/death-knights-squire/partition-pconv0/` (hors git, `D-178`)
— verdict convertisseur **VERT**, `validate_form` vert, **zéro dangling
link**, couverture fidélité exacte :

| mesure | valeur |
|---|---|
| nodes | **361** = 343 entrées verbatim + 1 ouverture + 17 pointeurs |
| tables | **5** `RollTable` d100 contiguës (chanceroll, exploreroom, nastyturn, riverdwellers, roundthetwist) |
| records / secrets / patches | 0 (passes P-conv-1/2) |
| étage aventure | émis ; trajectoire/conditions vides (P-conv-2), charnière = citation VERBATIM de la sortie ouverte du module (`OHWELL`, p54) via `aventure-auteur.json` |
| form_errors / coverage_gaps / overlaps / rule_exceptions | 0 / 0 / 0 / 0 |
| mass_alarms | 4 nominales : les 4 unités portant une table extraite voient leurs mots comptés DEUX fois (corps verbatim + table) — ratio 1.30–1.75, non bloquant par conception, expliqué ici |
| checks indexés (`mapping-regles.json`) | 0 — voir remontée plus bas |

**Écarts nommés et motivés :**

1. **« table d100 p5 »** : p5 porte la RÈGLE des chance rolls (prose pure,
   zéro plage chiffrée). Les VRAIES tables d100 sont INLINE dans les entrées
   (4 appels recensés v0) → 5 runs contigus extraits en primitives
   `RollTable` ancrées. Le livrable « table d100 » est tenu LÀ où le module
   les porte réellement.
2. **341 → 343 entrées** : +18 têtes que v0 manquait (8 avec `?!`, 2 noms de
   3 lettres, 2 coupées mid-word fusionnées, 6 multi-mots dont THE END) et
   −16 faux positifs v0 (13 fragments de coupure comptés comme têtes :
   LUES, SING, SILVE, SKETC, URSE, KOBO, RTONGUE, BLOODKNIGHTSC,
   CREEPERSLAI, CULTISTCOMBA, ENTRANCETOM, INVESTIGATESP, MASTERTHIE ;
   la cible collée auto-résolue INTHEKNOW ; les 2 coquilles source
   VALIANTDEAFEAT, ZEALOTSSNOMORE absorbées par le recollage toléré).
   Chaque entrée reste VERBATIM ; rien n'est inventé, les fragments restent
   dans le corps de l'entrée qui les porte.
3. **checks = 0** : le phrasé réel du module (« Make a perception check,
   DC 12 ») est hors de la forme actuelle de `aval.CHECK_RE`
   (« DC N <ability> check »). Étendre `aval.py` est HORS P1 ⇒ remontée :
   à instruire en P-conv-1 (les DC restent verbatim dans les corps entre-temps).

## 5. Mesure d'architecture (livrable 5, donnée `D-216`)

Ce que la route mécanique a ABSORBÉ (zéro LLM) :

| absorbé mécaniquement | volume |
|---|---|
| segmentation complète en nodes | 361 nodes / 213 428 caractères placés verbatim, ancres exactes |
| graphe de navigation | 485 liens typés conditionnels (condition_textuelle = clause source) |
| tables de hasard | 5 RollTable contiguës (15 plages) |
| pointeurs cartographiés | 17 zones S2 avec référence de carte exploitable |
| validation | validate_form + fidélité verts, zéro hallucination possible par construction |

Ce qui RESTE aux passes suivantes (jugement, route LLM ou fichiers auteur) :

| passe | matière restante | ordre de grandeur estimé |
|---|---|---|
| P-conv-1 records | 10 statblocks distincts (3 customs complets + 1 variante à documenter + 6 ancrages SRD directs), collisions instruites record par record (`D-200`, PV persistants du knight) | ~10 records ≈ 10–20 appels (ou fichier auteur + validation mécanique) |
| P-conv-2 événements & secrets | trajectoire du knight (backstory p8–9), conditions monde, secrets candidats, débouchés structurés `D-118` à partir des options ♦ déjà verbatim dans les corps | ~20–40 appels |
| P-conv-3 cartes | export 19 JPEG (mécanique, zéro OCR), primitive E1 (acte méta D2), rattachement aux 17 pointeurs (ancres déjà posées) | quasi-mécanique après D2/D4 |
| P-val | doctor bout-en-bout | mécanique |

Comparaison à la route LLM générale estimée en v0 (~700 appels) : le socle
des formes consomme **0 appel** ; le résidu de jugement est concentré sur
~30–60 appels maximum, tous bornés par des unités de charge déjà mesurées
(62 DC · 32 skill · 9 combats · 11 objets · 9 gp).

## 6. Suites vertes avant/après (livrable 6)

| moment | résultat |
|---|---|
| AVANT tout changement (baseline, worktree propre sur `main`+analyse mergée) | `run_tests.py` : **ALL SUITES PASSED** (42 fichiers) |
| APRÈS (route ajoutée) | `run_tests.py` : **ALL SUITES PASSED** (43 fichiers, nouveau `tests/gamebook_test.py`) |

`tests/gamebook_test.py` épingle : tuilage exact, fusion de têtes coupées,
suffixes `?!`, promotion croisée inter-pages, refus des fragments
(`LUES`/`SING` restent hors têtes), tables d100 des deux styles (y compris
plage `81-00` → 81–100), bout-en-bout `cmd_convert` VERT, CLI
`--segmenter gamebook` exit 0, fixture de structure v0 convertie VERT.
Aucune suite existante modifiée.

## 7. Dépôt et écarts de protocole consignés

- Périmètre P1 tenu : `git diff main...HEAD` = `coderain/converter/cli.py`,
  `coderain/converter/s1_local.py`, `tests/gamebook_test.py` (+ le présent
  rapport au commit suivant). Aucun autre fichier du convertisseur touché
  (`schemas.py`, `emit.py`, `aval.py`, `validate_form.py` intacts).
- Matériau réel sous `corpus-modules/death-knights-squire/` (gitignore,
  `D-178`) : source assemblée `extraction/source-pconv0-p10-98.txt`
  (213 428 caractères, pages 10–98), partition émise
  `partition-pconv0/`, `aventure-auteur.json` (charnière verbatim OHWELL
  p54). Le PDF source n'a jamais été modifié.
- Remontées incluses ci-dessus : E1/`Ressource` (acte méta D2, non bloquant
  pour ce livrable), extension de `aval.CHECK_RE` au phrasé réel des DC
  (passe suivante), écarts nommés §4.
