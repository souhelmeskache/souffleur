# Triage du stock — 38 issues confrontées au code du 29/08 (Issue #149)

Lane de lecture et de rapport uniquement : aucun code modifié, aucune issue
fermée, aucun label posé. Chaque verdict ci-dessous est vérifié au code réel
(grep/lecture) — jamais au seul titre de la fiche. Une FICHE peut être
construite sous un nom différent de celui qu'elle emploie ; le contenu du
contrat a été vérifié, pas seulement l'existence d'un fichier au nom proche.

**Périmètre demandé par #149** : les 22 FICHE (#85-#106) et « 14 items »
(#108-#123). Constat : la plage #108-#123 contient en réalité **16** issues
ouvertes (108 à 123 inclus, sans trou), pas 14 — le chiffre de l'énoncé
semble erroné ou compte deux issues déjà closes entre-temps. Les 16 sont
couvertes ci-dessous par prudence (mieux couvrir une de plus que d'en
sauter une). Total réel traité : **38 issues**.

Méthode : cinq lots de lecture indépendants (agents dédiés), chacun grep/lit
le code réel (`coderain/`, `tests/`, `docs/`, `specs/`, `catalogue/`,
`tools/`, `.github/`) en regard du contenu de chaque fiche/item, puis produit
verdict + preuve + détail + recommandation. Un verdict sans preuve concrète
(chemin de fichier + fonction/ligne) retombe à VIVANT par défaut — appliqué
strictement.

## Tableau de synthèse

| Verdict | Compte | Issues |
|---|---|---|
| **CONSTRUIT** | 5 | #86, #87, #88, #89, #101 |
| **PARTIEL** | 14 | #85, #90, #91, #92, #93, #94, #95, #96, #100, #102, #103, #105, #110, #121 |
| **VIVANT** | 18 | #98, #99, #104, #106, #108, #109, #111, #112, #113, #114, #115, #116, #117, #118, #119, #120, #122, #123 |
| **PÉRIMÉ** | 1 | #97 |
| **Total** | **38** | |

Lecture rapide pour le mainteneur : **5 fermetures directes possibles**
(#86, #87, #88, #89, #101 — contrat vérifié construit et testé), **14
requalifications** (une moitié construite documentée, l'autre moitié à
garder comme fiche réduite), **18 fiches/items qui restent VIVANTS tels
quels** (rien de correspondant trouvé au code, la fiche garde sa valeur
intégrale), et **1 PÉRIMÉ** (#97, dont la dépendance citée pointe vers un
tout autre organe que celui livré sous ce nom).

---

## FICHE #85-#106

### #85 — FICHE — Le copiste
**Verdict** : PARTIEL
**Preuve** : `catalogue/README.md` (schéma d'entrée à 4 champs + valideur de forme) ; `catalogue/univers-planescape/module-beyond-the-vale-of-madness.md` (en-tête : « Entrée remplie **après coup** depuis le module publié » — remplissage manuel) ; commit `5a9ad7c` (catalogue I-193 : convention d'entrée + valideur, 3 fixtures factices). `grep -rln "copiste"` ne retourne que `catalogue/README.md`, aucun code Python.
**Détail** : le débouché (b) — forme d'entrée de catalogue à 4 champs, gelée — est construit et validé. Mais l'organe copiste lui-même (survol automatisé PDF → transcription, régime Haiku/DÉDUIRE de `D-095`) n'existe dans aucun module `coderain/` : l'unique entrée réelle a été remplie manuellement « après coup ». Le débouché (a), bibliothèque de lore indexée par univers, n'a pas de contrepartie (le « lore » de `coderain/memory.py` est le lorebook runtime du narrateur, un objet différent).
**Recommandation** : requalifier — garder la fiche pour l'organe d'ingestion automatisée manquant, fermer la partie « forme d'entrée de catalogue » avec pointeur `catalogue/README.md` + commit `5a9ad7c`.

### #86 — FICHE — Le scripteur / convertisseur (contrat)
**Verdict** : CONSTRUIT
**Preuve** : `coderain/converter/buckets.py` (`classify`, triage `D-141`) ; `coderain/converter/schemas.py:252,300` (`fonction`/`charge`/`agenda`/`portee`, D-113/D-119/D-120) ; `coderain/converter/schemas.py:38` (`contrat`, alias D-218) ; `docs/audit-2-materiel-campagne-d252.md`, `docs/audit-completude-buckets-d249.md` ; commits `36343d9`, `8b1c520` (Personnage+Destinee, `emit.py`/`validate_form.py` garde zéro-dangling).
**Détail** : les trois dettes citées (buckets rangés, FONCTION+CHARGE descendues dans les formats moteur, débouché matière-à-contrats) sont couvertes. La question ouverte « bucket de plus ou passe séparée » est tranchée en pratique : objet séparé `Personnage`, pas un bucket.
**Recommandation** : fermer avec pointeur (commits `36343d9`, `8b1c520`, `docs/audit-completude-buckets-d249.md`, `docs/audit-2-materiel-campagne-d252.md`).

### #87 — FICHE — Le catalogue de modules (contrat)
**Verdict** : CONSTRUIT
**Preuve** : `catalogue/README.md` (schéma 4 champs, valideur 11 règles) ; `coderain/selecteur.py` (`EntreeCatalogue`, `selectionner`, sortie `CandidatActe`, garde d'ancrage `_valider_candidat`) ; commits `5a9ad7c` (I-193) et `ecb52fa` (I-370b, D-244).
**Détail** : le passage à l'échelle d'un ACTE (2-3 modules chaînés) est implémenté dans `selecteur.py`. Le 5e champ « compatibilité d'enchaînement » et le compteur de requêtes vides (3e signal) restent des questions ouvertes non tranchées dans le code.
**Recommandation** : fermer avec pointeur (`catalogue/README.md`, `coderain/selecteur.py`, commits `5a9ad7c`/`ecb52fa`) en gardant les deux questions résiduelles comme sous-issues séparées.

### #88 — FICHE — Le moteur de règles (contrat)
**Verdict** : CONSTRUIT
**Preuve** : `requirements.txt:24` (`dnd5e-engine==0.3.0`, épinglé) ; `coderain/rules_engine/` (pont hôte, D-200) ; `mcp_server.py:1873-1937` (`resolve_check`, `start_combat`, `submit_intent`, `monster_turn`, `end_combat`, `narration_events`) ; `tests/test_rules_engine.py` (deux exécutions mêmes graines → transcripts identiques, ligne ~76-138 ; k intentions illégales → k refus motivés).
**Détail** : la question ouverte n°1 de la fiche (« le test deux-graines-identiques a-t-il été réellement écrit ? ») est répondue OUI dans le code (`tests/test_rules_engine.py:134`). Le chemin statblock custom → record (question n°2) n'a qu'une garde partielle (`coderain/converter/ruletables.py:39`), sans verdict tranché refus/dégradation silencieuse.
**Recommandation** : fermer avec pointeur (`tests/test_rules_engine.py`) ; requalifier la question n°2 (statblock custom) en sous-issue isolée.

### #89 — FICHE — Le sélecteur et le proposeur (création)
**Verdict** : CONSTRUIT
**Preuve** : `coderain/selecteur.py` (étape 2) ; `coderain/proposeur.py` (étapes 3-4, `Friction`, doctrine D-232/D-245 : contrat refusé → autre proposition, jamais un rafistolage) ; commit `02ddb48`/`d75d26b` (garde `I-1562` réparée) ; conversation B/fenêtres : commit `8934352` (webui, F1-F4, `coderain/engine.py::conversation_b_*`) ; `tests/test-selecteur-matiere-i370b.py`, `tests/test-proposeur-refus-i370c.py`, `tests/test-raccord-selecteur-proposeur-i57.py`.
**Détail** : les 5 étapes de la séquence D-232 ont chacune une contrepartie codée et testée. La dépendance bloquante `I-1562` est réparée. Le raccord contrat→biographie et le lien `CandidatActe` unique sont couverts (commit `73e0843`, I-57). Note : D-245 (arbitrage du 29/08) durcit le protocole de refus au-delà de ce que demandait la fiche — une évolution postérieure, pas une contradiction.
**Recommandation** : fermer avec pointeur (commits `ecb52fa`, `5a2d992`, `73e0843`, `02ddb48`, `8934352`).

### #90 — FICHE — L'Auteur en création (la toile et le premier acte)
**Verdict** : PARTIEL
**Preuve** : `coderain/toile.py` (`FilToile`, `load`/`render`/`validate`, transitions latent→révélé/caduc, garde d'ancrage testée dans `tests/toile_test.py:152-156`) ; commit `e498b3d` (I-371a). `coderain/acte.py` (`Acte`, `Jalon`, `Raccord`, `remplissage`/`pieces_divergence`/`bloc_cadre`) ; commit `9a427c9` (D-262). `coderain/echeancier.py:14-15` : « Ce module fournit les deux briques, **jamais l'organe de réadaptation lui-même** (chantier I-371d, séparé) ».
**Détail** : format de toile (tracée/vérifiable/latente) et composition du premier acte sont construits et testés. Le tissage dédié à la création est esquissé indirectement (`coderain/formes.py:129,147`) mais pas comme fonction propre. La réadaptation module-après-module (question ouverte n°2) est explicitement documentée comme non implémentée par le code lui-même.
**Recommandation** : requalifier — fermer (a) format toile et (c) composition d'acte avec pointeurs `toile.py`/`acte.py`/commits `e498b3d`/`9a427c9` ; garder ouverts (b) tissage dédié et (d) réadaptation post-module.

### #91 — FICHE — campagne.md, le support
**Verdict** : PARTIEL
**Preuve** : `docs/verification-campagne-md-d186.md` (rapport complet §1-§7) + `coderain/campagne.py:73,83-88,109,173-174` (ambition_finale), `:32-43,143-159` (grammaire porte), `:107-124` (render) ; `tests/campagne_test.py:53-65,96-117,132-145`. Recherche `campagne` sur `coderain/context.py`, `coderain/converter/*`, `coderain/memory.py` → 0 occurrence fonctionnelle.
**Détail** : la vérification d'implantation + rapport d'écarts (issue a) est déjà faite intégralement dans `docs/verification-campagne-md-d186.md`, chaque champ conforme à D-186. Mais l'issue (b) — écrivains nommés + test grep — n'est qu'à moitié acquise : le grep zéro-fuite existe déjà, mais aucun ÉCRIVAIN réel n'appelle `campagne.save_file()`/`render()` en production (aucun outil MCP, aucune commande CLI/webui) — écart rapporté explicitement dans le même document (§3).
**Recommandation** : requalifier — fermer (a) avec pointeur `docs/verification-campagne-md-d186.md` ; réduire la fiche à la seule question (b) : qui écrit `campagne.md` et câbler l'écrivain nommé.

### #92 — FICHE — Le processeur d'entrée
**Verdict** : PARTIEL
**Preuve** : `coderain/input_processor.py` (table de routage D-092, `QUOTE_RE`/`PAREN_RE`/`EMDASH_RE`, `COMMANDES`) ; `docs/processeur-entree-i373.md` (table complète, PACK, métrique `pack_ratio`) ; `tests/test-processeur-entree-i373.py`. Grep `silencieux`/`N1` → aucune occurrence.
**Détail** : trois des quatre volets sont construits — table de routage (3 registres + commandes annuler/rejouer), LE PACK avec proposition de lecture, métrique `pack_ratio` testée, extracteur des `( )` raccordé au stub « dit ». Le quatrième — « le silencieux » (N1) — n'a aucune trace : aucun mécanisme ne capte ce que le joueur tait, décision jamais prise (le code lui-même marque l'hypothèse N4 « NON CONFIRMÉE », `input_processor.py:9-13`).
**Recommandation** : requalifier — fermer (a)(b)(c) avec pointeur `docs/processeur-entree-i373.md` + `coderain/input_processor.py` ; garder uniquement (d) « le silencieux » comme fiche résiduelle.

### #93 — FICHE — Le Director (contrat)
**Verdict** : PARTIEL
**Preuve** : `docs/mesure-i158-director-deux-corps.md` (mesure I-158 complète) ; `docs/rapatriement-director.md` (patch D-219/D-220 appliqué, testé) ; `tests/test-director-conversation-b-patch.py`. Grep `I-173`/`fraicheur`/`xhigh`/`D-095`/`D-099` sur `tests/` → aucun test dédié de réglage d'effort ou de fraîcheur inter-tour.
**Détail** : la mesure I-158 du contexte reçu (issue a) est intégralement livrée. La question ouverte n°1 (Issue #15) est en réalité déjà traitée (patch appliqué avec test de non-régression). Mais le test de fraîcheur inter-tour avec fixtures piégées (b) et le test `I-173` de prise d'effort low vs xhigh (c) n'existent nulle part dans `tests/`.
**Recommandation** : requalifier — fermer (a) et la question Issue #15 avec pointeur `docs/mesure-i158-director-deux-corps.md` + `docs/rapatriement-director.md` ; garder (b) fraîcheur et (c) test `I-173` comme fiche résiduelle.

### #94 — FICHE — Le moteur de faits et son guichet
**Verdict** : PARTIEL
**Preuve** : `tests/test-chemins-morts-i375.py` (4 chemins inventaire/PV/or/XP exercés via `Engine.apply_envelope`, latence mesurée, single-writer testé). Grep `horloge|friction` → seulement `TENSION_CATEGORIES` (`coderain/converter/schemas.py:29`, catégorie narrative sans rapport), aucune horloge-fait D-155 dans `coderain/memory.py` ni `coderain/echeancier.py`.
**Détail** : le test d'élément des chemins morts + latence (a) est intégralement construit et exécuté. La vérification « un seul écrivain » (b) est construite mais le test lui-même **constate** (sans corriger) qu'une écriture directe via `MemoryStore.set_world_state` (`coderain/memory.py:1044`) peut contourner le guichet sans passer par `validator.py:194-197` — la garde n'est donc pas structurellement garantie. Le cran d'horloge D-155/N3 (c) n'a aucune trace.
**Recommandation** : requalifier — fermer (a) et le diagnostic (b) avec pointeur `tests/test-chemins-morts-i375.py` ; garder la remédiation « single writer non garanti » + (c) horloges D-155/N3.

### #95 — FICHE — La caméra et le narrateur
**Verdict** : PARTIEL
**Preuve** : `tests/test-element-camera.py` (fixtures hors-champ/partiel/secret) ; `tests/test-garde-fuite-contexte-i376.py` (garde de fuite, `MemoryStore.assemble()`). Grep `81.6|81,6|improvisation_rate` → aucune occurrence hors un GIF binaire, aucune métrique de taux d'improvisation par run.
**Détail** : le test caméra (a) et les gardes de contexte narrateur (b) sont construits et testés précisément. Le suivi du taux d'improvisation par run (c, baseline 81,6 %) n'a aucune implémentation retrouvée.
**Recommandation** : requalifier — fermer (a) et (b) avec pointeur `tests/test-element-camera.py` + `tests/test-garde-fuite-contexte-i376.py` ; garder (c) suivi du taux d'improvisation.

### #96 — FICHE — Le repliement (contrat)
**Verdict** : PARTIEL
**Preuve** : `coderain/summarizer.py:151` (`_apply_promotions`, stamping `origin`) ; `tests/test-garde-agentivite-i462.py` ; `docs/garde-agentivite-i462.md`. Grep « couture F »/`D-141` → citée uniquement dans le bucketing convertisseur (`coderain/converter/buckets.py:1`), jamais amendée pour inclure le repliement.
**Détail** : saillance (D-126) et garde d'agentivité (I-462) sont construites et testées. La « couture F » (statut d'écrivain rangé pour le repliement) reste non tranchée — écart confirmé « jamais tranché » depuis le 08/08. Aucune mesure de durée du fold (tours avant perte) trouvée.
**Recommandation** : requalifier — fermer saillance/agentivité avec pointeur `coderain/summarizer.py::_apply_promotions` + `tests/test-garde-agentivite-i462.py` ; garder couture F + mesure de durée.

### #97 — FICHE — L'Auteur de l'entre-deux
**Verdict** : PÉRIMÉ
**Preuve** : `coderain/author.py:1-9` (docstring : « L'Auteur — détecteur de répétition à l'échelle campagne (I-229) »winking, fonctions `comparer_paire`/`detecter_campagne`/`rapport`. Aucune mention de « horloge », « entre-deux » ou N2 nulle part dans `coderain/`.
**Détail** : la fiche cite `author.py` livré (#13, socle) comme support de l'Auteur qui « fait tourner les horloges » de l'entre-deux — mais le `author.py` réellement livré est un détecteur de répétition de tensions/formes entre scénarios, un tout autre organe. Le postulat de dépendance de la fiche est contredit par le code livré sous ce nom ; aucun mécanisme d'entre-deux (horloges par friction, extrapolation N2) n'existe où que ce soit.
**Recommandation** : requalifier — corriger la dépendance erronée (« author.py livré » ne couvre pas ce périmètre), garder le reste de la fiche tel quel puisque rien de l'entre-deux n'est construit.

### #98 — FICHE — La récompense macro et les objectifs du joueur
**Verdict** : VIVANT
**Preuve** : aucune correspondance trouvée — `grep -rn "D-233|D-086|récompense" coderain/ mcp_server.py` ne remonte que `D-100` (`mcp_server.py:1949,2066`), un contrat différent (« execution = proposition », `set_evolution_interne`/I-200) sans rapport avec XP macro ou cap secret.
**Détail** : aucun module ne calcule d'XP à cadence macro, aucun cap secret par trait, aucune notion d'objectif auto-fixé récompensé. `evolution_interne` (I-200) est une brique voisine mais distincte.
**Recommandation** : garder.

### #99 — FICHE — Le carnet d'enquête
**Verdict** : VIVANT
**Preuve** : aucune correspondance trouvée — `grep -rli "carnet"` ne remonte que des fixtures narratives (`tests/test-ecrivain-module-i143.py:37,52`, `tests/test-retour2-conformite-i139.py:25`) où « carnet » est un objet de fiction, sans rapport avec un réceptacle de traces d'enquête.
**Détail** : aucun objet séparé « carnet d'enquête » n'existe, aucun routage vers un tel réceptacle, aucun lecteur nommé. Le trou N5 reste entier faute même d'un carnet à lire.
**Recommandation** : garder.

### #100 — FICHE — Les gardes de secret (transverse)
**Verdict** : PARTIEL
**Preuve** : `coderain/validator.py::scan_hidden_forced` + `docs/gabarit-autorat-secrets-i159.md` + `mcp_server.py::_lore_warnings` (appelé à chaque `load_save`) + `tests/test-garde-secrets-i159.py`.
**Détail** : la détection `pinned/critical` sur entrées `hidden` est construite et testée (item ii — audit I-159 passe) mais reste un avertissement au chargement, jamais un blocage. La règle n'est PAS dans le gabarit rempli par l'adaptateur (item i, aucune trace dans `coderain/converter/`), et aucun grep anti-fuite permanent en suite continue n'a été localisé (item iii, au-delà du test ciblé i159).
**Recommandation** : requalifier — fermer (ii) avec pointeur `docs/gabarit-autorat-secrets-i159.md` + `coderain/validator.py::scan_hidden_forced` ; garder (i) gabarit adaptateur et (iii) grep anti-fuite permanent.

### #101 — FICHE — Le test d'élément
**Verdict** : CONSTRUIT
**Preuve** : `specs/moule-test-element-i382.md`, `tests/fixtures/element_mold.py` (`ElementMold`), `tests/test-element-camera.py` (premier exemplaire), `README-moule-test-element.md`.
**Détail** : le moule générique existe exactement comme décrit (brique visée, fixtures, scénario réduit, compteurs `check()`, borne de coût), et un premier exemplaire tourne réellement sur la caméra — l'une des deux candidates citées par la fiche.
**Recommandation** : fermer avec pointeur (`specs/moule-test-element-i382.md`, `tests/fixtures/element_mold.py`, `tests/test-element-camera.py`).

### #102 — FICHE CHANTIER — La biographie du personnage
**Verdict** : PARTIEL
**Preuve** : `docs/verification-campagne-md-d186.md` (§3, « ÉCART STRUCTUREL ») + `coderain/campagne.py` (champs, `render()`/`load()`, `set_statut()`) + `tests/test-evolution-interne-i200.py` + `mcp_server.py::set_evolution_interne`/`journal2vecteur`.
**Détail** : format/support `campagne.md` (D-186) et mécanique `evolution_interne` (I-200) sont livrés et testés. Mais le rapport de vérification établit que rien n'appelle jamais `campagne.save_file()`/`render()` en production — le geste d'écriture de l'Auteur, distinct de la matière, n'existe pas.
**Recommandation** : requalifier — fermer la partie support/I-200 avec pointeur `docs/verification-campagne-md-d186.md` + `coderain/campagne.py` ; rouvrir spécifiquement le geste d'écriture de l'Auteur.

### #103 — FICHE CHANTIER — La garde anti-rail de l'Auteur
**Verdict** : PARTIEL
**Preuve** : `coderain/acte.py` (trois lectures remplissage/divergence/raccord, contrainte « états et potentiels, JAMAIS une séquence ») ; `coderain/ecrivain_module.py:5,74-82` (cas 2/3 de D-117) ; `coderain/retour2.py` (raccord retour 2).
**Détail** : la forme opposable de D-065 est injectée en prompt dans `acte.py` et `ecrivain_module.py`, et les cas 2/3 de D-117 sont câblés. Mais il n'existe aucun valideur MÉCANIQUE (« un valideur refuse toute sortie posant un événement futur non conditionné ») — la contrainte reste au niveau du prompt.
**Recommandation** : requalifier — créditer `coderain/acte.py` + `coderain/ecrivain_module.py` pour la forme D-065/D-117 ; garder ouvert le valideur mécanique anti-rail.

### #104 — FICHE CHANTIER — Le tableau de bord du dispositif
**Verdict** : VIVANT
**Preuve** : `coderain/campagne.py:34-36` (`SEUIL_AVENTURES`, signal I-186) et `rapport()` — seul embryon trouvé ; aucun fichier de dispositif, aucun cadran de dérive contre `ambition_finale`, aucun regroupement des compteurs D-096/D-098/D-097/D-113/I-183.
**Détail** : `campagne.py::rapport()` produit un unique compteur signal, mais ce n'est ni un fichier de dispositif distinct du save, ni le cadran de dérive demandé, ni une consolidation des compteurs.
**Recommandation** : garder.

### #105 — FICHE CHANTIER — Le valideur de spécification
**Verdict** : PARTIEL
**Preuve** : `coderain/converter/validate_form.py` (dangling links, orphan records, secret leak, doublons d'ids) ; `coderain/memory.py:1181-1183` (`delay` géré côté moteur). Aucune fonction classant les portes `delay:`/déclencheurs en « posée ⊥ effective ».
**Détail** : un valideur de spécification existe et couvre plusieurs invariants structurels (niveau 1 SPEC-P4). Le geste central — classer chaque porte temporelle posée vs effectivement appliquée, avec fixtures — n'a pas de fonction dédiée ; la mesure du rayon sur le catalogue (I-193) n'a pas été faite.
**Recommandation** : requalifier — créditer `validate_form.py` comme valideur de forme existant ; garder ouvert « portes posées ⊥ effectives » + mesure du rayon.

### #106 — FICHE CHANTIER — Le joueur-banc (régime ascendant)
**Verdict** : VIVANT
**Preuve** : aucune correspondance trouvée — `grep -rli "joueur-banc|joueur_banc|I-1637"` : zéro résultat. `tests/fixtures/ci_boutenbout.py` et `docs/mesure-d260-boucle-neuve.md` couvrent le convertisseur hors-ligne et une mesure de tokens, pas un agent-joueur.
**Détail** : aucun agent-instrument jouant une campagne sacrificielle n'existe, ni persona/intentions v1, ni tableau de verdict mécanique dédié.
**Recommandation** : garder.

---

## Items #108-#123

*(16 issues ouvertes dans cette plage, pas 14 — voir note en tête de document.)*

### #108 — Contractualiser le retrait des secrets côté director-pipeline
**Verdict** : VIVANT
**Preuve** : `coderain/modules/trinity.py:197-211` (`_direct`) construit `director_msgs` (avec `event_rules`) en variable locale, jamais réinjectée dans `messages` ; `_writer_messages` (lignes 244-249) reçoit `messages` non modifié. `tests/trinity_test.py` ne teste que l'ordre des étapes, aucune assertion sur `event_rules_block` côté Writer.
**Détail** : le comportement tient toujours par accident de portée de variable, comme décrit. Aucun refactor ni test de garde symétrique côté pipeline.
**Recommandation** : garder.

### #109 — Créer docs/CHEMINS.md
**Verdict** : VIVANT
**Preuve** : `docs/CHEMINS.md` n'existe pas (liste complète des 41 fichiers de `docs/` vérifiée) ; seul `tests/test-chemins-morts-i375.py` matche partiellement le nom, sans rapport.
**Détail** : le travail demandé reste entièrement à faire.
**Recommandation** : garder.

### #110 — Snapshot automatique des saves à l'ouverture de partie
**Verdict** : PARTIEL
**Preuve** : `mcp_server.py:433-446` (`save_snapshot`, outil MCP manuel via `saves.duplicate`) ; `mcp_server.py:373-419` (`load_save`) ne l'appelle jamais automatiquement.
**Détail** : la brique de bas niveau demandée (copie datée, par-dessus le système existant) existe déjà en manuel. Ce qui manque précisément est l'automatisation à l'ouverture de partie.
**Recommandation** : requalifier — recentrer sur « appeler `save_snapshot` automatiquement dans `load_save` », le mécanisme sous-jacent étant déjà là.

### #111 — D-202 : endpoint patches/ manquant
**Verdict** : VIVANT
**Preuve** : `coderain/converter/emit.py:242-247` confirme l'émission du dossier `patches/`. Grep `patches` sur `docs/*.md` → mentions indirectes seulement (`docs/audit-completude-buckets-d249.md:49`, `docs/ingestion-dks-analyse.md:85,118`), aucune ne documente explicitement le constat. Aucun `docs/ARCHITECTURE.md` n'existe.
**Détail** : le constat technique (émission sans lecteur) est exact, mais le livrable documentaire demandé n'existe nulle part.
**Recommandation** : garder.

### #112 — I-146 : gating inachevé
**Verdict** : VIVANT
**Preuve** : `coderain/memory.py:26-29` (`GATED_REGISTRIES`, exactement les 5 fichiers cités) ; `mcp_server.py:1196-1197` (`_wide_history` sur `threads.md`, filtre statut seul, pas de filtre déclencheur/lieu) ; `coderain/memory.py:1427-1431` (`world-bible.md` lu en bloc) ; `coderain/templates.py:276` annonce toujours un gating contredit par le code.
**Détail** : tous les faits cités par l'issue sont vérifiés au caractère près dans le code actuel.
**Recommandation** : garder.

### #113 — I-173 : réglage effort du Director
**Verdict** : VIVANT
**Preuve** : aucun dossier `.claude/agents`/`director.md` dans ce dépôt ; `docs/mesure-i158-director-deux-corps.md` mentionne `effort: xhigh` comme donnée mesurée mais aucun protocole comparatif low/max exécuté.
**Détail** : le doute reste entier, aucun test comparatif n'a été mené.
**Recommandation** : garder.

### #114 — I-183 : le fold coupe par compteur
**Verdict** : VIVANT
**Preuve** : `coderain/summarizer.py:127,130,419,423` (`medium_after`/`medium_size`, coupe par compteur sans signal de lieu/jour). Aucun script de mesure trouvé.
**Détail** : le fait vérifié est exact et inchangé ; la mesure gratuite demandée n'a pas été produite.
**Recommandation** : garder.

### #115 — I-188 : aucun verrou de save
**Verdict** : VIVANT
**Preuve** : grep exhaustif de `lock` sur `mcp_server.py`, `coderain/config.py`, `coderain/memory.py` → aucun mécanisme de verrouillage de save ; `load_save` (`mcp_server.py:373-419`) écrase l'état global sans détection de chargement concurrent.
**Détail** : le constat de l'issue est confirmé au code près.
**Recommandation** : garder.

### #116 — I-190 : latence jamais mesurée
**Verdict** : VIVANT
**Preuve** : `docs/mesure-i158-director-deux-corps.md` et `docs/mesure-d260-boucle-neuve.md` mesurent des tokens, jamais une latence en secondes ; le premier document dit explicitement ne pas permettre de dire le coût réel en latence. Aucun `time.time()`/`perf_counter` trouvé en rapport.
**Détail** : l'estimation 7-20s/tour n'a toujours reçu aucune confrontation chronométrique réelle.
**Recommandation** : garder.

### #117 — I-204 : le fold d'arc avance son compteur même sans écrire
**Verdict** : VIVANT
**Preuve** : `coderain/summarizer.py:400-409` (`_fold_arc` retourne `[]` sans écrire en cas d'échec) et `:433-446` (`maybe_fold` avance le compteur inconditionnellement).
**Détail** : le code correspond exactement à la description ; aucune correction appliquée.
**Recommandation** : garder.

### #118 — I-206 : troncature à 12 fiches non triée
**Verdict** : VIVANT
**Preuve** : `coderain/summarizer.py:96-100` (commentaire du code lui-même : « NOT ranked by importance before the cut ») et `:264-278` (`_existing_context`, coupe sans tri).
**Détail** : le code confirme précisément le mécanisme et documente lui-même le manque comme non résolu.
**Recommandation** : garder.

### #119 — I-222 : migration amont non revérifiée
**Verdict** : VIVANT
**Preuve** : aucune correspondance — aucun fichier `docs/` ne traite de migration amont/69 commits ; `git log` ne montre aucun commit pertinent.
**Détail** : aucune revérification depuis la mesure du 07/08 citée par l'issue.
**Recommandation** : garder.

### #120 — I-226 : fabrique de situations de test
**Verdict** : VIVANT
**Preuve** : `tests/fixtures/element_mold.py` + `README-moule-test-element.md` fournissent un harnais de verdicts (présent/absent), pas une fabrique construisant un save depuis une description texte. Les primitives (`duplicate`, `save_snapshot`, `import_card`) existent, comme l'issue elle-même le documentait déjà.
**Détail** : rien de nouveau n'a été construit au-delà de ce que l'issue documentait déjà comme socle partiel.
**Recommandation** : garder.

### #121 — I-270 : trinity_test échoue sur environnement
**Verdict** : PARTIEL
**Preuve** : `tests/trinity_test.py:179-198` + commit `b56206d` (« trinity_test déclare lui-même le profil openrouter, hermétique — suite 42/42 verte x2 ») ; `python tests/trinity_test.py` passe réellement. Mais `.github/workflows/ci.yml:21-33` skip encore explicitement `trinity_test.py` en nommant I-270.
**Détail** : le test lui-même est réparé et passe. Le skip CI n'a pas été retiré comme demandé par l'issue.
**Recommandation** : requalifier — rouvrir uniquement le volet CI (retirer le skip de `.github/workflows/ci.yml` citant I-270), la réparation de fond étant déjà faite en `b56206d`. **Note** : CLAUDE.md du repo mentionne toujours `trinity_test.py` comme « exclu, échec préexistant documenté » — à mettre à jour en cohérence si le skip est retiré.

### #122 — I-385 : caractères shell dans le corps d'une issue
**Verdict** : VIVANT
**Preuve** : `tools/lancer-lane.ps1:369-455,602` (`Build-LanePrompt` injecte `$Body` verbatim dans un here-string, puis `$promptText` est passé tel quel à l'exécutable). Aucun `Replace`/`Escape` sur le corps de l'issue. Aucun commit postérieur au 28/08 traitant de l'échappement.
**Détail** : le mécanisme décrit n'a reçu aucun correctif.
**Recommandation** : garder.

### #123 — I-386 : la sonnette SendMessage échoue vers la session tour
**Verdict** : VIVANT
**Preuve** : aucune correspondance — `CLAUDE.md` ne mentionne ni `SendMessage` ni `I-386` ; `hooks/` ne contient que `pre-commit`/`pre-push` ; `tools/lancer-lane.ps1` conserve `-SessionTour` et la logique de sonnette telle qu'avant l'incident.
**Détail** : aucun des deux tests de harnais demandés n'a été exécuté ni documenté.
**Recommandation** : garder.

---

## Notes transverses pour le mainteneur

- **Fermetures directes candidates** (contrat vérifié construit et testé, geste de fermeture sur pièces) : #86, #87, #88, #89, #101.
- **Requalifications** (moitié construite à documenter/fermer, moitié à garder réduite) : #85, #90, #91, #92, #93, #94, #95, #96, #100, #102, #103, #105, #110, #121.
- **Un PÉRIMÉ** : #97 cite une dépendance (`author.py` livré) qui ne correspond plus à l'organe réellement livré sous ce nom (détecteur de répétition I-229, pas horloges d'entre-deux) — la fiche elle-même reste valide, seule sa note de dépendance est à corriger.
- Aucune fermeture, aucun label n'a été posé par cette lane — geste réservé au mainteneur.
