# Couverture du système entier — mesure (Issue #314)

*Lane de MESURE PURE (même forme que `docs/couverture-moteur.md`, #235) :
aucun changement de comportement, aucun fichier touché hors ce document.
Objectif posé par la décision Souhel du 06/09 (matin) : avant de continuer à
tester le système ENTIER, savoir ce qui existe VRAIMENT dans le code, brique
par brique, avec quelle complétude et quels tests — la moitié « code » de la
carte croisée avec le vault de conception. « stub » est un fait de code, pas
un reproche ; ce document signale, il ne juge pas.*

Sources : `docs/ARCHITECTURE.md` (rôles, circuits, escalier campagne↔moteur),
l'arborescence `coderain/` (68 fichiers), `tools/` (5 fichiers), `mcp_server.py`
et `webui.py`, `docs/couverture-moteur.md` (repris tel quel pour le détail
`dnd5e-engine`, §3 ci-dessous), et une lecture exhaustive de `tests/`
(171 fichiers sous deux conventions de nommage, §5). Mesuré par 7 passes de
lecture indépendantes, une par organe, chacune croisant chaque fonction/
classe publique avec les tests qui l'exercent réellement (grep sur les
imports, pas sur la présence du nom).

---

## Synthèse (à lire en 15 minutes — le détail est dans les tableaux)

**73 fichiers `.py` dans `coderain/` + `tools/`** (21 952 lignes), **10 fichiers
racine** formant la couche interfaces (6 551 lignes) — 83 fichiers `.py`
mesurés au total, tous listés dans un tableau ci-dessous (écart vérifié par
`find` en fin de lane, §6).

**Ce qui est solide** : le cœur mécanique d'une partie jouée — jets et
combat (`mcp/jets_combat.py`, `modules/rpg.py`, `rules_engine/*`), la boucle
de tour (`engine.py`), l'assemblage de contexte keyé position (D-260,
`assembleur_position.py`), le Validator (moteur de légalité pur code,
`validator.py`), les gardes anti-fuite R1/R2, la chaîne Auteur complète
(`author.py`/`acte.py`/`campagne.py`/`toile.py`/`ecrivain_module.py`/
`retour2.py`/`proposeur.py`/`selecteur.py`), le convertisseur P4
(`converter/`, hormis 3 trous ci-dessous) et le banc de nuit (`tools/banc/`)
— sont **couverts** presque fonction par fonction, avec des tests dédiés qui
exercent aussi les branches de rejet.

**Les trois vrais trous de code trouvés** (pas des tests manquants — du code
mort ou débranché) :

1. `coderain/converter/semantic.py::absorb_tensions` — jamais appelée par le
   pipeline (`convert.py::absorb()` n'absorbe pas les tensions produites par
   la route LLM) ; la primitive `Tension` D-218 n'est peuplée que par des
   tests qui construisent une `Partition` à la main.
2. `coderain/converter/ruletables.py::statblock_core` — testée isolément
   mais jamais invoquée depuis `semantic.py`/`convert.py` : le filet
   anti-typo documenté pour les statblocks custom n'est câblé dans aucun
   chemin d'exécution réel.
3. `coderain/converter/install.py::doctor` (+ `cli.py main(["doctor", …])`) —
   zéro test, sur les deux formes.

**Ce qui a du code complet mais AUCUN test qui l'exerce par son nom** (pas des
stubs — tout est implémenté ; simplement jamais appelé depuis `tests/`) :

- **L'écran joueur** en quasi-totalité : `webui.py` (sauf `ConversationB`),
  les 5 outils `ui_*` de `mcp/narrateur.py`, `mcp/position_etat.py::ui_sheet`.
- **Le pipeline de fold mémoire côté pont MCP** : `fold_due`/`fold_apply`
  (`mcp/memoire_rappel.py`) — le shim `_NeedLLM`/`_ShimLLM` de `mcp_server.py`
  n'a aucun test direct, alors que `Summarizer` (le cœur du fold) est lui
  solidement testé.
- **La lecture de module côté outils MCP** : `module_index`,
  `module_list_nodes`, `module_get_node`, `module_get_record`,
  `module_roll_table`, `module_get_aventure` — la logique sous-jacente
  (`converter/aval.py`) est testée directement, mais aucun test n'appelle le
  wrapper MCP par son nom d'outil.
- **Le régime CLI/web secondaire en bloc** (D-267, jamais le chemin joué en
  production) : `server.py` (~90 routes FastAPI, 0 testée comme contrat
  HTTP), `play.py` (CLI REPL, 0 testé), `desktop.py`, `start.py`, `build.py`,
  `statusline_gauge.py`. `gui.py` fait exception mais seulement pour un tiers
  de ses méthodes (bootstrap, mémoire brute, panneau fiche, éditeur) — pas la
  boucle de jeu réelle ni les Settings.
- Quelques fonctions isolées : `coderain/config.py::read_env`/`write_env`,
  `coderain/profiles.py::apply_character`, `coderain/llm.py::extract_json`,
  `coderain/emit.py::read_manifest`.

