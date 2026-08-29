# Mesure I-158 — le Director en deux corps (director-pipeline vs director-de-table, D-258)

*Mesure pure (Issue #84) : aucune modification de code, aucune optimisation.
Les écarts constatés se consignent, ils ne se corrigent pas. Rapport expurgé :
aucun extrait de fiction, aucun nom propre de campagne — uniquement des
tailles agrégées (caractères, sections, comptages).*

**Régime mesuré : TOUR uniquement** (D-096). Le régime ÉDITORIAL (projet de
campagne entier, appliqué à `world-bible.md`/`premise.md` en amont de la
partie) n'est déclenché par aucun des deux corps au sens de cette mesure — il
ne se confond avec rien ci-dessous.

## Méthode

- **Conversion tokens** : 1 token ≈ 4 caractères — convention déjà en usage
  dans `coderain/memory.py:1309,1544` (`budget_tokens * 4`), réutilisée ici
  pour rester cohérent avec le code mesuré plutôt que d'introduire un second
  ratio.
- **Corps 1 (director-pipeline)** : mesuré en importation directe de
  `coderain.memory.MemoryStore` et `coderain.modules.trinity` dans ce repo
  (`coderain/modules/trinity.py`, `coderain/engine.py`), sur le save réel
  `planescape-vahn` du dépôt privé `ttrpg-corpus` (17 tours, mode RPG actif,
  22 règles d'événement, 8 scènes repliées, 15 fils ouverts, 25 faits) —
  lecture seule, script jetable en scratchpad, aucun octet de ce save copié
  dans ce document.
- **Corps 2 (director-de-table)** : mesuré sur les fichiers de dispositif du
  dossier `C:\Vaults\MVP2\jeu-planescape\.claude\` (agents, skills) — mêmes
  outils MCP mesurés côté code dans `mcp_server.py` (docstrings déjà
  chiffrées par une mesure antérieure sur CE MÊME save : `event_rules_block()`
  = 20 060 chars mesuré ici et 20 060 chars cité dans la docstring de
  `assemble_context_to_file`, confirmation croisée que `planescape-vahn` est
  la campagne réellement servie par le pont MCP).
- **Trou constaté (BLOQUÉ, voir fin de document)** : zéro transcript réel du
  corps 1. `trinity_brain` n'a jamais tourné sur `planescape-vahn` — ce save a
  toujours été joué par le corps 2 (dossier `.claude`, boucle `/jouer`). Le
  corps 1 est donc mesuré sur ce qu'il RECEVRAIT (assemblage réel + prompts
  réels, calcul déterministe) mais aucun coût de tour réellement encouru
  n'existe à relire.

## 1. Ce que chaque corps reçoit par tour

### Corps 1 — DIRECTOR-PIPELINE (`trinity.py::_direct`)

Le Director reçoit `messages[0]["content"]` = sortie de
`store.assemble(history, player_input, scenes_tail=4, budget_tokens=<budget
config>)` (Memory Manager, code-first, déterministe) + `DIRECTOR_SYS` (préfixé
en système) + `event_rules_block()` (Director-only en mode Quad, ajouté par
`engine.py:582-584`).

| Composant | Mesuré | Chars | ~Tokens |
|---|---|---:|---:|
| `store.assemble()`, budget=8000 (config défaut `context_budget_tokens`) | réel, save `planescape-vahn` | 52 589 | 13 147 |
| — dont bloc « Règles de narration » (writer-rules.md) | réel | 20 784 | 5 196 |
| — dont « STORY & MEMORY CONTEXT » (premise/monde/fils/arc/faits/scènes/timeline/lore activé) | réel | 31 804 | 7 951 |
| `store.assemble()`, budget=120000 (plafond MCP par défaut) | réel | 103 448 | 25 862 |
| `DIRECTOR_SYS % _ENV_WORLD` (schéma sans RPG) | statique, ce repo | 2 885 | 721 |
| `DIRECTOR_SYS % _ENV_RPG` (schéma RPG) | statique, ce repo | 3 661 | 915 |
| `event_rules_block()` (Director-only) | réel | 20 060 | 5 015 |
| character sheet (`rpg_mod.context_block`, `prompt_narrate=False`) — ajouté par `_augment_rpg`, avant le split Director/Writer | réel | 1 007 | 251 |

**Total reçu par le Director, un tour typique (budget config=8000, RPG on)** :
`store.assemble` (52 589) + `DIRECTOR_SYS` RPG-tail (3 661) + `event_rules_block`
(20 060) + character sheet (1 007) ≈ **77 317 chars ≈ 19 329 tokens**, avant
l'historique verbatim inclus dans `store.assemble` lui-même (le bloc « STORY &
MEMORY CONTEXT » ci-dessus le porte déjà — pas de double-compte).

Composition par catégorie (sur les 19 329 tokens) : état+lore+historique
≈ 68 %, règles d'écriture de la campagne ≈ 27 %, règles d'événement (secret,
Director-only) ≈ 26 %*(chevauche les 68 % ci-dessus car `event_rules_block`
est HORS `store.assemble` — additif, pas soustrait de lui)*, fiche perso ≈ 1 %,
instructions système du rôle ≈ 5 %.

### Corps 2 — DIRECTOR-DE-TABLE (sous-agent `director`, dossier `.claude`)

Le Director reçoit, PAR APPEL DE SOUS-AGENT (contexte frais à chaque tour,
voir §4) : son propre prompt système (`director.md`) + l'action du joueur
verbatim (quelques dizaines de tokens) + tout ce que ses appels d'outils MCP
lui rapportent EN COURS DE TOUR (séquentiel, pas prééassemblé) :

| Composant | Mesuré | Chars | ~Tokens |
|---|---|---:|---:|
| `director.md` (prompt système du sous-agent) | statique, vault | 11 960 | 2 990 |
| `get_world_state()` — JSON état (temps, lieu, flags, quêtes, PV, inventaire) | non mesuré (JSON compact, save-dépendant) | — | — |
| `get_event_rules()` = `event_rules_block()` | réel, même donnée que corps 1 | 20 060 | 5 015 |
| `context_candidates()` — rapport candidats lore (métadonnées seules : slug/titre/taille) | non mesuré directement ; `assemble_context` (dont ce rapport dérive) sert 103 blocs de lore sur ce save (docstring `mcp_server.py`) | — | — |
| `documentaliste` (sous-agent, si appelé) — retour uniquement, un `FAIT`+`ANCRAGE` par question, questions batchées | 3 470 chars de prompt propre + retour court | 3 470 | 867 |
| `derivateur` (sous-agent, rare — signal d'accumulation seulement) | prompt propre | 3 927 | 981 |

Le sous-agent `director` NE reçoit JAMAIS `assemble_context`/
`assemble_context_to_file` dans SA PROPRE fenêtre — il en reçoit seulement le
CHEMIN (`{path, chars}`) et ne lit pas le fichier (consigne explicite,
`director.md` étape 8c : « Ne lis JAMAIS ce fichier »). Ce fichier
(14 951–162 000 chars selon la scène, mesures antérieures de `mcp_server.py`)
est destiné exclusivement au narrateur (orchestrateur), pas au Director.

### Comparaison directe — ce que chaque corps voit

| | Corps 1 (pipeline) | Corps 2 (table) |
|---|---|---|
| Contexte d'état+lore+historique | pré-assemblé, dans SA fenêtre (52–103 k chars) | jamais dans sa fenêtre — délégué au fichier narrateur |
| Règles d'événement (secret) | dans sa fenêtre (20 060 chars) | dans sa fenêtre (20 060 chars, même donnée) |
| Recherche de faits manquants | aucune — le contexte est fixe, assemblé sans jugement du Director | `recall_entity`/`recall_quest` direct, ou sous-agent `documentaliste` — jugement actif |
| Tranchage du lore servi au narrateur | aucun (le Writer reçoit le MÊME contexte que le Director, voir §2) | actif — `context_candidates` + choix de slugs (`lore_include`) |

## 2. Ce que chaque corps décide

### Corps 1

Sortie STRICTEMENT contrainte : un objet JSON unique
(`beat_plan`, `must_stay_consistent`, `recall_queries`, `envelope{v:1,
check?, deltas}`), zéro appel d'outil, zéro écriture disque. Le jugement
mécanique est **un seul acte par tour** : produire cette enveloppe (plus,
optionnellement, une correction sur re-ask si le validateur rejette des
deltas — `_redirect`, un second appel borné). Sortie estimée (gabarit rempli
minimal) : schéma RPG brut = 968 chars ≈ 242 tokens ; en pratique le
`beat_plan` (1-3 phrases) + `must_stay_consistent` + `recall_queries` ajoutent
quelques centaines de tokens de plus — sortie totale typique de l'ordre de
**300 à 600 tokens**.

Point structurel mesuré : **le Writer (Narrator) du pipeline reçoit le
MÊME `messages` que le Director** (`trinity.py::_writer_messages` part de
`messages` inchangé, juste augmenté de la directive du plan) — sans le retrait
d'`event_rules_block` ni de section « secrets » que le corps 2 applique
explicitement (`assemble_context_to_file` défauts `event_rules=False,
secrets=False`, documenté comme « décision d'auteur », `mcp_server.py:1580-
1602`). Le pipeline n'a **pas** cette étape de retrait — aucune preuve dans le
code que le Writer du pipeline est privé des règles d'événement ou des
secrets que le Director a vus (il reçoit `messages[0]` construit AVANT
l'ajout de `event_rules_block`, donc IL NE LES REÇOIT PAS non plus — mais pas
par un geste de retrait délibéré, simplement parce qu'`event_rules_block` est
concaténé uniquement dans `director_msgs`, une COPIE locale à `_direct`,
jamais réinjectée dans `messages`). Le secret n'est donc PAS structurellement
gardé côté pipeline de la même façon que côté table (où le retrait est un
paramètre nommé, testé, avec compteur `secrets_suppressed`) — côté pipeline,
c'est un effet de bord de la portée de la variable Python, non un contrat
déclaré.

### Corps 2

Sortie = actions d'outils séquentielles (jusqu'à 9 outils listés en
frontmatter : `get_world_state`, `get_event_rules`, `context_candidates`,
`assemble_context_to_file`, `recall_entity`, `recall_quest`, `recall_turns`,
`fold_due`, `fold_apply`, `validate_envelope`, `apply_envelope`, `Read`,
`Write`, `Agent`) + délégations (`documentaliste`, `derivateur`, `resumeur`) +
UNE écriture disque finale (`briefing.md`) + une réponse de DEUX lignes
(`BRIEFING:`, `ETAT:`). Le jugement mécanique se répartit sur **plusieurs
décisions explicites par tour** : quels faits chercher (et par quelle route —
directe ou `documentaliste`), l'enveloppe, le tranchage du lore
(`context_candidates` → choix de slugs → `lore_include`), la génération de
l'Angle (perception du personnage, jamais pré-écrite), et — hors tour normal
— le repliement de mémoire quand `fold_due`. C'est un jugement PLUS RICHE et
PLUS DISTRIBUÉ que celui du corps 1 : la sélection de lore et la conversion
« monde → perception » (la Caméra) n'ont aucun équivalent dans
`DIRECTOR_SYS` — le pipeline ne trie pas le lore, il le reçoit déjà tranché
par le budget déterministe de `store.assemble` (poids × importance, pas de
lecture de scène).

## 3. Coût par tour

| | Corps 1 (pipeline) | Corps 2 (table) |
|---|---|---|
| Appels LLM séquentiels obligatoires | Director (1) → [Lore-keeper (0 ou 1, opt-in `llm_pass`)] → Writer (1) = **2 à 3** | sous-agent `director` (1, contient N appels d'outils séquentiels internes) → narration de l'orchestrateur (1, dans la session persistante) = **2 "tours de génération"**, mais le premier est un agent complet (plusieurs allers-retours outil, effort `xhigh`) |
| Appels outils/MCP séquentiels dans un seul appel de génération | 0 (le Memory Manager est du code appelé AVANT le LLM, pas par le LLM) | jusqu'à 8-9 dans un tour ordinaire : `get_world_state`, `get_event_rules`, [`recall_*` ou sous-agent `documentaliste`], `context_candidates`, `assemble_context_to_file`, [`validate_envelope`], `apply_envelope`, `Write` — chacun un aller-retour réseau vers le serveur MCP |
| Sous-agents additionnels | aucun (architecture mono-processus) | `documentaliste` (conditionnel, une ou plusieurs questions batchées), `derivateur` (rare, signal d'accumulation), `resumeur` (seulement si `fold_due`) — chacun une fenêtre fraîche, son propre prompt (867/981/827 tokens) |
| Cache 5 minutes (prompt caching) | **non applicable structurellement** : `LLM` (`coderain/llm.py`) est un client HTTP générique compatible OpenAI (`base_url`/`model`/`api_key`), pas nécessairement un provider avec cache — aucun mécanisme de cache dans ce code | applicable EN PRINCIPE (sous-agents Claude via Task/Agent SDK, potentiellement Claude API avec cache) — **non vérifiable depuis ce repo** : le cache dépend du modèle configuré (`director.md` frontmatter : `model: claude-opus-5`, un modèle Anthropic — le seul point où la question a un sens) et d'un rythme de jeu (un tour prend plusieurs minutes de dialogue humain, potentiellement > 5 min entre deux lancements du sous-agent `director` — auquel cas le cache expire structurellement à CHAQUE tour) |
| Latence structurelle (chemin séquentiel obligatoire) | Director LLM → validateur (code, ~instantané) → [re-ask si rejet] → Writer LLM = 2 générations LLM en série minimum, aucun retour utilisateur avant la fin | `ui_wait` (bloquant, jusqu'à 5 min, coût humain pas machine) → sous-agent `director` (série de ~8 appels réseau + 1 génération LLM `effort: xhigh`, le plus coûteux en latence des deux corps) → lecture de 2 fichiers par l'orchestrateur → génération de la prose (1 appel LLM) |
| Tokens de sortie du rôle Director lui-même | ≈ 300-600 (JSON compact, §2) | non chiffrable en tokens de MODÈLE depuis ce dossier — le sous-agent produit potentiellement des dizaines de milliers de tokens de RAISONNEMENT (`effort: xhigh`) avant ses 2 lignes de réponse finale ; ce raisonnement n'est PAS visible dans le vault (interne au provider) |

## 4. Accumulation — fenêtre qui grossit ou repart à neuf

### Corps 1 — repart frais, mesuré déterministe

Chaque appel `TrinityBrain.generate()` reconstruit `messages` à partir de
`store.assemble()` (Memory Manager code-first). Il n'y a **aucune mémoire de
conversation LLM** entre deux tours côté Director : le contexte de l'
appel N+1 ne contient pas les productions JSON de l'appel N (sauf ce qui a été
committé dans le store — deltas appliqués, tours ajoutés au transcript, donc
RÉ-ENTRE via `store.assemble` sous forme de faits/scènes, pas de raisonnement
brut). C'est un régime **« repart frais, coût constant par tour »** : le
budget `store.assemble` (8000 tokens config, mesuré ici à 13 147 tokens
effectifs — dépassement du budget nominal déjà visible sur ce save à 17
tours, cf. §5) ne croît pas mécaniquement avec le nombre de tours — il
plafonne, l'activation lorebook change quels blocs entrent, pas leur volume
total.

**Coût sur 10 tours simulés (budget=8000, hypothèse : volume par tour
stable au niveau mesuré ici)** :
- Entrée Director : 10 × 19 329 tokens ≈ **193 290 tokens** cumulés (mais
  chaque tour est un appel INDÉPENDANT — pas une fenêtre qui grossit, un
  compteur d'API additif)
- Sortie Director : 10 × ~450 tokens (milieu de fourchette) ≈ **4 500 tokens**
- Total pipeline (Director seul, hors Writer) ≈ **197 790 tokens sur 10 tours**,
  soit ~19 779 tokens/tour en moyenne, CONSTANT tour après tour (pas de
  dérive : aucune fenêtre unique ne grandit).

### Corps 2 — deux régimes d'accumulation superposés, pas un seul

- **Le sous-agent `director` repart frais à CHAQUE tour** — même régime que
  le corps 1 pour lui-même (context_candidates + assemble sont recalculés,
  aucune mémoire du Director d'un tour au suivant sauf ce que le moteur a
  committé). Coût par invocation dominé par `director.md` (2 990 tokens fixes)
  + `event_rules_block` (5 015 tokens fixes) + retours d'outils MCP
  (variables, non chiffrés depuis ce repo — dépend du JSON de
  `get_world_state` et du nombre de candidats lore).
- **L'orchestrateur (narrateur) NE REPART JAMAIS À NEUF** — `/jouer` skill,
  §300 : « Cette conversation EST ta mémoire de la partie ». C'est une
  session PERSISTANTE : chaque tour AJOUTE (narration précédente + briefing lu
  + fichier contexte lu, potentiellement 565 à 162 000 chars selon la scène,
  mesure antérieure `mcp_server.py`) à une fenêtre qui NE SE VIDE JAMAIS
  jusqu'à relance manuelle. Le skill documente lui-même le seuil : « au-delà
  de 50-60 %, on relance » (règle de Souhel, §280 du skill) — preuve que ce
  régime SATURE et que la limite est gérée par une consigne humaine, pas par
  le code.

**Coût sur 10 tours simulés, corps 2** :
- Sous-agent `director` : 10 invocations indépendantes, ~régime constant comme
  le corps 1 (pas de fenêtre cumulative pour LUI) — mais chacune contient une
  séquence d'outils (latence, pas volume de tokens fixe mesurable ici).
- Orchestrateur/narrateur : fenêtre qui CROÎT tour après tour — si chaque
  narration + lecture de briefing+contexte ajoute, au bas mot, l'ordre de
  grandeur mesuré côté fichier-contexte narrateur (14 951 à 162 000 chars sur
  les mesures antérieures, soit ~3 700 à 40 500 tokens PAR TOUR ajoutés à LA
  MÊME fenêtre), 10 tours peuvent faire passer cette fenêtre de 0 à
  **37 000-405 000 tokens accumulés**, selon le régime (« contexte dégradé »
  ou plein) — c'est justement l'écart que la consigne « 50-60 % puis relance »
  existe pour couper avant qu'il ne se referme sur lui-même.

**Ce que ces deux chiffres permettent de dire, et ce qu'ils ne permettent
pas** : le corps 1 a un coût par tour CONSTANT et un coût sur 10 tours
strictement additif (pas de compounding). Le corps 2 a un sous-organe
(Director) au même régime que le corps 1, mais son organe de narration
accumule structurellement — la saturation de fenêtre qui touche le corps 2
n'a AUCUN équivalent dans le corps 1, dont l'architecture n'a pas de
fenêtre de conversation à saturer (chaque appel LLM est isolé). Ce que ces
chiffres NE permettent PAS de dire : le coût RÉEL en tokens/latence/argent
d'un tour de corps 2, faute de transcript réel à relire (voir §5) — les
volumes ci-dessus sont des BORNES tirées de mesures antérieures sur le
FICHIER-CONTEXTE, pas des comptages de tokens de facturation.

## 5. Les trois pressions contradictoires (D-258)

- **Grossir** : le Director reçoit ce qu'on retire au narrateur — mesuré :
  côté corps 2, `assemble_context_to_file` retire délibérément 2 blocs
  (`event_rules`, `secrets`) au narrateur ; le Director les récupère par
  `get_event_rules()` (5 015 tokens) — un mouvement de retrait-report
  explicite. Côté corps 1, ce mouvement n'existe pas comme contrat déclaré
  (§2) : le Writer ne les reçoit simplement jamais, par portée de variable,
  pas par une politique documentée équivalente.
- **Rester mince** : le Director est le poste le plus cher structurellement
  des deux corps — côté 1, seul rôle à porter `event_rules_block` EN PLUS du
  contexte complet (19 329 tokens mesurés vs le Writer qui reçoit le
  contexte SANS cet ajout) ; côté 2, seul rôle en `effort: xhigh` (Opus) avec
  la chaîne d'outils la plus longue (jusqu'à 9 outils listés).
- **Accumuler** : côté 2, mesuré au §4 — l'orchestrateur accumule
  structurellement, le sous-agent Director non. Côté 1, AUCUN organe
  n'accumule (chaque appel est isolé) — ce qui déplace la question ailleurs :
  le pipeline n'a pas de pression d'accumulation à arbitrer, mais il n'a pas
  non plus de mémoire de raisonnement d'un tour à l'autre au-delà de ce que
  `store.assemble` recharge.

## 6. Trous mesurés (BLOQUÉ — à consigner, pas à combler)

- **Zéro transcript réel du corps 1** sur une vraie partie — `trinity_brain`
  n'a jamais tourné sur `planescape-vahn` (seul save réel disponible dans
  `ttrpg-corpus`, avec `beyond-the-vale-of-madness` non inspecté ici faute de
  signal qu'il diffère). Les chiffres du corps 1 sont donc des mesures de CE
  QU'IL RECEVRAIT (calcul déterministe rejoué sur un save réel), pas des
  mesures de ce qu'il A REÇU en jeu.
- **`rpg-rules.md` mesuré à 0 chars** sur ce save alors que `rpg_enabled() ==
  True` — soit ce fichier n'existe pas pour ce save (règles RPG portées
  autrement, non retrouvé dans ce repo ni dans `ttrpg-corpus`), soit la
  résolution de chemin (`instructions_dir` global) n'a pas été atteinte
  correctement par ce script de mesure lecture-seule. Non creusé davantage
  (hors périmètre d'une mesure : ne pas corriger un dispositif en le
  mesurant) — le chiffre « fiche perso 251 tokens » du §1 est donc un
  PLANCHER, pas un total.
- **Tokens de sortie et de raisonnement interne du sous-agent `director`**
  (corps 2) non chiffrables depuis ce dossier : le compteur de tokens réel
  d'un appel Claude (`effort: xhigh`, raisonnement inclus) n'est pas exposé
  dans le vault — seules les tailles de PROMPT (statiques, mesurées) et de
  FICHIERS produits (mesures antérieures documentées dans le code) le sont.
- **Applicabilité réelle du cache 5 minutes** au sous-agent `director` : pas
  vérifiable depuis ce repo (dépend du rythme de jeu humain et de
  l'implémentation du provider, hors du code lisible ici).

## Conclusion (trois lignes)

1. Coût par tour comparable en volume reçu (~19 300 tokens côté pipeline,
   ordre de grandeur voisin ou supérieur côté table) mais régime opposé :
   pipeline = jugement resserré (une enveloppe JSON, coût constant, aucune
   fenêtre à saturer) ; table = jugement distribué (tranchage du lore, Angle,
   repliement) avec un Director qui repart frais mais un orchestrateur qui
   accumule jusqu'à relance manuelle — la pression « accumulation » n'existe
   QUE côté table.
2. La garde secrets/règles d'événement au Writer est un CONTRAT DÉCLARÉ côté
   table (paramètres nommés, testés, `secrets_suppressed`) contre un EFFET DE
   PORTÉE Python non déclaré côté pipeline (§2) — même résultat apparent,
   garanties différentes.
3. Ce que ça laisse ouvert : le coût réel tokens/latence/argent d'un tour de
   table (zéro transcript réel à relire, §5/§6) et si l'écart de contrat sur
   le pipeline est voulu ou un angle mort — cette mesure les rend visibles,
   elle ne les tranche pas.