**Aucun `TODO`/`FIXME`/`NotImplementedError` littéral trouvé nulle part dans
`coderain/`+`tools/`** (recherche exhaustive fichier par fichier par les 7
lectures, §4) — les seules tournures de périmètre trouvées sont des phrases
de docstring assumant EXPLICITEMENT une frontière (« hors périmètre »,
« jamais branché en séance », « v0 ») documentant une décision, pas un défaut
oublié. Un seul stub nommé comme tel : `coderain/input_processor.py`
écrit sciemment dans `STUB_INTERIORITE` (D-233b, le vrai support
biographique n'existe pas encore côté repo).

**Deux corps bien distincts à ne jamais confondre** (rappel ARCHITECTURE.md
§1) : `coderain/modules/trinity.py` (director-pipeline, Quad) est présent,
testé unitairement par une quinzaine de suites — mais **jamais le chemin par
défaut en production** (opt-in `generation.trinity_brain`, single-brain reste
le défaut). C'est un fait different d'un stub : le code tourne et est
vérifié, simplement non emprunté hors configuration explicite.

---

## 1. Par organe

L'escalier applicatif suit `docs/ARCHITECTURE.md` : un module source devient
une **Partition** (convertisseur, §1.2), servie tour après tour au **Director**
(rôle unique, deux corps — le pipeline `trinity.py` mesurable dans ce dépôt,
et le sous-agent director-de-table hors dépôt servi par le pont MCP), qui lit
l'**état et la mémoire** (`engine.py`/`memory.py`/`assembleur_position.py`),
résout les **jets et le combat** (`rules_engine/`+`modules/rpg.py`), comble
les petits trous de fiche (**bouchage**), consomme le vocabulaire de
**formes et tensions**, et écrit par patchs validés. Au-dessus de la boucle
de tour vit l'**Auteur** (campagne/toile/actes, écriture de module-épisode).
Le tout est mesuré côté banc (`tools/banc/`) et exposé par les
**interfaces** (pont MCP, webui, régime CLI/web secondaire).

### 1.1 Narrateur / Director

Pas un fichier isolé — un RÔLE distribué sur plusieurs organes déjà décrits
par `docs/ARCHITECTURE.md` §1/§6 :

- **director-pipeline** (`coderain/modules/trinity.py`, banc mesurable,
  jamais le chemin joué) — table complète en §1.7 (Banc et modules annexes).
- **director-de-table** (sous-agent hors dépôt) — sa seule matière dans ce
  dépôt est le pont MCP qui le sert : `mcp/narrateur.py::paquet_narrateur`,
  `mcp/position_etat.py::apply_envelope`/`assemble_context_to_file` — table
  en §1.9 (Interfaces).
- **narrateur single-brain** (pas de `trinity` configuré) — `Engine._produce`,
  `Engine.opening`, `Engine.continue_story`, `Engine.swipe_generate` dans
  `coderain/engine.py` — table en §1.4 (État et mémoire), tous `couvert`.

### 1.2 Convertisseur / adaptateur (`coderain/converter/`)

Chaîne P4 (SPEC-P4) : segmentation → bucketing → conversion sémantique →
tables de règles → deux validateurs (forme, fidélité) → émission → câblage
dans une save jouable (install/doctor/projection) → brief de direction. Deux
routes coexistent : pipeline LLM et route déterministe locale
(`s1_local.py`, modules à structure rigide/gamebooks).

#### Table

| fichier | fonction ou classe | rôle en une ligne | tests qui la couvrent | état |
|---|---|---|---|---|
| `coderain/converter/__init__.py` | (ré-export du paquet) | expose Partition/Manifest/… + sous-modules | exercé transitivement par tous les tests qui importent `coderain.converter` | couvert |
| `coderain/converter/__main__.py` | `raise SystemExit(main())` | point d'entrée `python -m coderain.converter` | aucun test n'invoque le module en `-m` (seul `cli.main()` est testé directement) | absent (zéro test direct, code trivial 1 ligne) |
| `coderain/converter/annexe_a.py` | `required_fields(classe)` | champs `stats_5e` obligatoires par classe de record | `test-classe-sort-d252c.py`, `pconv1_records_test.py`, `pconv_objets_magiques_test.py`, et tout test construisant un `Record` | couvert |
| `coderain/converter/aval.py` | `extract_checks` | extrait les jets DC (`CHECK_RE`+`REVERSE_CHECK_RE` ordre inverse D-254) | `test-check-re-ordre-inverse-d254.py`, `cli.cmd_convert` (bout-en-bout) | couvert |
| `coderain/converter/aval.py` | `write_checks` | sérialise `mapping-regles.json` | via `cli.cmd_convert` | couvert |
| `coderain/converter/aval.py` | `load_partition` | relit `index.json` | `install()`, `save_depart_test.py` | couvert |
| `coderain/converter/aval.py` | `_split_front` (privé) | sépare front-matter JSON / corps | via `get_node`/`get_record`/`derive`/`doctor` | couvert (indirect) |
| `coderain/converter/aval.py` | `get_node` | relit un node (meta+body) | `install.doctor`, `test-element-rendu-md-boucle-i187.py`, `projection.derive` | couvert |
| `coderain/converter/aval.py` | `get_record` | relit un record (meta+stats) | `install.doctor`, `projection.derive`, `save_depart_test.py` | couvert |
| `coderain/converter/aval.py` | `TableConsultationError` | échec explicite consultation de table | `test-table-consultation-d252-4.py` | couvert |
| `coderain/converter/aval.py` | `roll_table` | lecture table mode `aleatoire` | `test-table-consultation-d252-4.py` | couvert |
| `coderain/converter/aval.py` | `consulter_table` | lecture ciblée table mode `consultation` (D-252.4) | `test-table-consultation-d252-4.py` | couvert |
| `coderain/converter/aval.py` | `_table_meta`/`_read_table_entries` (privés) | lecture front-matter table / parsing des lignes | via `roll_table`/`consulter_table` | couvert (indirect) |
| `coderain/converter/buckets.py` | `SYSTEM`+`_validate` (privé) | grammaire du tri change-en-jeu/consulté-à-froid/mixte | via `classify` | couvert (indirect) |
| `coderain/converter/buckets.py` | `classify` | stage 2 LLM : classe chaque unité | `converter_test.py`, `test-pont-mcp-conversion-p4-i173.py` | couvert |
| `coderain/converter/cli.py` | `_extract_text` | extrait texte source (.pdf pymupdf / .txt) | branche `.txt` exercée partout ; branche `.pdf` **jamais exercée** | partiel |
| `coderain/converter/cli.py` | `_segment` | routage auto/s1/gamebook vers segmentation locale ou LLM | modes s1/gamebook/auto testés ; branche `llm is None` non exercée | partiel |
| `coderain/converter/cli.py` | `cmd_convert` | pipeline complet convert→validate→emit | `gamebook_test.py`, `fixtures/ci_boutenbout.py`, `test-pont-mcp-conversion-p4-i173.py`, toute la suite pconv*/d260 | couvert |
| `coderain/converter/cli.py` | `main` | CLI argparse : convert/all/install/doctor/project | seule la sous-commande `convert` est exercée via `main()` ; branches `install`/`doctor`/`project`/`all` du dispatch jamais invoquées via `main()` | partiel |
| `coderain/converter/cli.py` | `_slug` | wrapper vers `install._slugify` | via `main()` sous-commande convert | couvert (indirect) |
| `coderain/converter/convert.py` | `TokenMeter` | compte les caractères envoyés au LLM par stage | `converter_test.py`, `test-pont-mcp-conversion-p4-i173.py` | couvert |
| `coderain/converter/convert.py` | `convert_module` | pilote la route LLM complète | `converter_test.py` (nominal, erreurs de stage, fallback per-unit, sample_recheck) | couvert |
| `coderain/converter/directeur.py` | `GABARIT`/`SPEC_S1` | contenu fixe du brief de direction | généré par `generate()` | couvert (indirect) |
| `coderain/converter/directeur.py` | `generate` | écrit `directeur.md` | exécuté sans erreur par tout `cli.cmd_convert` ; **aucun test n'ouvre/assert le contenu généré** | partiel (exécuté, jamais son rendu vérifié) |
| `coderain/converter/emit.py` | `_md_table`/`_front_matter` (privés) | rendu markdown table / front-matter JSON | via `write_partition` | couvert (indirect) |
| `coderain/converter/emit.py` | `write_partition` | sérialise toute la Partition (11 gardes zéro-dangling/contrat) | quasi tous les fichiers pconv1-4/d-218/d-216/d-219/i033, chaque garde a son test dédié | couvert |
| `coderain/converter/emit.py` | `read_manifest` | relit `manifest.json` | aucun appel direct trouvé en test | absent |
| `coderain/converter/exceptions.py` | `build` | assemble le rapport d'exceptions (verdict VERT/ROUGE) | `converter_test.py`, `cli.cmd_convert` | couvert |
| `coderain/converter/exceptions.py` | `write_report` | écrit `rapport-conversion.json` | via `cli.cmd_convert` | couvert (indirect) |
| `coderain/converter/exceptions.py` | `render_md` | rend `rapport-conversion.md` | `converter_test.py` | couvert |
| `coderain/converter/install.py` | `_slugify` (privé) | slug kebab avec repli accents FR | via `install()`/`cli._slug` | couvert (indirect) |
| `coderain/converter/install.py` | `install` | crée/relie scenario+save à la partition, idempotent | `save_depart_test.py` (nominal, ré-appel idempotent, wiring périmé, --force) | couvert |
| `coderain/converter/install.py` | `doctor` | re-vérifie structure+câblage, verdict PRÊT/PAS PRÊT | **aucun test ne l'appelle** | absent |
| `coderain/converter/projection.py` | `_load_node_ids`/`_strip_sequences` (privés) | lecture nodes / retrait séquences "go to N" | via `derive()` | couvert (indirect) |
| `coderain/converter/projection.py` | `derive` | dérive la vue moteur (locations/characters/conditions/trajectoire/secrets/brief) dans la save | jamais appelée directement par un test, mais toujours via `install()` — effets vérifiés (`save_depart_test.py`) | couvert (via install(), jamais en appel direct) |
| `coderain/converter/rendu_auteur.py` | `node_id_par_scene` | mapping titre de scène → node_id, titres ambigus exclus | `test-node-id-par-scene-titre-ambigu-i191.py` | couvert |
| `coderain/converter/rendu_auteur.py` | `chemin_scenario_auteur` | premier chemin candidat existant | via `ecrire_rendu_auteur` | couvert (indirect) |
| `coderain/converter/rendu_auteur.py` | `_fusionner` (privé) | fusion non destructive dans `scenario-auteur.json` | via `ecrire_rendu_auteur` | couvert (indirect) |
| `coderain/converter/rendu_auteur.py` | `ecrire_rendu_auteur` | câble `declaration_rendu` → `scenario-auteur.json` (I-187) | `test-rendu-auteur-doublon-scene-i191.py`, `test-element-rendu-md-boucle-i187.py` | couvert |
| `coderain/converter/ruletables.py` | `statblock_core` | filet anti-typo dialecte source → noyau chiffré | `pconv1_records_test.py` (direct) — **jamais appelée depuis le pipeline** `semantic.py`/`convert.py` | partiel (testé mais jamais branché dans le pipeline) |
| `coderain/converter/ruletables.py` | `ConversionException` | exception "pas de table pour cette valeur" | `converter_test.py`, `pconv1_records_test.py` | couvert |
| `coderain/converter/ruletables.py` | `RuleTables` | tables de conversion versionnées source→5e | `converter_test.py` (identity + non-identity, cible 2014/2024) | couvert |
| `coderain/converter/s1_local.py` | `characterise_rendu` | caractérise ton/rythme depuis un lexique fermé (D-102/I-111) | `test-element-rendu-md-converter.py`, `rendu-md-anti-rail-test.py` | couvert |
| `coderain/converter/s1_local.py` | `segment_s1` | tuile le texte aux marqueurs `#N` | `pconv1_records_test.py` et pconv*_test.py (route s1) | couvert |
| `coderain/converter/s1_local.py` | `node_for_unit` | construit un Node verbatim + liens typés | idem (route s1) | couvert |
| `coderain/converter/s1_local.py` | `GamebookFormat`/`GAMEBOOK` | paramètres structurels d'une famille de gamebook | `gamebook_test.py` | couvert |
| `coderain/converter/s1_local.py` | `assemble_pages` | assemble des pages `page-NNN.txt` + offsets | `gamebook_test.py` (§5) | couvert |
| `coderain/converter/s1_local.py` | `_norm_map`/`_lev`/`_slug` (privés) | normalisation espaces / distance de Levenshtein / slug | via `scan_gamebook` | couvert (indirect) |
| `coderain/converter/s1_local.py` | `scan_gamebook` | détecte entrées CAPS, pointeurs, graphe de renvois | `gamebook_test.py` | couvert |
| `coderain/converter/s1_local.py` | `build_gamebook_partition` | construit nodes+liens+tables d100 depuis un scan | `gamebook_test.py`, `cli.cmd_convert(mode="gamebook")` | couvert |
| `coderain/converter/s1_local.py` | `extract_d100_tables` | tables d100 → `RollTable` | `gamebook_test.py` | couvert |
| `coderain/converter/schemas.py` | `check_prerequis`/`make_debouche`/`make_heritage`/`check_id` | validateurs de formes partagées | `test-etage-scenario-d260.py`, famille `test-*-position-d260.py`, `converter_test.py` | couvert |
| `coderain/converter/schemas.py` | `Unit` | unité segmentée ancrée (offsets) | `converter_test.py`, `s1_local.py` tous les tests | couvert |
| `coderain/converter/schemas.py` | `Manifest` | champs obligatoires + validation structures/corpus_cible | `converter_test.py` | couvert |
| `coderain/converter/schemas.py` | `Node` | prose + liens + rubriques scénario + garde anti-rail rendu_md | `test-element-rendu-md-converter.py`, `rendu-md-anti-rail-test.py`, `test-etage-scenario-d260.py`, quasi tous les pconv*_test.py | couvert |
| `coderain/converter/schemas.py` | `Record` | statblock typé 5e + formes P-CONV-1/objets magiques/sorts | `pconv1_records_test.py`, `pconv_objets_magiques_test.py`, `test-classe-sort-d252c.py` | couvert |
| `coderain/converter/schemas.py` | `RollTable` | table aléatoire (plages contiguës) ou consultation (D-252.4) | `test-table-consultation-d252-4.py`, `pconv4_test.py` | couvert |
| `coderain/converter/schemas.py` | `Secret` | secret épistémique (statut/porteurs/révélation) | `pconv2_tension_test.py` et al. | couvert |
| `coderain/converter/schemas.py` | `Tension` | inventaire de tension traversant D-218 | `pconv2_tension_test.py`, `test-auteur-codes-tension.py` | couvert |
| `coderain/converter/schemas.py` | `Ressource`+`set_etat_ressource` | primitive générique carte/document/illustration (D-216/D-252.1) | `pconv3_ressource_test.py`, `document-illustration-d2521-test.py` | couvert |
| `coderain/converter/schemas.py` | `Personnage` | personnage + destinée (I-341/D-219/D-220) | `test-personnage-destinee.py` | couvert |
| `coderain/converter/schemas.py` | `Fenetre` | fenêtre de conversation d'accord, borne à deux murs (I-033) | `test-borne-deux-murs-i033.py` | couvert |
| `coderain/converter/schemas.py` | `Patch` | mutation incrémentale adressée | `converter_test.py` | couvert |
| `coderain/converter/schemas.py` | `Evenement` | 7ᵉ primitive, schéma figé D-182 | `test-etage-aventure.py` | couvert |
| `coderain/converter/schemas.py` | `Aventure` | étage aventure (trajectoire/conditions/charnière), pertes signalées | `test-etage-aventure.py` | couvert |
| `coderain/converter/schemas.py` | `Partition` | objet racine, agrège les primitives | tous les tests de la lane | couvert |
| `coderain/converter/segmentation.py` | `segment` | stage 1 LLM : détecte S1/S2/S3, offsets exacts | via `segment_chunked` et `convert_module` | couvert |
| `coderain/converter/segmentation.py` | `segment_chunked` | découpe en tranches ~12k car., agrège unités + erreurs | `converter_test.py` (import direct) | couvert |
| `coderain/converter/semantic.py` | `convert_unit` | stage 3 LLM, une unité → primitives, ancrages obligatoires | `converter_test.py` (fallback per-unit), `validate_fidelity.sample_recheck` | couvert |
| `coderain/converter/semantic.py` | `convert_batch` | conversion par lot (8), tolère un id manquant/inventé | `converter_test.py`, `test-pont-mcp-conversion-p4-i173.py` | couvert |
| `coderain/converter/semantic.py` | `absorb_aventure` | assemble trajectoire/conditions dans `partition.aventure` | `converter_test.py` (via `convert_module`) | couvert |
| `coderain/converter/semantic.py` | `absorb_tensions` | ajoute les tensions D-218 à la partition | **jamais appelée** — `convert.py::absorb()` n'en fait pas usage ; aucun test ne l'appelle non plus | stub (fonction morte, jamais branchée ni testée) |
| `coderain/converter/semantic.py` | `RuleTablesLike` | classe de typage vide (`# pragma: no cover`) | — | n/a (marqueur de type, explicitement hors couverture) |
| `coderain/converter/validate_fidelity.py` | `coverage_report` | union des ancrages = [0,len) exact | `converter_test.py`, `cli.cmd_convert` | couvert |
| `coderain/converter/validate_fidelity.py` | `mass_report` | ratio mots source/sortie par unité, alarme hors tolérance | `converter_test.py` | couvert |
| `coderain/converter/validate_fidelity.py` | `sample_recheck` | ré-traduit un échantillon, diff avec la conversion primaire | `converter_test.py` | couvert |
| `coderain/converter/validate_form.py` | `validate_form` | 13 familles de gardes structurelles | quasi tous les fichiers pconv*/test-*-d219/d218/d216/i033 | couvert |
| `coderain/converter/validate_form.py` | `adventure_exceptions` | lignes d'exception étage aventure | `test-etage-aventure.py`, `cli.cmd_convert` | couvert |
| `coderain/converter/validate_form.py` | `scenario_report` | mesures + erreurs étage scénario | `test-etage-scenario-d260.py` et famille | couvert |
| `coderain/converter/validate_inter_module.py` | `cross_module_report` (+ 5 privés) | garde de résolution inter-modules (orphelines + slugs suspects, D-253.2) | `test-identite-inter-modules-d253.py`, `test-dks-regime-trans-modules.py` | couvert |

#### TODO/FIXME/stubs trouvés

- `coderain/converter/annexe_a.py:3` — « DRAFT v0 » : squelette de champs
  assumé provisoire, jamais remplacé par le jeu de champs SRD complet
  annoncé.
- `coderain/converter/semantic.py:186-190` — `absorb_tensions` définie mais
  **jamais appelée** : la primitive `Tension` D-218 n'est peuplée que par du
  code de test qui construit la Partition à la main, jamais par le pipeline
  LLM réel.
- `coderain/converter/ruletables.py:39` (`statblock_core`) — testée
  isolément mais jamais invoquée depuis `semantic.py`/`convert.py` : le
  filet anti-typo documenté comme mécanisme de conversion des statblocks
  custom n'est câblé dans aucun chemin d'exécution.
- `coderain/converter/install.py::doctor` + `cli.py main(["doctor", …])` —
  zéro test (recherche exhaustive du mot « doctor » dans `tests/` : zéro
  occurrence).
- `coderain/converter/cli.py::_extract_text` — branche `.pdf` (pymupdf)
  jamais exercée (toutes les fixtures sont `.txt`).
- `coderain/converter/emit.py::read_manifest` — aucun appel direct trouvé en
  test.

#### Chiffres

| fichier | lignes | fonctions/classes publiques | testées |
|---|---:|---:|---:|
| `__init__.py` | 20 | 0 (agrégation) | — |
| `__main__.py` | 4 | 0 (script) | 0 |
| `annexe_a.py` | 42 | 1 | 1 |
| `aval.py` | 298 | 8 | 8 |
| `buckets.py` | 53 | 1 | 1 |
| `cli.py` | 322 | 3 (+2 privées) | 3 (partiellement) |
| `convert.py` | 159 | 2 | 2 |
| `directeur.py` | 103 | 1 | 1 (exécutée, pas assertée) |
| `emit.py` | 308 | 2 (+2 privées) | 1 |
| `exceptions.py` | 84 | 3 | 3 |
| `install.py` | 142 | 2 (+1 privée) | 1 |
| `projection.py` | 200 | 1 (+2 privées) | 1 (via install) |
| `rendu_auteur.py` | 127 | 3 (+1 privée) | 3 |
| `ruletables.py` | 142 | 3 | 3 (`statblock_core` non branchée pipeline) |
| `s1_local.py` | 566 | 8 (+3 privées, +1 dataclass) | 8 |
| `schemas.py` | 1071 | 19 classes/fonctions | 19 |
| `segmentation.py` | 102 | 2 (+2 privées) | 2 |
| `semantic.py` | 246 | 5 (+2 privées) | 4 (`absorb_tensions` jamais appelée) |
| `validate_fidelity.py` | 134 | 3 (+2 privées) | 3 |
| `validate_form.py` | 408 | 3 | 3 |
| `validate_inter_module.py` | 188 | 1 (+5 privées) | 1 |
| **total** | **4719** | **~72** | **~66 couvertes**, 1 stub mort (`absorb_tensions`), 1 orpheline (`statblock_core`), `doctor()`/`__main__`/`_extract_text` PDF/`read_manifest` sans test |

### 1.3 Moteur de règles + combat

Deux systèmes de jets coexistent (voir `docs/couverture-moteur.md` pour le
détail complet `dnd5e-engine`, repris ici tel quel) : (1) l'ancien
`coderain.modules.rpg` — jets "legacy" hors combat
(`roll_check`/`roll_damage`/`death_save`/`attack`), résolution dérivée de la
fiche Markdown, jamais de moteur externe ; et (2) le pont
`coderain/rules_engine/` vers `dnd5e-engine` (D-200/D-078), qui détient tout
l'état mécanique d'un combat ouvert. `coderain/mcp/jets_combat.py` est le
point d'entrée MCP unique pour les deux systèmes.

#### Table

| fichier | fonction ou classe | rôle en une ligne | tests qui la couvrent | état |
|---|---|---|---|---|
| `coderain/rules_engine/__init__.py` | `RulesEngineNotInstalled` | exception si `dnd5e-engine` absent | `test_rules_engine.py` §1 | couvert |
| `coderain/rules_engine/__init__.py` | `engine()` | charge `dnd5e_engine` une seule fois (lazy) | `test_rules_engine.py` §1 | couvert |
| `coderain/rules_engine/__init__.py` | `__getattr__` (PEP 562) | ré-export paresseux des attributs du moteur | exercé indirectement à chaque usage `dnd5e_engine.*` | couvert (indirect) |
| `coderain/rules_engine/engine_bridge.py` | `intent_rejected_error` | expose `IntentRejectedError` du moteur | `test_rules_engine.py` (intent illégal/hors-tour) | couvert |
| `coderain/rules_engine/engine_bridge.py` | `resolve_check` | résout un jet 5e isolé via le moteur | `test_rules_engine.py` §2 (déterminisme seed), `kind` inconnu | couvert |
| `coderain/rules_engine/engine_bridge.py` | `get_bridge` | singleton du pont `CombatBridge` | `test_rules_engine.py`, `test_monster_bridge.py`, `test-paquet-narrateur-combat-i200.py` | couvert |
| `coderain/rules_engine/engine_bridge.py` | `CombatBridge.start_combat` | ouvre un combat moteur, avertit slugs non résolus (I-205) | idem + slug absent/mauvais | couvert |
| `coderain/rules_engine/engine_bridge.py` | `CombatBridge.submit_intent` | soumet l'intention d'un PJ (attack/move/pass) | nominal + hors-tour → `IntentRejectedError` | couvert pour `attack`/`move`/`pass` ; `cast_spell`/`equip_item` non exercés |
| `coderain/rules_engine/engine_bridge.py` | `CombatBridge.monster_turn` | fait jouer le tour d'un monstre par l'IA moteur | slug absent → `pass`+warning à CHAQUE tour | couvert |
| `coderain/rules_engine/engine_bridge.py` | `CombatBridge.end_combat` | clôt le combat, renvoie `CombatOutcome` | `test_rules_engine.py`, `test_monster_bridge.py` | couvert |
| `coderain/rules_engine/engine_bridge.py` | `CombatBridge.live` | miroir lecture seule de l'état combat courant | exercé à chaque appel start/submit/monster_turn | couvert (indirect) |
| `coderain/rules_engine/engine_bridge.py` | `CombatBridge.drain_events` | draine les événements pendants (file exact-once) | `test_rules_engine.py` (`narration_events`) | couvert |
| `coderain/rules_engine/monster_bridge.py` | `brute_template_slug` | slug déterministe du template "brute" | `test_monster_bridge.py` | couvert |
| `coderain/rules_engine/monster_bridge.py` | `install_brute_template` | enregistre le monstre "brute" dans le loader composite | jamais isolément, seulement via `encounter_member_from_record` | partiel |
| `coderain/rules_engine/monster_bridge.py` | `encounter_member_from_record` | record de module (champs FR) → `EncounterMemberSpec` | nominal + `ConversionException` sur champ manquant | couvert |
| `coderain/mcp/jets_combat.py` | `roll_check` | jet legacy d20+stat (compétence inconnue refusée, bouchage D-275) | `test-element-mort-i213.py`, `test-element-bouchage-d275.py`, `test-element-jet-degats-i206.py` | couvert |
| `coderain/mcp/jets_combat.py` | `death_save` | résout UNE sauvegarde contre la mort (legacy) | `test-element-mort-i213.py` (3 échecs, 3 succès, nat 20, nat 1) | couvert |
| `coderain/mcp/jets_combat.py` | `roll_damage` | jet de dégâts legacy à partir d'une formule/fiche | `test-element-jet-degats-i206.py` (déterminisme seed+nonce) | couvert |
| `coderain/mcp/jets_combat.py` | `attack` | attaque de bout en bout legacy : toucher + dégâts + application | `test-element-attaque-i463.py`, `test-element-bouchage-d275.py` | couvert |
| `coderain/mcp/jets_combat.py` | `resolve_check` | jet 5e isolé par `dnd5e-engine` (délègue) | `test_rules_engine.py` | couvert |
| `coderain/mcp/jets_combat.py` | `start_combat`/`submit_intent`/`monster_turn`/`end_combat` | cycle de combat complet | `test_rules_engine.py` (client MCP réel), `test-paquet-narrateur-combat-i200.py` | couvert |
| `coderain/mcp/jets_combat.py` | `narration_events` | draine les événements de combat pendants | `test_rules_engine.py` | couvert |
| `coderain/modules/rpg.py` | `win_chance` | probabilité de succès d'un jet d20+mod vs DC | `phase4_test.py` (médian + 2 clamps) | couvert |
| `coderain/modules/rpg.py` | `skill_mod` | bonus de compétence entraînée | `character_schema_test.py`, `wave3_test.py` | couvert |
| `coderain/modules/rpg.py` | `roll_check` | jet d20+mod déterministe (seed+nonce) | `test-element-jet-degats-i206.py` + outil MCP | couvert |
| `coderain/modules/rpg.py` | `roll_damage` | jet de dégâts déterministe, refuse formule illisible/hors bornes | `test-element-jet-degats-i206.py` | couvert |
| `coderain/modules/rpg.py` | `proficiency_bonus` | bonus de maîtrise 5e | jamais appelé directement ; exercé en interne par `derived_combat` | partiel |
| `coderain/modules/rpg.py` | `opt_int` | lit un entier de fiche ou None/False | jamais appelé directement ; exercé en interne, cas "illisible" non testé | partiel |
| `coderain/modules/rpg.py` | `derived_combat` | dérive CA/bonus d'attaque/arme depuis la fiche (D-274 §1) | `test-element-attaque-i463.py` (sans armure, avec dex_max, sans arme, stat manquante), `test-element-bouchage-d275.py` | couvert |
| `coderain/modules/rpg.py` | `player_combat` | `derived_combat` sur save réelle + bouchage D-275 | `test-element-bouchage-d275.py` | couvert |
| `coderain/modules/rpg.py` | `death_save` | résout UNE sauvegarde contre la mort du joueur | `test-element-mort-i213.py` | couvert |
| `coderain/modules/rpg.py` | `apply` | applique un sidecar validé (check/HP/mana/XP/level-up/grants/…) | `phase4_test.py`, `phase4_sweep_test.py`, `wave3_test.py`, `sweep2/4_test.py`, `test_etat_persistant.py` | couvert |
| `coderain/modules/rpg.py` | `render_sheet_lines` | rendu vertical de la fiche (GUI) + bloc Combat dérivé | `test-fixture-personnage-banc-i257.py`, `wave3_test.py` | couvert |
| `coderain/modules/rpg.py` | `render_sheet` | rendu compact de la fiche (CLI) | jamais appelé directement ; exercé en interne par `context_block` | partiel |
| `coderain/modules/rpg.py` | `context_block` | fiche + dernier jet injectés dans le contexte narrateur | `test-rpg-rules-socle-declencheur-d260.py`, `mesure-d260-boucle-neuve.py` | couvert |

#### TODO/FIXME/stubs trouvés

Aucun `TODO`/`FIXME`/`NotImplementedError` littéral. Limites documentées,
volontairement réduites (pas des stubs) :

- `coderain/rules_engine/monster_bridge.py:19-23` — "Portée volontairement
  minimale (« suffit pour la fumée »)" — une attaque, pas de multiattaque,
  pas de résistances/immunités pour le template "brute" (I-205).
- `coderain/rules_engine/engine_bridge.py:9-10` — "Coexistence v0 : les jets
  simples hors combat restent dans `coderain.modules.rpg`, NON touché" —
  frontière assumée.
- `coderain/rules_engine/monster_bridge.py:171-178` — `_CompositeLoader`
  s'appuie sur `set_lib_loader_for_tests`, injection côté moteur pensée pour
  les tests, réutilisée en prod — dépendance fragile documentée.
- `combat.cast_spell` existe côté moteur (`dnd5e_engine/dispatch.py`) mais
  n'est mentionné ni testé côté pont coderain — trou FONCTIONNEL, pas un
  TODO littéral (déjà noté par `docs/couverture-moteur.md`).

#### Chiffres

| fichier | lignes | fonctions/classes publiques | testées |
|---|---:|---:|---:|
| `rules_engine/__init__.py` | 71 | 3 | 3 |
| `rules_engine/engine_bridge.py` | 260 | 10 | 10 |
| `rules_engine/monster_bridge.py` | 251 | 3 | 3 (1 indirectement) |
| `mcp/jets_combat.py` | 313 | 10 (outils) | 10 |
| `modules/rpg.py` | 888 | 13 | 10 couvertes, 3 partielles (`proficiency_bonus`, `opt_int`, `render_sheet`) |

### 1.4 État et mémoire

Boucle de tour (`engine.py` : assemble → génère → persiste → folde), stockage
Markdown-comme-source-de-vérité + index de mémoire (`memory.py`), assemblage
de contexte KEYÉ POSITION pour les saves avec partition projetée
(`assembleur_position.py` + `mcp/position_etat.py`), verrou de save
inter-process (`save_lock.py`), canal sidecar (`sidecar.py`), données de
calibrage modèle/contexte (`models.py`). `context.py` est un placeholder de
3 lignes (logique réelle dans `mcp_server.py`, I-281).

#### Table

| fichier | fonction ou classe | rôle en une ligne | tests qui la couvrent | état |
|---|---|---|---|---|
| `coderain/engine.py` | `_any_applied` | filtre les events validator pour ne pas compter un rejet comme delta appliqué | wave2/3/4_test, validator_test (indirect) | couvert |
| `coderain/engine.py` | `Engine.__init__` | construit LLM/Summarizer/features/trinity/retriever depuis la config | tous les tests moteur | couvert |
| `coderain/engine.py` | `Engine._partition_dir` | résout `module.json`→partition depuis la save | test-branchement-position-d260, test-assembleur-position-d260 | couvert |
| `coderain/engine.py` | `Engine._rpg_rules_served` | découpe rpg-rules.md en socle + section Level-ups | test-rpg-rules-socle-declencheur-d260 | couvert |
| `coderain/engine.py` | `Engine._messages` | bascule assemble() legacy / assembleur_position selon `eligible()` | test-branchement-position-d260, wave2-4_test | couvert |
| `coderain/engine.py` | `Engine._augment_event_rules` | insère le bloc verdicts CANDIDAT en queue volatile | test-regles-evenement-verdicts-d260 | couvert |
| `coderain/engine.py` | `Engine.route_input` | route l'entrée joueur (I-373) vers PACK/commande méta | test-processeur-entree-i373 | couvert |
| `coderain/engine.py` | `Engine._augment_pack` | ajoute le PACK D'ENTRÉE NON ROUTÉ au prompt | test-processeur-entree-i373 | couvert |
| `coderain/engine.py` | `Engine._authors_note_cfg` | lit depth/every de l'author's note (ST-21) | wave4_test | couvert |
| `coderain/engine.py` | `Engine._response_length_directive` | texte de la directive response_length | wave4_test, test-prefixe-rpg-longueur-unique-d260 | couvert |
| `coderain/engine.py` | `Engine._augment_style` | injecte directive longueur + author's note | wave4_test | couvert |
| `coderain/engine.py` | `Engine._augment_rpg` | ajoute règles RPG + fiche perso au prompt (chemin non-partition) | wave2/3_test | couvert |
| `coderain/engine.py` | `Engine._snapshot_rpg` | deep-copy pré-tour de l'état pour retry/undo | undo_test, wave2-4_test | couvert |
| `coderain/engine.py` | `Engine.restore_pre_turn_rpg` | annule les mutations d'un tour | phase6_pre_sweep_test, undo_test | couvert |
| `coderain/engine.py` | `Engine.opening` | génère/rend la scène d'ouverture (verbatim ou générée) | sweep4/5_test, tier3_test, wave4_test | couvert |
| `coderain/engine.py` | `Engine.turn` | le tour joueur complet | quasiment tous les tests moteur | couvert |
| `coderain/engine.py` | `Engine.continue_story` | bouton "Continue" sans nouvelle entrée joueur | sweep3_test | couvert |
| `coderain/engine.py` | `Engine._ensure_swipes` | initialise l'état de swipe | sweep3_test | couvert |
| `coderain/engine.py` | `Engine.swipe_browse` | navigue entre variantes déjà générées (ST-02) | sweep3_test | couvert |
| `coderain/engine.py` | `Engine.swipe_generate` | génère une nouvelle variante alternative | test-processeur-entree-i373 | couvert |
| `coderain/engine.py` | `Engine.impersonate` | suggère la prochaine action du joueur (ST-04) | sweep3_test | couvert |
| `coderain/engine.py` | `Engine.undo_last` | annule le dernier échange sans regénérer | sweep2_test, undo_test, wave2-4_test | couvert |
| `coderain/engine.py` | `Engine.maybe_fold` | lance les folds dus + agrège les events RPG | phase2-4_test, timeline_test, trinity_test, undo_test | couvert |
| `coderain/engine.py` | `Engine._expand_authored` | expanse les macros ST-20 sur un texte verbatim | wave4_test (implicite) | partiel |
| `coderain/engine.py` | `Engine._apply_output_regex` | applique les règles find/replace ST-31 avec garde ReDoS | wave4_test | couvert |
| `coderain/engine.py` | `Engine._reply_prefix` | lit le préfixe "Start reply with" (ST-22) | wave4_test | couvert |
| `coderain/engine.py` | `Engine._generate_and_store` | injecte le préfixe ST-22 lazy sur le flux streamé | wave4_test | couvert |
| `coderain/engine.py` | `Engine._produce` | corps de génération (single-brain/tool/trinity) + application mécaniques | wave2-4_test, trinity_test, sweep4-6_test | couvert |
| `coderain/engine.py` | `Engine.apply_envelope` | seam Backend Validator : valide+applique reveals/canon/events/RPG + log | validator_test, wave2-4_test, test-element-mort/attaque/jet-degats, single-writer-guichet-i94 | couvert |
| `coderain/engine.py` | `Engine._apply_reveals` | flip reveal + log canon-event (undo-tracked) | wave2_test | couvert |
| `coderain/engine.py` | `Engine._apply_event_rules` | marque un once-rule consommé (undo-tracked) | test-regles-evenement-verdicts-d260, wave4_test | couvert |
| `coderain/engine.py` | `Engine._apply_quest_canon` | log canon-event quand un quest complete/failed | wave3_test | couvert |
| `coderain/engine.py` | `Engine.companions` | slugs des personnages compagnons | wave3_test | couvert |
| `coderain/engine.py` | `Engine.conversation_b_start`/`_submit`/`_personnage` | démarre/soumet/finalise le protocole F1 (délègue à webui) | aucun test direct au niveau Engine (webui.conv_b_* testé côté converter) | absent |
| `coderain/engine.py` | `Engine.companion_chat` | side-chat privé avec un compagnon (hors transcript) | wave3_test | couvert |
| `coderain/engine.py` | `Engine._generate_with_tool` | appelle le LLM avec le tool lookup_memory | phase5_sweep/vector_test (mode use_memory_tool) | partiel |
| `coderain/engine.py` | `Engine._dispatch_tool` | résout un appel d'outil mémoire | camera_selection_test, phase5_sweep_test | partiel |
| `coderain/memory.py` | `safe_output_regex` | garde ReDoS pour les règles ST-31 | wave4_test | couvert |
| `coderain/memory.py` | `Entry` (dataclass + ~20 méthodes) | modèle d'une entrée de registre + tout le vocabulaire lorebook | tier2_test, wave2/3_test, stats_md_test, camera_selection_test, character_schema_test | couvert |
| `coderain/memory.py` | `parse_entries` | parse les sections `## Nom {#slug}` avec attrs + body | phase2_test, wave2_test, character_schema_test | couvert |
| `coderain/memory.py` | `MemoryStore.path/read/write/make_override/remove_override/reset_rule/layer_of/resolve_read_path/resolve_write_path` | accès fichier générique + résolution de couche | rules_migration_test, phase3-5_test | couvert |
| `coderain/memory.py` | `MemoryStore.title` | titre de la save depuis meta.json | phase2_test (implicite) | partiel |
| `coderain/memory.py` | `MemoryStore.custom_files/gated_registries/index_files/add_custom_file` | registres de lore typés custom (Wave 2) | wave2_test | couvert |
| `coderain/memory.py` | `MemoryStore.facts/add_facts` | faits intemporels (Wave 2) | wave2_test | couvert |
| `coderain/memory.py` | `MemoryStore.mode/beats` | mode simple/rpg de la save + beats de rythme | wave3_test | couvert |
| `coderain/memory.py` | `MemoryStore.append_companion_chat/companion_chat_tail` | log + lecture du side-chat compagnon | wave3_test | couvert |
| `coderain/memory.py` | `MemoryStore.event_rules/event_rules_block/event_rule_verdicts_block/mark_event_consumed` | règles d'événement authored + bloc CANDIDAT du tour | wave4_test, test-regles-evenement-verdicts-d260, test-assembleur-position-d260 | couvert |
| `coderain/memory.py` | `MemoryStore.opening_override` | scène d'ouverture verbatim (## Opening) | wave4_test, sweep4/5_test | couvert |
| `coderain/memory.py` | `MemoryStore.custom_instructions` | instructions de style custom par save (ST-21) | wave4_test | couvert |
| `coderain/memory.py` | `MemoryStore.set_hidden` | flip hidden sur toute la portée des registres | wave2_test, test-garde-secrets-i159 | couvert |
| `coderain/memory.py` | `MemoryStore.state/write_state` | métadonnées de fold (.fold_state.json) | phase2-4_test, timeline_test | couvert |
| `coderain/memory.py` | `MemoryStore.snapshot` | copie horodatée pré-fold (undo/branch) | snapshot_ouverture_i148_test, phase3-4_test | couvert |
| `coderain/memory.py` | `MemoryStore.append_turn/drop_last_turns/update_turn/turns/recent_turns/turns_range/has_turns` | transcript.md : lecture/écriture/édition des tours | quasi tous les tests moteur, undo_test | couvert |
| `coderain/memory.py` | `MemoryStore.recall_turns/_scenes_touching/recall_entity/recall_quest` | index causal/entité pour drill-down verbatim | test-element-camera, camera_selection_test (indirect) | partiel |
| `coderain/memory.py` | `MemoryStore.entries/upsert_entry/remove_entry/merge_entry` | CRUD registre textuel | wave2/3_test, phase2-4_test | couvert |
| `coderain/memory.py` | `MemoryStore.world_state/set_world_state/clock_str` | état monde + point d'écriture unique guardé | phase3_test, validator_test, single-writer-guichet-i94_test | couvert |
| `coderain/memory.py` | `MemoryStore.append_event_log/truncate_event_log` | JSONL des enveloppes validées (rejouable pour branch) | sweep2-5_test, phase5_saves_test | couvert |
| `coderain/memory.py` | `MemoryStore.append_fold_log` | JSONL forensique des folds (write-only) | timeline_test (indirect) | partiel |
| `coderain/memory.py` | `MemoryStore.rpg_state/set_rpg_state/rpg_enabled` | accès au bloc rpg de state.json | wave2-4_test | couvert |
| `coderain/memory.py` | `MemoryStore.index/lookup` | index en mémoire + recherche libre (tool lookup_memory) | camera_selection_test, test-element-camera | couvert |
| `coderain/memory.py` | `MemoryStore._entry_activates/_collapse_groups/_recursion_pass/_activate_lore` | moteur d'activation lorebook (Tier 1+2) | tier2_test | couvert |
| `coderain/memory.py` | `MemoryStore.lore_candidates` | rapport documentaliste (candidats, sans corps) | camera_selection_test, test-director-camera-patch | couvert |
| `coderain/memory.py` | `MemoryStore.assemble` | assemblage complet du contexte narrateur (chemin legacy) | phase2/3/5_test, wave2-4_test, tier2/3_test, test-garde-fuite-contexte-i376, regression_test | couvert |
| `coderain/memory.py` | `MemoryStore.strip_secrets_section` | retire la section Secrets du texte assemblé (I-108) | test-retrait-writer-i158 | couvert |
| `coderain/memory.py` | `MemoryIndex.__init__/resolve/relationships/dangling_refs/find` | index requêtable sur les entrées | tier2_test, wave2_test | couvert |
| `coderain/memory.py` | `trigger_hit` | match mot-entier d'un token dans un haystack | tier2_test (indirect) | partiel |
| `coderain/memory.py` | `trigger_gate` | geste commun de sélection par déclencheur | test-assembleur-position-d260, test-regles-evenement-verdicts-d260 | couvert |
| `coderain/memory.py` | `ScenarioLibrary` | bibliothèque de scénarios réutilisables | builder_test, default_scenario_test, phase5_saves_test | couvert |
| `coderain/memory.py` | `SaveLibrary.dir/meta/list/create/store/open/touch` | bibliothèque de saves | phase5_saves_test, snapshot_ouverture_i148_test, sweep2-5_test | couvert |
| `coderain/memory.py` | `SaveLibrary.branch` | fork à un tour N : restaure snapshot + rejoue le log | sweep2/4/5_test, wave4_test | couvert |
| `coderain/memory.py` | `SaveLibrary.duplicate/rename/delete/export/import_` | opérations de cycle de vie d'une save | phase5_saves_test, phase5_sweep_test, sweep3_test | couvert |
| `coderain/memory.py` | `_nearest_snapshot/_read_event_log/_write_event_log/_fold_end/_filter_folds_after/_reconcile_fold_state` | internes du branchement (SPEC-V2 §4.2) | sweep4/5_test (indirect via `.branch()`) | partiel |
| `coderain/memory.py` | `_sync_player_stats` | synchronise player.md ↔ state.json | stats_md_test, wave3_test | couvert |
| `coderain/memory.py` | `Library.__init__/reset_all_rules/create_story/list_stories/store/open` | façade top-level | rules_migration_test, quasi-totalité des tests moteur | couvert |
| `coderain/assembleur_position.py` | `eligible` | frontière de cohabitation position/partition vs assemble() legacy | test-assembleur-position-d260, test-branchement-position-d260, test-etage-scenario-d260, test-pont-mcp-position-d260 | couvert |
| `coderain/assembleur_position.py` | `rendu_md_for` | lit le rendu_md (couleur de ton) du node courant | rendu-md-service-i181-test | couvert |
| `coderain/assembleur_position.py` | `_current_node_section` | section stable : corps + objectif + potentiels (D-179) | test-assembleur-position-d260 | couvert |
| `coderain/assembleur_position.py` | `_presence_section` | records ancrés + secrets dont un porteur est présent | test-assembleur-position-d260, test-pont-mcp-position-d260 | couvert |
| `coderain/assembleur_position.py` | `_rule_verdicts_section` | verdicts de règles weight=heavy évalués CE TOUR | test-assembleur-position-d260 | couvert |
| `coderain/assembleur_position.py` | `_world_and_queue_section` | horloge + drapeaux + étage scénario ouvert | test-etage-scenario-d260 | couvert |
| `coderain/assembleur_position.py` | `build_sections` | construit le paquet ordonné complet | test-assembleur-position-d260, test-rpg-rules-socle-declencheur-d260, mesure-d260-boucle-neuve, rendu-md-service-i181-test | couvert |
| `coderain/assembleur_position.py` | `stable_prefix` | sous-ensemble byte-stable pour non-régression cache | test-assembleur-position-d260, test-prefixe-rpg-longueur-unique-d260 | couvert |
| `coderain/assembleur_position.py` | `to_messages` | rend le paquet en liste de messages | test-assembleur-position-d260 (via `assemble`) | couvert |
| `coderain/assembleur_position.py` | `assemble` | point d'entrée assemblage keyé position | test-assembleur-position-d260, test-branchement-position-d260 | couvert |
| `coderain/assembleur_position.py` | `_read_json_front/_brief/_potentials_text/_anchored_record_ids` (internes) | front-matter JSON, brief directeur.md, débouchés, records ancrés | test-assembleur-position-d260 (indirect via `build_sections`) | couvert |
| `coderain/mcp/position_etat.py` | `get_world_state` | état monde complet + section combat dérivée (I-463) | test-element-attaque-i463, test-visu-combats, wave2-4_test | couvert |
| `coderain/mcp/position_etat.py` | `opening_scene` | scène d'ouverture authored déjà traitée | aucun test direct de ce tool MCP | absent |
| `coderain/mcp/position_etat.py` | `get_event_rules` | relit event_rules_block() (LEGACY/DEBUG explicite) | test-retrait-writer-i158 (indirect) | partiel |
| `coderain/mcp/position_etat.py` | `validate_envelope` | valide une enveloppe sans l'appliquer | via `mcp_server.validator_mod.validate`, pas le tool lui-même | partiel |
| `coderain/mcp/position_etat.py` | `apply_envelope` | mutation unique : dice/state/reveals/events/RPG + stamp | 9+ fichiers (test-element-mort/jet-degats/attaque, test-paquet-narrateur-*, single-writer-guichet-i94) | couvert |
| `coderain/mcp/position_etat.py` | `assemble_context` | briefing Writer complet (proactif) | aucun test appelant le tool par son nom (`_assemble_text` seul est exercé) | partiel |
| `coderain/mcp/position_etat.py` | `assemble_context_to_file` | même briefing écrit en fichier | test-pont-mcp-position-d260, nuit_paires_turn_etancheite_test, test-banc-fumee-i151, test-retrait-writer-i158 | couvert |
| `coderain/mcp/position_etat.py` | `context_candidates` | rapport candidats (documentaliste) | `store.lore_candidates` testé directement ; le tool non appelé par son nom | partiel |
| `coderain/mcp/position_etat.py` | `ui_sheet` | rend + épingle la fiche perso à l'écran | gui_panel_test, test-fixture-personnage-banc-i257, test-visu-combats | couvert |
| `coderain/mcp/position_etat.py` | `module_index` | index du module converti (nodes/records/tables/secrets) | indirect via `load_partition` | partiel |
| `coderain/mcp/position_etat.py` | `module_list_nodes` | liste des nodes du module | aucun test direct du tool ; `load_partition(...)["nodes"]` testé | partiel |
| `coderain/mcp/position_etat.py` | `module_get_node` | lit un node (liens typés + corps verbatim) | aucun test direct du tool ; `get_node` testé directement ailleurs | partiel |
| `coderain/mcp/position_etat.py` | `module_get_record` | lit un statblock déjà 5e | aucun test direct du tool ; `get_record` testé directement ailleurs | partiel |
| `coderain/mcp/position_etat.py` | `module_roll_table` | résout une ligne de table à partir d'un jet | aucun test direct du tool ; `roll_table` testé directement | partiel |
| `coderain/mcp/position_etat.py` | `module_get_aventure` | lit l'étage AVENTURE | aucun test direct du tool | partiel |
| `coderain/mcp/position_etat.py` | `set_evolution_interne` | pose les vecteurs d'évolution interne (D-125/D-090) | `_validate_evolution_interne` testé directement ; le tool non appelé par son nom | partiel |
| `coderain/mcp/position_etat.py` | `derive_evolution_interne` | dérive un delta via `journal2vecteur` | `journal2vecteur` testé directement ; le tool non appelé par son nom | partiel |
| `coderain/save_lock.py` | `_pid_alive` | vivacité cross-platform d'un pid | test-verrou-save-i188 | couvert |
| `coderain/save_lock.py` | `read` | lit le lock (tolère absent/corrompu) | test-verrou-save-i188 | couvert |
| `coderain/save_lock.py` | `held_by_other_live_process` | None si libre, sinon le lock vivant | test-verrou-save-i188 | couvert |
| `coderain/save_lock.py` | `acquire` | écrit le lock de ce process, réclame un orphelin | test-verrou-save-i188 | couvert |
| `coderain/save_lock.py` | `release` | retire SON PROPRE lock uniquement | test-verrou-save-i188 | couvert |
| `coderain/sidecar.py` | `cfg_get` | valeur config RPG avec repli sur DEFAULT_CFG | wave2-4_test (indirect) | partiel |
| `coderain/sidecar.py` | `default_block` | bloc rpg par défaut (state.json shape-stable) | wave2/3_test | couvert |
| `coderain/sidecar.py` | `_first_json_object` (privé) | extraction brace-balanced d'un objet JSON | opencore_test | partiel |
| `coderain/sidecar.py` | `parse_sidecar` | extrait {check, deltas} d'une réponse narrateur | opencore_test, wave2-4_test | couvert |
| `coderain/sidecar.py` | `strip_sidecar` | sépare prose visible / sidecar dict | opencore_test, wave2-4_test | couvert |
| `coderain/sidecar.py` | `_partial_tail` (privé) | détecte un marqueur coupé en fin de buffer (streaming) | phase4_test (indirect) | partiel |
| `coderain/sidecar.py` | `filter_sidecar` | filtre le flux streamé, détourne le sidecar vers hidden_out | phase4_test, wave2-4_test | couvert |
| `coderain/models.py` | `platform_comparison_lines` | table texte alignée plateformes vs BYO | context_test | couvert |
| `coderain/models.py` | `context_hint_lines` | table texte alignée des tailles de contexte modèles | context_test | couvert |
| `coderain/models.py` | constantes (MIN_CONTEXT_TOKENS, HOSTED_PRESETS, etc.) | données de calibrage modèle/contexte | context_test couvre la plupart | partiel |
| `coderain/context.py` | (placeholder, aucune fonction) | note P1 receipt I-281, logique réelle dans `mcp_server.py` | `tests/context_test.py` teste en réalité `coderain/models.py`, pas ce fichier | absent (fichier vide de logique) |

#### TODO/FIXME/stubs trouvés

Aucun `TODO`/`FIXME`/`NotImplementedError` littéral trouvé dans les 8
fichiers de cet organe. Points faibles relevés par la lecture, pas des
marqueurs explicites :

- `coderain/context.py:1-3` — placeholder 3 lignes ; le nom
  `tests/context_test.py` suggère à tort qu'il teste ce module — il teste en
  réalité `coderain/models.py`.
- `coderain/engine.py:889-909` — `conversation_b_start`/`_submit`/
  `_personnage` délèguent entièrement à `webui` sans aucun test au niveau
  `Engine`.
- `coderain/mcp/position_etat.py` — neuf/dix tools n'ont aucun test qui les
  appelle PAR LEUR NOM (`opening_scene`, `assemble_context`,
  `context_candidates`, la famille `module_*`, `set_evolution_interne`,
  `derive_evolution_interne`) — seule la logique sous-jacente est exercée.
- `coderain/memory.py:1745-1750` (`_INTERNAL_ATTRS`) — filtre anti-fuite par
  nom fixe, pas de garde de schéma ; un futur attribut interne non listé
  fuirait au narrateur silencieusement — fragilité structurelle non testée
  par une assertion d'exhaustivité.

#### Chiffres

| fichier | lignes | fonctions/classes publiques | testées |
|---|---:|---:|---:|
| `coderain/engine.py` | 967 | 34 (Engine: 33 méthodes + `_any_applied`) | 30 |
| `coderain/mcp/position_etat.py` | 557 | 16 tools MCP | 7 couverts, 9 partiels |
| `coderain/memory.py` | 2474 | ~90 | ~75 |
| `coderain/assembleur_position.py` | 359 | 13 | 13 |
| `coderain/save_lock.py` | 138 | 5 | 5 |
| `coderain/sidecar.py` | 161 | 7 | 5 couvertes, 2 partielles |
| `coderain/models.py` | 207 | 2 fonctions + ~12 constantes | 2 fonctions couvertes, données partielles |
| `coderain/context.py` | 3 | 0 (placeholder) | n/a |

### 1.5 Bouchage

Le bouchage (D-275, Issue #253) traite un PETIT trou de règle en partie (un
nombre absent d'une fiche convertie, ou une micro-règle manquante) sans
arrêter la partie : `coderain/bouchage.py` porte la logique pure (lecture de
`rpg.provisoire`, normalisation des noms de champ, résumé mécanique de
scène, table de repli, extrait du vocabulaire fermé de règles) — aucun appel
réseau, aucune écriture. `coderain/mcp/bouchage.py` porte les deux outils
MCP qui encadrent le sous-agent juge.

#### Table

| fichier | fonction ou classe | rôle en une ligne | tests qui la couvrent | état |
|---|---|---|---|---|
| `coderain/bouchage.py` | `normaliser` | forme canonique sans accent/casse d'un texte | `test-element-bouchage-d275.py` | couvert |
| `coderain/bouchage.py` | `champ_canon` | nom canonique d'un champ de fiche | idem | couvert |
| `coderain/bouchage.py` | `fiche_canon` | slug de fiche visé | idem | couvert |
| `coderain/bouchage.py` | `entier` | parse un entier lisible ('+4', '16', 16) ou None | indirect via `appliquer_fiche`/`appliquer_stats` | couvert (indirect) |
| `coderain/bouchage.py` | `bloc` | bloc `rpg.provisoire` brut ou vide | indirect via `entrees`/`valeur_provisoire` | couvert (indirect) |
| `coderain/bouchage.py` | `entrees` | dict des bouchages enregistrés | indirect via `valeur_provisoire`/`appliquer_stats` | couvert (indirect) |
| `coderain/bouchage.py` | `nb_scenario` | compte de bouchages du scénario courant | appelée directement (I1) | couvert |
| `coderain/bouchage.py` | `id_trou` | id déterministe fiche+champ (ou `regle.<champ>`) | vérifié directement (C1) | couvert |
| `coderain/bouchage.py` | `valeur_provisoire` | valeur provisoire enregistrée pour (fiche, champ) | jamais appelée directement ; via `attack`/`roll_check` | couvert (indirect) |
| `coderain/bouchage.py` | `appliquer_fiche` | comble les nombres absents d'une fiche de combat | jamais appelée directement ; via `attack` | couvert (indirect) |
| `coderain/bouchage.py` | `appliquer_stats` | copie de stats complétée des modificateurs provisoires | jamais appelée directement ; via `roll_check`/`player_combat` | couvert (indirect) |
| `coderain/bouchage.py` | `resume_scene` | résumé mécanique (tour, lieu, temps, joueur, ennemis, dernier_jet) | vérifié directement (C3) | couvert |
| `coderain/bouchage.py` | `table_repli` | entrées `repli.md`, triées, bornées REPLI_MAX | vérifié (C2, D1) | couvert |
| `coderain/bouchage.py` | `vocabulaire` | vocabulaire fermé lu dans `docs/couverture-moteur.md` §4 | via `regles_concernees` (C4) ; branche "document absent" non exercée | partiel |
| `coderain/bouchage.py` | `regles_concernees` | extrait du vocabulaire lié à un trou, borné REGLES_MAX | vérifié (C4) ; branche `type: nombre → check.legacy` et plafonnement non vérifiés explicitement | partiel |
| `coderain/mcp/bouchage.py` | `demander_bouchage` | prépare le dossier (id, trou, scene, repli, regles, consigne) | tests A à I (refus, dossier bien formé, repli, journalisation) | couvert |
| `coderain/mcp/bouchage.py` | `enregistrer_bouchage` | trace la valeur jugée dans `rpg.provisoire`, incrémente le compteur | tests E, F, H, I | couvert |
| `coderain/mcp/bouchage.py` | `_trou_normalise` (privé) | valide/nettoie le `trou` reçu | exercé via `demander_bouchage` ; branche chaîne JSON jamais testée | partiel |
| `coderain/mcp/bouchage.py` | `_champ_deja_present` (privé) | un champ déjà écrit sur la fiche n'est pas un trou | exercé (B1, fiche de combat) ; branche attributs bruts hors combat non testée | partiel |
| `coderain/mcp/bouchage.py` | `_trou_du_dossier` (privé) | relit le `trou` du dernier dossier journalisé pour un id | exercé (E1) et à chaque enregistrement réussi | couvert |

#### TODO/FIXME/stubs trouvés

- Aucun `TODO`/`FIXME`/`NotImplementedError` littéral. `coderain/bouchage.py`
  et `coderain/mcp/bouchage.py` sont sans marqueur de périmètre — seules
  quelques branches (document `docs/couverture-moteur.md` absent, `trou` en
  chaîne JSON) restent non exercées, pas non codées.

#### Chiffres

| fichier | lignes | fonctions/classes publiques | testées |
|---|---:|---:|---:|
| `coderain/bouchage.py` | 344 | 15 | 15 (13 couvertes dont 5 indirectement, 2 partielles) |
| `coderain/mcp/bouchage.py` | 232 | 2 outils (+3 privées) | 2 outils couverts ; 2/3 privées partielles |

### 1.6 Combat

Voir §1.3 (Moteur de règles + combat) — `coderain/mcp/jets_combat.py` et
`coderain/modules/rpg.py` y sont déjà entièrement tabulés ; cette section
n'est pas dupliquée pour éviter deux verdicts divergents sur le même
fichier.

### 1.7 Formes et tensions

Le stock de formes (D-261, `coderain/formes.py`) est le vocabulaire narratif
composable et versionné (Propp, Polti, contes-types ATU — domaine public,
`catalogue/formes/`) dans lequel un futur organe d'écriture d'épisode
(Issue #133, **pas encore câblé**) devra choisir plutôt qu'inventer
librement. `coderain/echeancier.py` (D-253.1, Issue #71) extrait, depuis une
`Aventure` déjà construite, les conditions vivantes/échues/à-état, et porte
la garde qui refuse la perte d'une condition vivante entre deux passes de
réadaptation d'un module.

#### Table

| fichier | fonction ou classe | rôle en une ligne | tests qui la couvrent | état |
|---|---|---|---|---|
| `coderain/formes.py` | `Forme` (+ `to_prompt_dict`) | atome composable du stock (id, nom, source, description, exige, compose_avec) | `test-formes-d261.py` §0/0b, §5/5b | couvert |
| `coderain/formes.py` | `charger_vocabulaire` | lit `catalogue/formes/*.json` → dict id→Forme | §0 (comptes Propp 31/31, Polti 36/36, ATU 20-40) ; branche "id dupliqué → ValueError" jamais déclenchée | partiel |
| `coderain/formes.py` | `valider_declaration` | garde de forme : refuse déclaration vide, id hors vocabulaire, justification vide | §1-4, exhaustif | couvert |
| `coderain/formes.py` | `bloc_prompt` | bloc de prompt figé présentant le vocabulaire | §5, §5b | couvert |
| `coderain/echeancier.py` | `ConditionVivante` (dataclass) | condition datée/à délai non échue | construite/lue via `extraire`/`garder_reportage` ; `to_dict()` jamais appelé | partiel |
| `coderain/echeancier.py` | `ConditionEtat` (dataclass) | déclencheur `etat`, hors périmètre garde v0 | construite via `extraire` ; `to_dict()` jamais appelé | partiel |
| `coderain/echeancier.py` | `Echeancier`+`rapport` | inventaire vivantes/échues/etats/avertissements | `rapport()` appelé dans les assertions des deux fichiers de test | couvert |
| `coderain/echeancier.py` | `extraire` | extrait l'échéancier d'une `Aventure` à une date de référence | test-echeancier-trans-modules.py, test-dks-regime-trans-modules.py (fixture synthétique ET partition DKS réelle) | couvert |
| `coderain/echeancier.py` | `garder_reportage` | garde de ré-émission : refuse la perte d'une condition vivante | test-echeancier §3-6, test-dks §2 | couvert |
| `coderain/echeancier.py` | `_parse_delai_jours`/`_parse_date`/`_ancre` (privés) | parsing délai/date/composition d'ancre | exercés indirectement via `extraire` | couvert (indirect) |

#### TODO/FIXME/stubs trouvés

- `coderain/echeancier.py:35,123` — « Hors périmètre garde v0 : les
  déclencheurs `etat` (non datés, D-119) n'ont pas de notion d'échéance
  calendaire » — limite de conception assumée et documentée, pas un TODO à
  corriger.
- `coderain/formes.py:24-26` — « L'organe qui écrit les épisodes n'existe
  pas encore dans le code (issue #133) : ce module pose le socle
  consommable par lui, sans câblage dans un organe inexistant » — le stock
  de formes est donc un socle non branché en aval (aucun
  `NotImplementedError`, mais fonctionnellement non consommé hors tests).
- Aucun `TODO`/`FIXME`/`NotImplementedError` littéral dans les deux
  fichiers.

#### Chiffres

| fichier | lignes | fonctions/classes publiques | testées |
|---|---:|---:|---:|
| `coderain/formes.py` | 155 | 4 | 4 (3 couvertes, 1 partielle) |
| `coderain/echeancier.py` | 221 | 5 publiques (+3 privées) | 5/5 publiques (3 couvertes, 2 partielles) |

### 1.8 Auteur (campagne, toile, actes, écriture de module)

L'Auteur porte ce qui structure une campagne au-delà d'une scène : la
mémoire propre à l'organe (`campagne.py` — fils rouges, `toile.py` — secrets
tissés, `acte.py` — grandes étapes à trois lectures), la détection de redite
inter-scénarios (`author.py`), la négociation personnage+contrat en amont
d'une partie (`proposeur.py`, `selecteur.py`) et la chaîne d'écriture d'un
module-épisode quand le joueur sort du prévu (`ecrivain_module.py` +
`retour2.py`, contrôle de conformité texte-contre-texte). `generator.py` est
un organe voisin mais distinct dans le code (Feature 4, génération de
scénario complet) : aucun import partagé avec le reste du lot, inclus ici
par regroupement de lane plutôt que par couplage de code.

Doctrine transverse répétée dans quasi tous ces fichiers : le code
assemble/valide/persiste, **jamais** ne juge ni ne score (D-131/D-118) ;
rien n'est jamais réécrit ni supprimé, seul le statut change ; une reprise
après refus doit être **AUTRE**, jamais une variation cosmétique (D-232).

#### Table

| fichier | fonction ou classe | rôle en une ligne | tests qui la couvrent | état |
|---|---|---|---|---|
| `coderain/author.py` | `SignalRepetition`, `SEUIL_SIMILARITE`, `comparer_paire`, `detecter_campagne`, `rapport` | signal/rapport de redite de tension (2 scénarios, même code D-218) | `test-repetition-campagne.py` | couvert |
| `coderain/author.py` | `SignalRepetitionForme`, `comparer_paire_formes`, `detecter_campagne_formes`, `rapport_formes` | même famille pour les redites de forme (Propp/Polti/ATU, D-261) | `test-formes-d261.py` | couvert |
| `coderain/acte.py` | `Jalon`, `Raccord`, `Acte`, `Actes` | modèle d'un acte (objectif, jalons, raccord, statut) | `acte_test.py` | couvert |
| `coderain/acte.py` | `load`/`load_file`/`render`/`save_file` | parse/sérialise `actes.md`, round-trip octet-stable | `acte_test.py` | couvert |
| `coderain/acte.py` | `validate` | garde de forme (id slug, doublons, objectif/intention absents, statuts hors vocabulaire) | `acte_test.py` | couvert |
| `coderain/acte.py` | `remplissage` | lecture 1 : comptage vécu/pas-vécu/abandonné + vécu promu | `acte_test.py` | couvert |
| `coderain/acte.py` | `pieces_divergence` | lecture 2 : objectif + vécu récent, aucun score | `acte_test.py` | couvert |
| `coderain/acte.py` | `bloc_cadre` | rendu complet des 3 lectures pour un prompt d'Auteur | `acte_test.py`, `test-ecrivain-module-i143.py` | couvert |
| `coderain/campagne.py` | `FilRouge`, `Campagne`, `load`/`load_file`/`render`/`save_file` | fils rouges + ambition finale, parse/sérialise `campagne.md` | `campagne_test.py` | couvert |
| `coderain/campagne.py` | `set_statut` | transition actif→promu\|scelle, jamais supprimé | `campagne_test.py` | couvert |
| `coderain/campagne.py` | `validate` | forme + résolution des `porte` (record/flag/quête) | `campagne_test.py` | couvert |
| `coderain/campagne.py` | `rapport` | actifs par registre, ancienneté, signal de stagnation (I-186) | `campagne_test.py` | couvert |
| `coderain/toile.py` | `FilToile`, `Toile`, `load`/`load_file`/`render`/`save_file` | secrets tracés, parse/sérialise `toile.md` | `toile_test.py` | couvert |
| `coderain/toile.py` | `set_etat` | transition latent→revele→caduc, jamais de retour arrière | `toile_test.py` | couvert |
| `coderain/toile.py` | `validate` | forme + ancre_module/condition obligatoires + rattachement résolu | `toile_test.py` | couvert |
| `coderain/ecrivain_module.py` | `REGIMES`, `ModuleEcrit`, `RapportEcriture` | vocabulaire fermé + structures de sortie validées | `test-ecrivain-module-i143.py` | couvert |
| `coderain/ecrivain_module.py` | `vers_scenario_auteur` | câble `declaration_rendu` vers `scenario-auteur.json` | `test-ecrivain-module-i143.py`, `test-element-rendu-md-auteur.py` | couvert |
| `coderain/ecrivain_module.py` | `ecrire_module` | chaîne complète cadre→régime→formes→écriture→retour2, 1 re-demande max | `test-ecrivain-module-i143.py` (succès, échec formes, succès après re-demande, échec retour2, régime inconnu) | couvert |
| `coderain/ecrivain_module.py` | `_bloc_regime`/`_objectifs_regime`/`_valider_declaration_rendu` (privés, testés directement) | bloc de prompt du régime / objectifs retour2 / garde de forme sur `declaration_rendu` | `test-ecrivain-module-i143.py`, `test-verrou-declaration-rendu-identite-i191.py` (identité AST avec la copie MCP) | couvert |
| `coderain/retour2.py` | `VERDICTS_VALIDES`, `Objectif`, `VerdictConformite`, `VerdictForme`, `RapportConformite` | vocabulaire fermé de verdict, jamais de note chiffrée | `test-retour2-conformite-i139.py` | couvert |
| `coderain/retour2.py` | `retour2` | jugement LLM texte-contre-texte + garde de forme (10 scénarios distincts) | `test-retour2-conformite-i139.py` | couvert |
| `coderain/proposeur.py` | `EnvieJoueur`, `ElementPropose`, `Friction`, `Proposition` | personnage+contrat proposés, signature anti-rafistolage | `test-proposeur-refus-i370c.py` | couvert |
| `coderain/proposeur.py` | `valider`/`valider_ancrage` | forme + ancrage à un candidat/envie connus | `test-proposeur-refus-i370c.py`, `test-raccord-selecteur-proposeur-i57.py` | couvert |
| `coderain/proposeur.py` | `RegistreProposeur` (`proposer`/`refuser`/`retenir`/`capturer_friction`) | journal append-only, refuse la reproposition sans friction ou rafistolage (D-245/D-232) | `test-proposeur-refus-i370c.py` | couvert |
| `coderain/proposeur.py` | `rendu_joueur` | rendu montrable, jamais d'ancre_source/id/statut interne | `test-proposeur-refus-i370c.py` (grep zéro-fuite) | couvert |
| `coderain/selecteur.py` | `EntreeCatalogue`, `CandidatActe` | entrée catalogue + candidat d'acte ancré (2-3 modules) | `test-selecteur-matiere-i370b.py`, `test-raccord-selecteur-proposeur-i57.py` | couvert |
| `coderain/selecteur.py` | `selectionner` | jugement LLM + garde de forme (9 scénarios de rejet) | `test-selecteur-matiere-i370b.py` | couvert |
| `coderain/selecteur.py` | `sortie_montrable` | concatène les `libelle` seuls (zéro-spoiler) | `test-selecteur-matiere-i370b.py` | couvert |
| `coderain/generator.py` | `GenerationError`, `ScenarioSpec` | échec fort premise / réglages utilisateur | `generator_test.py`, `builder_test.py` | couvert |
| `coderain/generator.py` | `generate_scenario` | orchestre premise→(factions)→personnages/lieux/objets→threads→introduction | `generator_test.py` (fast, rich, échec premise, retry 0-entité, improve opt-in) | couvert |
| `coderain/generator.py` | `assist_field`/`complete_scenario` | assist IA un-shot par champ / complète uniquement ce qui manque | `builder_test.py` §5-6 | couvert |
| `coderain/generator.py` | `PIECE_KINDS`, `_entry_from` (privée, testée directement) | table kind→builder / construit une `Entry` depuis un dict LLM | `generator_test.py`, `wave3_test.py` | couvert |

#### TODO/FIXME/stubs trouvés

Aucun `TODO`/`FIXME`/`NotImplementedError` dans ces neuf fichiers. Tournures
de périmètre présentes mais descriptives (D-186/D-241/D-232, doctrine
« lecture et rapport seuls, jamais branché en séance ») — pas des défauts.
Une note obsolète sans conséquence : `coderain/acte.py:264` renvoie au
« futur organe d'écriture d'épisodes, hors périmètre » — cet organe
(`ecrivain_module.py`) existe désormais et importe `bloc_cadre`, le
commentaire n'a simplement pas été mis à jour.

#### Chiffres

| fichier | lignes | fonctions/classes publiques | testées |
|---|---:|---:|---:|
| `coderain/author.py` | 196 | 8 | 8 |
| `coderain/acte.py` | 308 | 12 | 12 |
| `coderain/campagne.py` | 226 | 9 | 9 |
| `coderain/toile.py` | 171 | 8 | 8 |
| `coderain/ecrivain_module.py` | 387 | 5 (+3 privées testées directement) | 8 |
| `coderain/retour2.py` | 328 | 6 | 6 |
| `coderain/proposeur.py` | 229 | 10 | 10 |
| `coderain/selecteur.py` | 218 | 6 | 6 |
| `coderain/generator.py` | 726 | 6 (+1 privée testée directement) | 7 |

### 1.9 Banc de mesure (`tools/banc/`)

Cinq scripts autonomes, tous MÉCANIQUES (aucun LLM) qui arbitrent/mesurent le
contrat de fichiers d'une nuit de banc (Issue #260/#276/#295/#299/#305/#306/
#281) : extraction de la prose du narrateur, détection de fin de partie,
fabrication de la save de DÉPART gelée, calcul des métriques/rapport de
nuit. Chacun est appelé en sous-processus par `nuit.sh`, jamais importé en
production. Tous les cinq sont abondamment testés (14 à 24 assertions par
test dédié), logique interne `_`-préfixée comprise.

#### Table

| fichier | fonction ou classe | rôle en une ligne | tests qui la couvrent | état |
|---|---|---|---|---|
| `tools/banc/arbitrer_prose.py` | `signal_pollution` | détecte titre md/bloc code/mention Director-visée dans un prose-NN.md écrit à la main | `arbitrer_prose_test.py`, `nuit_prose_polluee_test.py` | couvert |
| `tools/banc/arbitrer_prose.py` | `arbitrer` | tranche voie extraction (primaire) vs voie fichier (repli tolérant) vs échec | `arbitrer_prose_test.py`, `nuit_prose_voie_fichier_test.py`, `nuit_prose_polluee_test.py` | couvert |
| `tools/banc/arbitrer_prose.py` | `main` | CLI (usage, codes 0/1/2) | `arbitrer_prose_test.py`, `test-banc-fumee-i151.py` | couvert |
| `tools/banc/detecter_fin.py` | `evaluer` | statue mort/fin_module/non depuis la partition + state.json | `detecter_fin_test.py` | couvert |
| `tools/banc/detecter_fin.py` | `main` | CLI, sortie fixe `fin:`/`noeud:` | `detecter_fin_test.py` | couvert |
| `tools/banc/detecter_fin.py` | `_lire_json`/`_partition_dir` (privés) | lecture tolérante module.json/state.json | via `evaluer` | couvert (indirect) |
| `tools/banc/extraire_prose.py` | `extraire_prose` | extraction mécanique de la section « Prose du Narrateur » de tour-NN.md | `extraire_prose_test.py`, `arbitrer_prose_test.py` | couvert |
| `tools/banc/extraire_prose.py` | `main` | CLI, sortie 0/1 | `extraire_prose_test.py`, `test-bench-prose-i150.py` | couvert |
| `tools/banc/metriques_nuit.py` | `lire_events`/`compter_refus_outil`/`compter_bouchages`/`compter_combats` | parsing events.jsonl + comptages | `metriques_nuit_test.py` | couvert |
| `tools/banc/metriques_nuit.py` | `tours_sans_craquement`/`lire_resume_run`/`lire_noeud`/`tours_par_noeud` | mesure de progression par partie/nœud (#306) | `metriques_nuit_test.py`, `rapport_nuit_test.py` | couvert |
| `tools/banc/metriques_nuit.py` | `compter_paires` | nombre de paires Director/joueur distinctes (#282) | `metriques_nuit_test.py` | couvert |
| `tools/banc/metriques_nuit.py` | `_compter_craquements_par_role`/`compter_timeouts_par_role`/`compter_processus_sortis_par_role` | imputation joueur/mj des timeouts (#299) et processus sortis (#305) | `metriques_nuit_test.py` | couvert |
| `tools/banc/metriques_nuit.py` | `calculer`/`formater_markdown` | agrège/rend toutes les métriques §3 de #201 | `metriques_nuit_test.py` | couvert |
| `tools/banc/metriques_nuit.py` | `extraire_classe_craquement`/`lister_craquements`/`craquements_par_classe` | classement D-276 §4 des craquements | `rapport_nuit_test.py` | couvert |
| `tools/banc/metriques_nuit.py` | `lire_director_modele`/`stats_ab_director` | A/B Director (haiku ⊥ sonnet) | `rapport_nuit_test.py` | couvert |
| `tools/banc/metriques_nuit.py` | `pires_craquements`/`lire_module_info` | pointeurs craquements récents / ligne Module (#281) | `rapport_nuit_test.py` | couvert |
| `tools/banc/metriques_nuit.py` | `calculer_rapport`/`formater_rapport_markdown`/`main` | `rapport-nuit.md` complet (#276), CLI deux modes | `metriques_nuit_test.py`, `rapport_nuit_test.py` | couvert |
| `tools/banc/save-depart.py` | `_scenario_slug_depuis`/`_partition_dir_depuis` (privés) | résolution scénario/partition depuis une save jouée existante | `save_depart_test.py` | couvert |
| `tools/banc/save-depart.py` | `fabriquer` | fabrique la save de DÉPART (tour 0, module installé, fixture personnage) | `save_depart_test.py`, `nuit_garde_save_depart_test.py` | couvert |
| `tools/banc/save-depart.py` | `verifier` | vérifie sur disque le contrat (tour 0, personnage, module installé) | `save_depart_test.py` | couvert |
| `tools/banc/save-depart.py` | `main` | CLI argparse (`--slug`/`--from-save`/`--scenario`/`--profil`/`--force`) | surtout via `fabriquer`/`verifier` directs, peu de test CLI bout en bout | partiel |

#### TODO/FIXME/stubs trouvés

- `tools/banc/metriques_nuit.py:11-24` — `refus_outil`/`combats_sous_systeme`
  restent à 0 en pratique (« aucun writer du moteur ne journalise ces refus
  dans events.jsonl » / combats dnd5e-engine non journalisés) — HORS
  PÉRIMÈTRE #260, pas un bug du banc.
- `tools/banc/metriques_nuit.py:60-64,309-311,376` — classification D-276 §4
  des craquements : tout token de classe non reconnu compte « non classé »
  — classification N2 explicitement hors périmètre #276.
- Aucun `TODO`/`FIXME`/`NotImplementedError` littéral dans les 5 fichiers.

#### Chiffres

| fichier | lignes | fonctions/classes publiques | testées |
|---|---:|---:|---:|
| `tools/banc/arbitrer_prose.py` | 152 | 3 | 3 |
| `tools/banc/detecter_fin.py` | 124 | 2 (+2 privées) | 2 |
| `tools/banc/extraire_prose.py` | 102 | 2 | 2 |
| `tools/banc/metriques_nuit.py` | 537 | 19 | 19 |
| `tools/banc/save-depart.py` | 309 | 3 (+2 privées) | 3 |

### 1.10 Modules annexes (director-pipeline, vector, LLM, validator, config, …)

Le pipeline Quad optionnel (director-pipeline, `coderain/modules/trinity.py`,
hors chemin joué en production — ARCHITECTURE.md §1), le rappel sémantique
vectoriel, le client LLM provider-agnostique + streaming pur, le Validator
(moteur de légalité pur code de l'enveloppe v1), le pipeline de fold/résumé
mémoire, le routeur d'entrée joueur, les macros ST-20, l'import de
character-card, la config/les features/les profils de personnage et les
gabarits de fichiers d'une save/d'un scénario, et le monde par défaut
« The Veil ». La plupart de ces fichiers sont au cœur du chemin joué
(validator, templates, config, summarizer, input_processor, streaming,
llm) ; `trinity.py` seul est un banc opt-in, testé mais jamais le défaut.

#### Table

| fichier | fonction ou classe | rôle en une ligne | tests qui la couvrent | état |
|---|---|---|---|---|
| `coderain/modules/trinity.py` | `TrinityBrain` (props, `_direct`, `_redirect`, `_keep_lore`, `_writer_context`/`_writer_messages`, `generate`, `_apply_fallback`) | pipeline Quad complet : Director→Validator→(Lore-keeper)→Writer, jamais le chemin joué par défaut | `trinity_test.py`, `test-retrait-writer-i158.py`, wave2-4/sweep2-6_test.py | couvert (opt-in, hors chemin joué par défaut) |
| `coderain/modules/trinity.py` | `_stage_llm`/`_tail_user`/`_plan_text`/`_writer_directive` (internes) | résolution client pinné, texte du plan, directive Writer | `trinity_test.py` | couvert |
| `coderain/modules/vector.py` | `Embedder`, `VectorIndex`, `Retriever`, `build_retriever` | index.db dérivé, ré-embed incrémental, recherche par salience, callable `assemble()` | `phase5_vector_test.py`, `phase6_pre_sweep_test.py` | couvert |
| `coderain/llm.py` | `LLM.stream`/`.complete`/`.complete_with_tools` | client chat OpenAI-compatible, boucle tool-calling | `streaming_test.py`, `trinity_test.py`, `regression_test.py`, `tier3_test.py`, `acte_test.py` | couvert |
| `coderain/llm.py` | `emit_json_ex`/`emit_json` | émission JSON structurée avec retry + raison d'échec | `phase2_test.py` (via Summarizer), `trinity_test.py` (via Director/redirect) | couvert (indirect, pas de test unitaire isolé) |
| `coderain/llm.py` | `extract_json` | extraction {..} brace-balanced depuis texte modèle | aucun appel direct ; exercé en interne par `emit_json_ex`/`TrinityBrain._keep_lore` | partiel |
| `coderain/streaming.py` | `ThinkFilter.feed`/`.flush`, `filter_think` | filtre push/pull `<think>` split-safe | `streaming_test.py`, `phase4_test.py`, `regression_test.py` | couvert |
| `coderain/summarizer.py` | `Summarizer.maybe_fold`/`_fold_scene`/`_fold_arc` | fold scène/arc, snapshot pré-fold | `phase2/3_test.py`, `phase3_sweep_test.py`, `wave2_test.py` | couvert |
| `coderain/summarizer.py` | `_apply_promotions`/`_apply_time`/`_existing_context` | promotion d'entités, clock monotone, contexte tronqué | `phase2_test.py`, `summarizer_troncature_importance_test.py`, `test-garde-agentivite-i462.py` | couvert |
| `coderain/summarizer.py` | `_append_scenario_note`/`fermer_scenario`/`scenario_stage_chars` | étage scénario D-260 lane c | `test-etage-scenario-d260.py` | couvert |
| `coderain/input_processor.py` | `process` | routage parole/intériorité/action/commande + LE PACK (jamais tranché de force) | `test-processeur-entree-i373.py` | couvert |
| `coderain/input_processor.py` | `classify_pack_ratio` | lecture qualitative de pack_ratio | `test-processeur-entree-i373.py` | couvert |
| `coderain/input_processor.py` | `extraire_interiorite` | écrit l'intériorité vers un réceptacle STUB déclaré (D-233b) | `test-processeur-entree-i373.py` | couvert (mais écrit dans un stub déclaré, pas le vrai support) |
| `coderain/validator.py` | `validate` | schéma + légalité de l'enveloppe v1 complète | `validator_test.py` (957 lignes de règles) | couvert |
| `coderain/validator.py` | `apply_world` | applique time_advance/flag_set/location/gold/quest_update/persist/beat_advance | `validator_test.py`, `trinity_test.py`, `wave*_test.py` | couvert |
| `coderain/validator.py` | `known_skills`/`skill_trained`/`fold_skill` | vocabulaire de compétences (I-213) | `validator_test.py` | couvert |
| `coderain/validator.py` | `guard_world_state` | garde single-writer (I-94) | `single-writer-guichet-i94_test.py` | couvert |
| `coderain/validator.py` | `replay_records` | ré-application déterministe pour rebuild de branche | `undo_test.py`, `test-branchement-position-d260.py` | couvert |
| `coderain/validator.py` | `scan_hidden_forced` | garde secrets I-159 | `validator_test.py` | couvert |
| `coderain/validator.py` | `scan_missing_origin` | garde agentivité I-462/D-107 | `test-garde-agentivite-i462.py` | couvert |
| `coderain/validator.py` | `current_location`/`store_clock`/`rejection_text`/`snapshot_state` | accesseurs/helpers | `validator_test.py`, usage prod dans `detecter_fin.py` | couvert |
| `coderain/macros.py` | `expand_macros` (+`_roll` privé) | macros ST-20 ({{user}}, {{roll}}, {{random}}…), replay-safe | `tier3_test.py` | couvert |
| `coderain/cards.py` | `parse_card`/`substitute_macros` | import character-card V1/V2/V3 (PNG/JSON/.charx) | `cards_test.py` | couvert |
| `coderain/config.py` | `load_config` | charge config.yaml + .env | dépendance transitive de ~34 fichiers tests/*.py | couvert |
| `coderain/config.py` | `build_profile` | résout un profil nommé, utilisé aussi par Trinity par étage | `trinity_test.py` | couvert |
| `coderain/config.py` | `context_budget` | budget mémoire en tokens, dérivation `auto` | `context_test.py` | couvert |
| `coderain/config.py` | `corpus_dir` | racine du corpus de campagne (hors dépôt, D-178/D-224) | ~22 fichiers tests/*.py | couvert |
| `coderain/config.py` | `saves_dir` | racine des saves d'une Library | `mesure-d260-boucle-neuve.py` (indirect) | partiel |
| `coderain/config.py` | `save_yaml` | persiste tout le dict config vers config.yaml | `phase2_gui_test.py` | couvert |
| `coderain/config.py` | `read_env`/`write_env` | lecture/écriture de .env (Settings GUI) | aucun test trouvé | absent |
| `coderain/config.py` | `_home_dir` (privé) | résolution CODERAIN_HOME/frozen/repo | exercé implicitement via ROOT, pas de test dédié aux 3 branches | partiel |
| `coderain/features.py` | `module`/`pro_module`/`enabled` | seam optionnel (rpg/multi_brain/vector_recall/memory_tool) | `opencore_test.py`, `mesure-d260-boucle-neuve.py` | couvert |
| `coderain/profiles.py` | `CharacterProfiles`, `PieceLibrary` | CRUD characters.json / library.json | `builder_test.py` | couvert |
| `coderain/profiles.py` | `apply_character` | seed player.md depuis un profil (démarrage "play-as") | aucun appel direct trouvé (seule `apply_playable_entry` testée) | absent |
| `coderain/profiles.py` | `apply_playable_entry`/`entry_from_character`/`character_from_entry` | seed depuis pièce scénario / aller-retour profil↔Entry | `builder_test.py` | couvert |
| `coderain/templates.py` | `new_save` | instancie une partie (copie scénario + fichiers play-state frais) | ~30 fichiers tests/*.py, `tools/banc/save-depart.py` (usage prod) | couvert |
| `coderain/templates.py` | `seed_scenario` | fabrique un monde réutilisable | ~11 fichiers tests/*.py via `Library.scenarios.create()` | couvert (indirect) |
| `coderain/templates.py` | `seed_instructions` | seed + migration des masters de règles globales | `rules_migration_test.py` | couvert |
| `coderain/templates.py` | `split_rpg_rules` | découpe socle/section "Level-ups" de rpg-rules.md | `test-prefixe-rpg-longueur-unique-d260.py` | couvert |
| `coderain/templates.py` | `slugify`/`initial_state`/`default_rule`/`user_default`/`_seed_save_aids` | slug générique, state.json initial, textes par défaut, aids.json | `builder_test.py`, `rules_migration_test.py`, `default_scenario_test.py` | couvert |
| `coderain/default_scenario.py` | `seed` | écrit le monde bundlé « The Veil » (idempotent) | `default_scenario_test.py` | couvert |

#### TODO/FIXME/stubs trouvés

- `coderain/input_processor.py:162` — `STUB_INTERIORITE` : réceptacle stub
  explicitement nommé « D-233b, le support biographique réel n'existe pas
  encore côté repo » — testé, mais écrit sciemment dans un stub.
- Aucun autre `TODO`/`FIXME`/`NotImplementedError` littéral dans les 14
  fichiers de cet organe.

#### Chiffres

| fichier | lignes | fonctions/classes publiques | testées |
|---|---:|---:|---:|
| `coderain/modules/trinity.py` | 456 | 1 classe (9 méthodes/props) + 4 helpers | 13 (hors chemin joué par défaut) |
| `coderain/modules/vector.py` | 257 | 4 classes + `build_retriever` | couvert |
| `coderain/llm.py` | 203 | 1 classe (5 méthodes) + 3 fonctions | 4/5 (`extract_json` non testé directement) |
| `coderain/streaming.py` | 104 | 1 classe + `filter_think` | 2/2 |
| `coderain/summarizer.py` | 539 | 1 classe (~10 méthodes) + 2 fonctions | tous couverts |
| `coderain/input_processor.py` | 184 | 3 (+2 privés) | 3/3 |
| `coderain/validator.py` | 957 | ~20 | 20/20 |
| `coderain/macros.py` | 66 | 1 (+1 privé) | 1/1 |
| `coderain/cards.py` | 157 | 2 (+3 privés) | 2/2 |
| `coderain/config.py` | 270 | 9 + 2 dataclasses | 7/9 (`read_env`/`write_env` non testés) |
| `coderain/features.py` | 50 | 3 | 3/3 |
| `coderain/profiles.py` | 276 | 2 classes + 4 fonctions | 5/6 (`apply_character` non exercée) |
| `coderain/templates.py` | 762 | ~10 | 10/10 (partiellement indirect) |
| `coderain/default_scenario.py` | 430 | 1 | 1/1 |

### 1.11 Interfaces (pont MCP, webui, régime CLI/web secondaire)

Deux régimes cohabitent sans partager de couverture (D-267). Le régime
**FORFAIT/MCP produit** — `mcp_server.py` (bridge d'état, aucun outil MCP
direct) + ses 7 sous-modules `coderain/mcp/*.py` (56 outils MCP au total),
plus `webui.py` (écran joueur local) — est le chemin que joue réellement une
partie : testé très inégalement (pipeline combat et gardes anti-fuite
solides ; écran joueur, fold mémoire et lecture de module quasi nus). Le
régime **CLI/web secondaire** — `server.py` (FastAPI, ~90 routes), `play.py`
(REPL), `gui.py` (Tkinter), `desktop.py`/`start.py`/`build.py` — est une
façade alternative sur le même moteur, quasiment jamais exercée par
`tests/` en tant que contrat d'interface. `statusline_gauge.py` est une
sonde de statut, hors chemin de jeu.

Les outils `mcp/jets_combat.py` (§1.3), `mcp/bouchage.py` (§1.5) et
`mcp/position_etat.py` (§1.4) sont déjà tabulés dans leur organe métier —
non répétés ici pour éviter deux verdicts sur le même fichier.

#### Table

| fichier | fonction ou classe | rôle en une ligne | tests qui la couvrent | état |
|---|---|---|---|---|
| `mcp_server.py` | `journal2vecteur` (seule fonction publique) | dérive un delta de vecteur d'évolution interne depuis un acte RP | `test-evolution-interne-i200.py` | couvert |
| `mcp_server.py` | `_validate_evolution_interne` | valide les vecteurs contre le schéma D-125/D-090 | `test-evolution-interne-i200.py` | couvert |
| `mcp_server.py` | `_lore_warnings` | avertit sans nommer une entrée cachée+pinned/critical | `test-garde-secrets-i159.py` | couvert |
| `mcp_server.py` | `_attack_fiche` | fiche de combat lue telle qu'écrite, jamais complétée | `test-element-attaque-i463.py`, `test-fixture-personnage-banc-i257.py` | couvert |
| `mcp_server.py` | `_skill_mod_ranked` | modificateur de compétence par rang | appelée via roll_check/attack, format non testé isolément | partiel |
| `mcp_server.py` | `_secrets_segment`/`_hidden_entries`/`_body_probes`/`_hidden_exposure`/`_splice_secrets` | garde anti-fuite double haystack lore/secrets (D-269) | `test-garde-fuite-contexte-i376.py`, `test-element-camera.py` | couvert |
| `mcp_server.py` | `_slug_named`/`_content_leak`/`_r2_scan` | filet R2 (fuite littérale dans la directive Director) | `test-paquet-narrateur-i192.py` §6/6b/6c | couvert |
| `mcp_server.py` | `_wide_history`/`_position_context_text`/`_finalize`/`_assemble_text` | assemblage double-haystack lore/secrets | `test-pont-mcp-position-d260.py`, `test-element-camera.py`, `test-director-camera-patch.py` | couvert |
| `mcp_server.py` | `_run_fold`/`_fold_probe`/`_NeedLLM`/`_ShimLLM` | shim LLM du fold mémoire, alimente `fold_due`/`fold_apply` | aucun | absent |
| `mcp_server.py` | `_arm_turn`/`_stage_rollback`/`_restamp_turn_log` | armement/rejeu du rollback de tour (undo/retry) | aucun test direct | absent |
| `mcp_server.py` | `_combat_event_str`/`_record_combat_events` | traduit les événements combat en lignes lisibles pour R1 | `test-paquet-narrateur-combat-i200.py` | couvert |
| `mcp_server.py` | `_module_partition` | résout la partition pointée par `module.json` | indirect via `p4_convert_step` ; jamais via les outils `module_*` | partiel |
| `mcp_server.py` | `_auteur_bloc_regime`/`_auteur_objectifs_regime`/`_auteur_payload_retour2`/`_auteur_valider_verdict(_forme)`/`_auteur_synthese` | logique de rendu/garde des organes Auteur (D-263) | `test-pont-mcp-auteur-d263.py` | couvert |
| `mcp_server.py` | `_auteur_valider_declaration_rendu` | garde de forme sur `declaration_rendu` | `test-verrou-declaration-rendu-identite-i191.py` (parité octet-à-octet, pas fonctionnel direct) | partiel |
| `mcp_server.py` | `_echo_checks`/`_release_save_lock` | affiche chaque jet dans le webui / libère le verrou de save à l'arrêt | aucun | absent |
| `coderain/mcp/narrateur.py` | `paquet_narrateur` | compose le paquet narrateur (contexte+mécaniques+R1/R2) | `test-paquet-narrateur-i192.py`, `-combat-i200.py`, `test-schisme-position-i197.py` | couvert |
| `coderain/mcp/narrateur.py` | `record_turn` | enregistre l'échange et réarme le tour ("CALL THIS AT THE END OF EVERY TURN") | aucun | absent |
| `coderain/mcp/narrateur.py` | `companions` | liste les compagnons éligibles | `wave3_test.py` teste `eng.companions()`, pas l'outil MCP | partiel |
| `coderain/mcp/narrateur.py` | `companion_prompt`/`companion_log` | prompt système / journalisation du side-chat compagnon | aucun | absent |
| `coderain/mcp/narrateur.py` | `ui_open`/`ui_say`/`ui_wait`/`ui_panel`/`ui_close` | démarre/affiche/attend/met à jour/arrête l'écran joueur | aucun | absent |
| `coderain/mcp/save_installation.py` | `list_saves` | liste les sauvegardes | aucun (lib `saves.list()` sous-jacente testée) | absent |
| `coderain/mcp/save_installation.py` | `load_save` | charge une save, verrou de session anti-collision | `test-verrou-save-i188.py` | couvert |
| `coderain/mcp/save_installation.py` | `save_snapshot`/`save_branch` | duplique / fork-rewind la save courante | aucun (libs `saves.duplicate()`/`saves.branch()` testées en aval) | absent |
| `coderain/mcp/save_installation.py` | `undo_last` | annule le dernier échange, restaure mécanique | `undo_test.py` teste `engine.undo_last()`, pas le wrapper | partiel |
| `coderain/mcp/save_installation.py` | `import_card` | importe une fiche SillyTavern | `cards_test.py` teste `cards.parse_card()`, pas le wrapper | partiel |
| `coderain/mcp/save_installation.py` | `p4_convert_step` | pilote une conversion P4 pas à pas | `test-pont-mcp-conversion-p4-i173.py` | couvert |
| `coderain/mcp/memoire_rappel.py` | `lookup_memory`/`recall_turns`/`recall_entity`/`recall_quest` | recherche/rappel mémoire, wrappers MCP | `store.lookup`/`store.recall_*` testés en aval, jamais les wrappers par leur nom | partiel |
| `coderain/mcp/memoire_rappel.py` | `retry_turn` | reprend le dernier échange, restaure la mécanique | `test-corrections-dispositif-v2.py` simule la logique en commentaire, n'appelle jamais le wrapper | absent (quasi) |
| `coderain/mcp/memoire_rappel.py` | `fold_due`/`fold_apply` | sonde/applique le fold mémoire dû | aucun | absent |
| `coderain/mcp/auteur.py` | `auteur_bloc_cadre`/`auteur_valider_ecriture`/`auteur_verdicts_conformite` | pose le cadre / gardes forme / gardes verdicts de conformité (D-263) | `test-pont-mcp-auteur-d263.py` §1-3 | couvert |
| `webui.py` | `say`/`set_panel`/`set_sheet`/`set_title`/`set_status`/`wait`/`set_gauge`/`snapshot`/`reset` | état partagé de l'écran joueur | aucun test direct | absent |
| `webui.py` | `start`/`stop`/`is_running` | (dé)marrage idempotent du serveur HTTP local | aucun (des tests vérifient juste que le fichier existe, sans l'exécuter) | absent |
| `webui.py` | `_Handler.do_GET`/`do_POST` | routes `/`, `/poll`, `/health`, `/say`, `/gauge`, `/conv-b/*` | aucune requête HTTP réelle envoyée dans les tests | absent |
| `webui.py` | `ConversationB` (F1→F4, garde zéro-spoiler, `guard_output`, `personnage`) | 4 fenêtres jouables de conversation de démarrage (D-219) | `test-conversation-b-outillage.py` (avec partition réelle) | couvert |
| `webui.py` | `ConversationB._check_reformulation`/`_accept_reformulation` (branches limites) | détection contradiction non-négociable / reformulation | cas limites non couverts | partiel |
| `webui.py` | `conv_b_start`/`conv_b_submit`/`conv_b_state`/`conv_b_personnage` | wrappers module reliant `ConversationB` au serveur global | aucun (les tests appellent la classe directement) | absent |
| `server.py` | routes `/api/saves*`, `/api/scenarios*`, `/api/library*`, `/api/characters*`, `/api/models/*`, `/api/settings`, `/api/profiles*`, import/export, `/api/defaults*`, `index()`, `__main__` | CRUD save + boucle de jeu (SSE), builder de monde, bibliothèque, découverte modèles, config/profils, import/export, service SPA | aucun (pas de `TestClient`/`httpx` contre l'app) | absent |
| `play.py` | `pick_scenario`/`create_scenario`/`new_save`/`choose_save`/`_open`/`main` (boucle REPL) | sélection/création interactive + interface CLI complète | aucun | absent |
| `gui.py` | bootstrap (`App.__init__`, `_init_style`, `_build_menubar`, `_open_story`), onglet Memory, panneau fiche perso, onglet Editor | fenêtre principale, édition brute, UI de jeu annexe, éditeur structuré | `phase2_gui_test.py`, `gui_panel_test.py`, `gui_editor_test.py` | couvert |
| `gui.py` | boucle de jeu réelle (`_on_send`/`_on_retry`/`_on_undo`/`_start_generation`/`_drain_queue`), `_talk_dialog`, dialogues CRUD, onglet Settings | envoi/génération/retry via l'UI, side-chat, popups, config | aucun (round-trip YAML testé directement sur `save_yaml`, pas via `_save_settings`) | absent |
| `desktop.py` | `_fix_std_streams`/`_free_port`/`main` | lance uvicorn en thread + fenêtre pywebview chromeless | aucun | absent |
| `start.py` | `_venv_python`/`_bootstrap_and_reexec`/`_ensure_deps`/`_run_web`/`main` | bootstrap venv + routage des modes `--cli/--gui/web` | aucun | absent |
| `build.py` | script top-level PyInstaller (pas de fonctions) | empaquetage build | aucun (build réel non exécuté en CI hors-ligne) | absent |
| `statusline_gauge.py` | `main` | lit le JSON stdin Claude Code, pousse la jauge de contexte au webui | aucun | absent |

#### TODO/FIXME/stubs trouvés

Aucune occurrence de `TODO`/`FIXME`/`NotImplementedError`/"jamais
branché"/"V0" dans les 13 fichiers de l'organe. Seule mention connexe :
`coderain/mcp/position_etat.py:60-72` qualifie déjà `get_event_rules`
explicitement de « LEGACY/DEBUG » (repris en §1.4). Tous les éléments
listés `absent` ici ont une implémentation complète — ce ne sont pas des
stubs, seulement des chemins jamais exercés par `tests/`.

#### Chiffres

| fichier | lignes | fonctions/classes publiques | testées |
|---|---:|---:|---:|
| `mcp_server.py` | 1813 | 46 fonctions internes + 1 publique + 2 classes ; 0 outil MCP direct | ~14 couvertes / 4 partielles / 5 absentes |
| `coderain/mcp/narrateur.py` | 321 | 10 outils MCP | 1 couvert, 1 partiel, 8 absents |
| `coderain/mcp/save_installation.py` | 231 | 7 outils MCP | 2 couverts, 2 partiels, 3 absents |
| `coderain/mcp/memoire_rappel.py` | 121 | 7 outils MCP | 0 couvert, 5 partiels, 2 absents |
| `coderain/mcp/auteur.py` | 221 | 3 outils MCP | 3 couverts |
| **Total outils MCP exposés (7 sous-modules mcp/)** | — | **56** | **~30 couverts / ~15 partiels / ~11 absents** (cumul avec jets_combat.py/bouchage.py/position_etat.py déjà comptés en §1.3-1.5) |
| `webui.py` | 709 | 34 unités | 18 couvertes/partielles (ConversationB seule) / 16 absentes |
| `server.py` | 1613 | ~90 (routes + helpers) | 0 |
| `play.py` | 381 | 16 | 0 |
| `gui.py` | 1624 | ~45 | ~13 |
| `desktop.py` | 78 | 3 | 0 |
| `start.py` | 166 | 9 | 0 |
| `build.py` | 37 | 0 (script) | 0 |
| `statusline_gauge.py` | 92 | 1 | 0 |

**Constat de synthèse de l'organe** : le régime FORFAIT/MCP produit a une
couverture très inégale mais concentrée sur les chemins critiques
(combat, gardes anti-fuite R1/R2, `apply_envelope`, `paquet_narrateur`,
organes Auteur D-263) — tous couverts. À l'inverse, trois familles
entières n'ont aucune couverture directe : l'écran joueur (`ui_*` +
`webui.py` sauf `ConversationB`), le fold mémoire côté pont
(`fold_due`/`fold_apply`), et la lecture de module côté outils MCP
(`module_*` sauf `p4_convert_step`). Le régime CLI/web secondaire n'a
aucun test qui l'exécute en tant que contrat d'interface — seule `gui.py`
en bénéficie, pour environ un tiers de ses méthodes.

### 1.12 Fichiers d'agrégation (`__init__.py`)

Trois fichiers `__init__.py` supplémentaires (le quatrième,
`coderain/converter/__init__.py`, est déjà tabulé en §1.2), tous des
docstrings de module sans logique :

| fichier | rôle en une ligne | tests qui la couvrent | état |
|---|---|---|---|
| `coderain/__init__.py` | docstring de paquet + `__version__` | exercé transitivement par tout import `coderain.*` | couvert (indirect, pas de logique propre) |
| `coderain/mcp/__init__.py` | docstring listant les familles d'outils MCP (I-233) | exercé transitivement | couvert (indirect, pas de logique propre) |
| `coderain/modules/__init__.py` | docstring décrivant les modules optionnels (rpg/trinity/vector) + `__version__` | exercé transitivement | couvert (indirect, pas de logique propre) |

---

## 2. Ce que le code dit qu'il ne fait pas

Recherche exhaustive de `TODO`/`FIXME`/`NotImplementedError` et des
tournures « jamais branché en séance »/« en cible »/« V0 »/« v0 » dans les 73
fichiers de `coderain/`+`tools/`, fichier par fichier (7 lectures
indépendantes, zéro fichier sauté). **Aucun `TODO`/`FIXME`/
`NotImplementedError` littéral n'existe dans ce périmètre.** Les seules
occurrences trouvées documentent une frontière ASSUMÉE, pas un oubli :

| fichier:ligne | citation | nature |
|---|---|---|
| `coderain/converter/annexe_a.py:3` | « DRAFT v0 » | squelette de champs jamais remplacé par le SRD complet annoncé |
| `coderain/rules_engine/engine_bridge.py:9-10` | « Coexistence v0 : les jets simples hors combat restent dans `coderain.modules.rpg`, NON touché » | frontière de conception assumée |
| `coderain/rules_engine/monster_bridge.py:19-23` | « Portée volontairement minimale (« suffit pour la fumée ») » | scope réduit assumé (I-205) |
| `coderain/echeancier.py:35,123` | « Hors périmètre garde v0 : les déclencheurs `etat`… » | limite de conception documentée |
| `coderain/formes.py:24-26` | « L'organe qui écrit les épisodes n'existe pas encore dans le code (issue #133) » | socle posé, pas encore consommé en aval |
| `coderain/input_processor.py:162` | `STUB_INTERIORITE` — « D-233b, le support biographique réel n'existe pas encore côté repo » | seul stub NOMMÉ comme tel dans tout le périmètre |
| `coderain/author.py:12`, `campagne.py:23`, `toile.py:30` | « lecture et rapport seuls, jamais branché en séance »/« ce module ne branche rien en séance » | doctrine D-186/D-241 assumée |
| `coderain/proposeur.py:5` | « registre méta, hors périmètre de ce repo » | renvoi vault D-232/D-245 |
| `coderain/mcp/position_etat.py:60-72` | `get_event_rules` qualifié « LEGACY/DEBUG » | usage explicitement daté |
| `coderain/acte.py:264` | « le futur organe d'écriture d'épisodes, hors périmètre de cette lane » | **obsolète** : `ecrivain_module.py` est cet organe et importe déjà `bloc_cadre` |
| `docs/couverture-moteur.md` (rappel, déjà mesuré) | `combat.cast_spell` existe côté moteur, non mentionné/testé côté pont coderain | trou fonctionnel, pas un marqueur littéral |

---

## 3. Moteur de règles (renvoi)

Le détail complet de ce que `dnd5e-engine` résout (catégories de règle,
limites connues, table de sollicitation DKS) a déjà été mesuré par
`docs/couverture-moteur.md` (#235) et n'est pas reproduit ici : §1.3
ci-dessus en reprend la table 1 sous forme fichier/fonction/tests/état pour
rester dans le format uniforme de ce document, sans réviser ses constats.

---

## 4. Code sans aucun test (au-delà des organes ci-dessus, vue consolidée)

Fonctions/outils avec une implémentation complète mais qu'aucun test
n'exerce par son nom (« absent » dans les tableaux du §1) :

- **Convertisseur** : `converter/install.py::doctor`, `cli.py` sous-commandes
  `install`/`doctor`/`project`/`all` (via `main()`), `emit.py::read_manifest`,
  `cli.py::_extract_text` branche `.pdf`, `converter/__main__.py`.
- **Convertisseur (code mort)** : `semantic.py::absorb_tensions` — pas
  seulement non testée, jamais APPELÉE par le pipeline réel (voir §2/§1.2).
- **État et mémoire** : `Engine.conversation_b_start`/`_submit`/
  `_personnage` ; neuf tools de `mcp/position_etat.py`
  (`opening_scene`, `assemble_context`, `context_candidates`, toute la
  famille `module_*`, `set_evolution_interne`, `derive_evolution_interne`).
- **Interfaces — pont MCP** : `mcp_server.py::_run_fold`/`_fold_probe`/
  `_NeedLLM`/`_ShimLLM`/`_arm_turn`/`_stage_rollback`/`_restamp_turn_log`/
  `_echo_checks`/`_release_save_lock` ; `mcp/narrateur.py::record_turn` et
  les 5 outils `ui_*` + `companion_prompt`/`companion_log` ;
  `mcp/save_installation.py::list_saves`/`save_snapshot`/`save_branch` ;
  `mcp/memoire_rappel.py::retry_turn`/`fold_due`/`fold_apply`.
- **Interfaces — webui/régime secondaire** : `webui.py` en quasi-totalité
  hors `ConversationB` ; la totalité de `server.py`, `play.py`,
  `desktop.py`, `start.py`, `build.py`, `statusline_gauge.py` ; les deux
  tiers de `gui.py` (boucle de jeu réelle, Settings, dialogues).
- **Modules annexes** : `coderain/config.py::read_env`/`write_env` ;
  `coderain/profiles.py::apply_character` ; `coderain/llm.py::extract_json`
  (testé seulement via ses appelants).

## 5. Tests orphelins

Un test est dit orphelin ici quand son sujet (le symbole qu'il importe ou la
fonctionnalité qu'il décrit) n'existe plus dans le code. Vérification :
la suite complète (`python run_tests.py`, 171 fichiers sous `tests/`) passe
au vert de bout en bout sur cette branche (hook pré-commit local, CLAUDE.md)
— un test dont le sujet aurait disparu casserait à l'import (`ImportError`/
`AttributeError`) et ferait échouer la suite, donc **aucun test orphelin par
rupture d'import n'existe actuellement** dans les 171 fichiers.

Deux orphelins **de fond** (le test tourne et passe, mais teste autre chose
que ce que son nom promet) relevés par les 7 lectures :

- `tests/context_test.py` — le nom suggère qu'il teste `coderain/context.py`
  (placeholder 3 lignes, §1.4) ; il teste en réalité `coderain/models.py`.
- `tests/test-corrections-dispositif-v2.py` — sur `retry_turn`, **simule** la
  logique en commentaire plutôt que d'appeler
  `mcp_server.retry_turn()` : le sujet nominal (le wrapper MCP) n'est jamais
  exercé, seule sa logique métier sous-jacente l'est ailleurs.

Décompte des conventions de nommage (`tests/` + `tests/fixtures/`, cf. #252) :

| convention | nombre |
|---|---:|
| `<nom>_test.py` | 100 |
| `test-<nom>.py` / `test_<nom>.py` | 63 |
| hors les deux motifs ci-dessus (`document-illustration-d2521-test.py` et proches comptés dans `test-<nom>`, plus `mesure-d260-boucle-neuve.py`, `tests/run_tests.py`) | 6 |
| `tests/fixtures/*.py` (harnais partagé, pas des tests autonomes) | 2 |
| **Total fichiers `.py` sous `tests/`** | **171** |

---

## 6. Chiffres de tête

| périmètre | fichiers `.py` | lignes |
|---|---:|---:|
| `coderain/` | 68 | ~20 300 |
| `tools/` (banc) | 5 | ~1 650 |
| **Sous-total coderain/+tools/ (périmètre de l'acceptation #314)** | **73** | **21 952** |
| Racine (interfaces + lancement) | 10 | 6 551 |
| **Total mesuré** | **83** | **28 503** |
| `tests/` (+ `tests/fixtures/`) | 171 | — (hors périmètre de comptage de lignes de cette mesure) |

Par organe (fonctions/classes publiques recensées → testées, voir détail par
fichier dans chaque section du §1) :

| organe | fichiers | fonctions/classes publiques (approx.) | testées |
|---|---:|---:|---:|
| Convertisseur (§1.2) | 21 | ~72 | ~66 couvertes, 1 stub mort, 2 orphelines de câblage |
| Moteur de règles + combat (§1.3) | 5 | 39 | 36 couvertes, 3 partielles |
| État et mémoire (§1.4) | 8 | ~167 | ~137 couvertes/partielles confondues |
| Bouchage (§1.5) | 2 | 17 (+ 3 privées) | 17 couvertes/partielles |
| Formes et tensions (§1.7) | 2 | 9 (+ 3 privées) | 9 couvertes/partielles |
| Auteur (§1.8) | 9 | ~70 | ~70 couvertes |
| Banc de mesure (§1.9) | 5 | 29 | 29 couvertes |
| Modules annexes (§1.10) | 14 | ~85 | ~78 couvertes |
| Interfaces (§1.11) | 13 | ~330 (dont 56 outils MCP) | ~76 couvertes/partielles |
| `__init__.py` (§1.12) | 4 | 0 (agrégation) | n/a |
| **Total** | **83** | **~810** | dominé par « couvert » sur le chemin joué (combat, boucle de tour, Auteur, banc), concentré en « absent » sur trois familles précises : écran joueur, fold mémoire côté pont, régime CLI/web secondaire (détail §1.11 et §4) |

*Méthode de comptage (identique à `docs/couverture-moteur.md`) : une
« fonction/classe publique » compte une dataclass ou une exception pour 1,
plus ses méthodes non triviales ; une fonction privée n'est comptée que si
un test l'importe et l'appelle nommément (seam interne jugé digne d'un test
direct par le code lui-même). Les totaux par organe sont des sommes des
tableaux « Chiffres » de chaque section — approximatifs sur les plus gros
fichiers (`engine.py`, `memory.py`, `mcp_server.py`) où compter chaque
méthode d'une classe de plusieurs centaines de lignes introduit une marge
de ±quelques unités sans changer le diagnostic.*
