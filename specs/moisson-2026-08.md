# Moisson 2026-08 — fiches de la boucle à convertir en Issues GitHub

*Produit en phase 0 du gel de la boucle (`boucle/veilleur.ps1`, définitivement éteinte). Recense les fiches de travail encore ouvertes dans `C:\Vaults\MVP2\Migration Coderain\` au 2026-08-28, pour matière à création d'Issues GitHub en phase 1 (repo `coderain`, une fois `gh` en place). Aucune Issue n'est créée par ce document — c'est une liste de conversion.*

Source : `meta-rpg/etat-boucle.md` (10 fiches « lançables en attente ») + `veilleur-state.json` (8 fiches dans `fichesBannies` au moment du gel — cf. `MRPG-I-1622` : le compteur d'échecs de la boucle bannissait des fiches saines sur deux bugs machine, pas sur un défaut du travail proposé). Vérification croisée faite sur `git log --all` des deux dépôts (`boucle`, `coderain`) pour écarter ce qui est déjà livré.

**Statut global (mis à jour phase 1, verdicts `MRPG-H-2371` + feu vert Souhel du 28/08) : 18 fiches recensées = 9 ouvertes créées comme Issues GitHub (coderain) + 1 fiche (#13) tranchée en Issue de merge (10 Issues GitHub au total) · 2 fiches (#3, #18) reroutées vault, pas d'Issue GitHub (ligne de partage `D-224` : GitHub ne porte que ce qu'une lane peut livrer dans le repo) · 2 déjà livrées (exclues, gardées ici pour traçabilité) · 4 fiches (#2/#5/#6/#7) caduques par gel, déplacées en fin de fichier.**

La colonne *Label suggéré* est une proposition ; le brief réserve le label `prete` aux fiches "réellement lançables" — décision à trancher en phase 1 au moment de la création effective des Issues, pas figée ici.

*Mise à jour phase 1 ([`MRPG-H-2371`](../../../Vaults/MVP2/meta-rpg/registre-historisation/MRPG-H-2371-pv-phase-0-gel-boucle-moisson-verdicts.md)) : les trois points remontés par la session phase 0 ont été tranchés par le fil méta — voir le PV pour l'argumentaire complet. Répercussion dans ce fichier ci-dessous, item par item.*

---

## Groupe A — lançables en attente (déjà jugées saines par le trieur)

### 1. I-329 — Visualisation combats (feuille perso + canvas)
- **Objectif** : le moteur calcule les règles (dnd5e-engine v0.3, D-200) mais ne les affiche pas. Feuille perso vivante (source `get_world_state`) + canvas combat (grille, pions, HP, initiative) pour rendre le jeu jouable après le 1er tour.
- **Périmètre** : `webapp/character-sheet.html`, `webapp/combat-canvas.js`, `webapp/app.js`, `tests/test-visu-combats.py`, `tests/run_tests.py`. Lecture seule : `engine.py`, `webui.py`.
- **Dépendances** : D-200 (moteur intégré), D-211 (tour jouable, non bloquant), webui I-144.
- **Statut** : OUVERTE — pas de branche `visu-combats-i329` dans l'historique coderain.
- **Label suggéré** : `prete`, priorité moyenne (rentabilité notée « moyenne » par le trieur).

### 2. I-296 — ⚰️ CADUQUE PAR GEL (D-224) — voir section « Caduques par gel » en fin de fichier.

### 3. I-023 — ↩️ REROUTÉE VAULT (pas de périmètre repo) — pas d'Issue GitHub
- **Décision Souhel (feu vert phase 1)** : ligne de partage actée `D-224` — GitHub ne porte que les tickets qu'une lane peut livrer *dans le repo* ; une fiche dont le livrable est une écriture de vault n'est fermable par aucune lane (l'Issue resterait ouverte indéfiniment ou serait fermée sans preuve). I-023 existe déjà comme item du registre `meta-rpg` : c'est son lieu, traité côté méta.
- Objectif d'origine (pour mémoire) : décomposer le chantier transverse du « doigté » (I-056) et les 6 codes de tension (D-218) en briques opératoires ancrées à la destinée (D-219), sans doctrine nouvelle.

### 4. I-309 — Étage Aventure du convertisseur
- **Objectif** : ajoute trajectoire par défaut, perturbations, conditions de monde et charnière de sortie au convertisseur — chaînon manquant pour fermer le test intégrateur DKS.
- **Périmètre** : `converter/emit.py`, `converter/validator.py`, `converter/schemas/aventure.json`, `tests/test-etage-aventure.py`.
- **Dépendances** : D-200 (confirmé mergé, `b2238e4`), I-105, séquencée après `borne-deux-murs-i033` (déjà livrée, `f9745dc`).
- **Statut** : OUVERTE.
- **Label suggéré** : `prete`, priorité très haute (rentabilité trieur : très haute).

### 5. I-314 — ⚰️ CADUQUE PAR GEL (D-224) — voir section « Caduques par gel » en fin de fichier.

### 6. I-320 — ⚰️ CADUQUE PAR GEL (D-224) — voir section « Caduques par gel » en fin de fichier.

### 7. I-271 — ⚰️ CADUQUE PAR GEL (D-224) — voir section « Caduques par gel » en fin de fichier.

### 8. I-462 — Agentivité effacée à la compression
- **Objectif** : le banc fold-arc a mesuré qu'une action exigée par le joueur redevient révélation spontanée d'un PNJ après compression, sans garde de non-contradiction (D-107) pour l'attraper — perte de provenance. Marquage acteur/provenance sur chaque influence scénario.
- **Périmètre** : `converter/validator.py`, `docs/garde-agentivite-i462.md`, `tests/test-garde-agentivite-i462.py`, `schemas/emitter.json`.
- **Dépendances** : D-107, D-129, I-208, I-213 ; après P-conv-3 et coeur-b (#13, statut à vérifier).
- **Statut** : OUVERTE.
- **Label suggéré** : `prete`, priorité très haute (rentabilité trieur : très haute).

### 9. I-159 — Protection des secrets par les données
- **Objectif** : 0/20 entrées cachées sont pinned/critical aujourd'hui donc la garde ne mord pas — un seul `pinned:true` sur une entrée hidden l'exposerait en silence. Règle d'autorat + arme dans le validator.
- **Périmètre** : `docs/gabarit-autorat-secrets-i159.md`, `converter/validator.py`, `tests/test-garde-secrets-i159.py`, `schemas/validator-secrets.json`.
- **Dépendances** : D-082, D-077, I-158, I-154.
- **Statut** : OUVERTE.
- **Label suggéré** : `prete`, priorité très haute (rentabilité trieur : très haute).

### 10. I-150 — Tension plafond (D-076) vs prose (D-079)
- **Objectif** : le plafond/frontière (D-076) et le choix de prose (D-079) ne coïncident pas complètement sur le poste narrateur ; 2/3 lectures déjà tranchées. Tester à coût quasi nul si un modèle frontière apporte un grain de prose distinct.
- **Périmètre** : `docs/cadrage-puissance-i150.md`, `bench/bench-prose-i150.md`, `tests/test-bench-prose-i150.py`.
- **Dépendances** : D-076, D-079, D-091/D-095 (tranchées), I-145, I-100.
- **Statut** : OUVERTE.
- **Label suggéré** : `prete`, priorité haute (rentabilité trieur : haute).

---

## Groupe B — bannies à tort par le compteur d'échecs (`MRPG-I-1622` — bug machine, pas défaut de fiche)

### 11. I-341 — Record Personnage + Destinée — ⛔ EXCLUE
- **Statut** : **DÉJÀ LIVRÉE**. Commit `421c82c` confirmé dans `coderain` : *« Merge personnage-destinee-i341 (8b1c520) : Personnage+Destinee D-219/D-220 + codes D-218 - 6/6 harnais »*.
- **Action** : ne pas créer d'Issue — ban obsolète mais inoffensif (travail déjà en prod).

### 12. D-184 — Patch Director caméra v0 appliqué + mesure improvisation
- **Objectif** : le cadre caméra v0 est spécifié et un patch `director.md` déposé le 23/08 (`7d04c11`) mais jamais appliqué. Câble le double assemblage de contexte (narrateur sans secrets vs Director avec) et mesure le taux d'improvisation (D-128).
- **Périmètre** : `mcp_server.py`, `coderain/engine.py`, `coderain/context.py`, `tests/test-director-camera-patch.py`.
- **Dépendances** : D-209 (front 1), D-184, D-128, I-174, I-158 ; doit passer AVANT #14 (D-218, même `mcp_server.py`).
- **Statut** : OUVERTE — aucune trace de merge dans l'historique coderain.
- **Label suggéré** : `prete`, priorité très haute (rentabilité trieur : très haute).

### 13. coeur-b — Conversation B outillée en webui — ✅ TRANCHÉ (H-2371) : LIVRÉ, JAMAIS MERGÉ → Issue de merge
- **Objectif** : la spec des 4 fenêtres canoniques (D-219) est actée mais rien ne les rend jouables via webui ; sans cet outillage le test DKS « créer Vahn » ne peut avoir lieu.
- **Périmètre** : `webui.py`, `webui.html`, `coderain/engine.py`, `tests/test-conversation-b-outillage.py`.
- **Dépendances** : I-340, I-341 (livré), D-219, D-220, I-144 ; doit passer avant `coeur-interface-complet`.
- **Verdict `MRPG-H-2371`** : ni doublon ni caduque. [`H-1842`](../../../Vaults/MVP2/meta-rpg/registre-historisation/MRPG-H-1842-pv-rapport-coeur-b-outillage-webui-couvert.md) (27/08 14:55) a rendu COUVERT sur le commit `be241c0` (8/8 tests, réserves mineures), avec merge piloté prescrit (`--ff-only` + push) resté lettre morte.
- **⚠️ Nouvelle discordance trouvée à l'audit phase 1 (28/08)** : `be241c0` n'est **plus** l'ancêtre d'aucune branche — `git branch -a --contains be241c0` ne retourne rien. La branche `origin/coeur-b-outillage-webui` pointe aujourd'hui sur `8934352` (même parent `cf8a57b`, commit 21 min plus tard, message quasi identique mais diff différent : `git diff --stat be241c0 8934352` = 4 fichiers, +691/-927 lignes nettes vs le contenu vérifié ligne à ligne par H-1842). Autrement dit : la branche a été réécrite (force-push probable) **après** la vérification H-1842, qui n'a donc pas revu le contenu actuellement sur la branche. **Le `--ff-only` prescrit ne s'applique plus au bon commit.**
- **Action** : Issue de merge dédiée (pas de re-développement), avec deux tâches explicites : (1) re-vérifier le contenu réel de `8934352` avant tout merge — la relecture ligne à ligne de H-1842 portait sur `be241c0`, un commit désormais introuvable sur la branche ; (2) une fois vérifié, merger par `merge`/`rebase` (le `--ff-only` initialement prescrit ne passera pas, `main` a avancé depuis `cf8a57b`) et rejouer les suites. Séquencement : `coeur-interface-complet` (#13bis) reste derrière ce merge.
- **Statut** : Issue à créer (merge, pas re-dev), label `prete`.

### 13bis. coeur-interface-complet — séquencée derrière coeur-b (note de séquencement, pas une fiche de la moisson)
- **Constat audit phase 1** : `origin/coeur-interface-complet` (tip `001c212`, parent `2eb846d`, parent `cf8a57b`) n'est pas non plus mergée dans `main` (`git merge-base --is-ancestor 2eb846d main` → NO). Périmètre observé au dernier commit (`001c212`) : `matrix.js`, `index.html`, `style.css`, `app.js`, `tests/test-interface-complet.py` — le message du commit affirme `webui.py`/`webui.html` inchangés, donc le chevauchement redouté par H-1842 semble résorbé dans cette révision, mais **à re-vérifier** au moment du merge de `coeur-b` (diff réel contre le `main` d'alors, pas seulement le message de commit).
- **Action** : ne pas créer d'Issue de re-développement — le travail existe déjà sur la branche. Si une Issue de merge est ouverte pour elle aussi, la séquencer explicitement APRÈS celle de #13 (même risque de collision `webui.py` que H-1842 avait signalé, à confirmer/infirmer au diff réel).

### 14. D-218 — Contrat convertisseur des 6 codes de tension traversants
- **Objectif** : matérialise le contrat D-218 (menace/horloge/échéance/coût/choix/révélation) comme enum vérifiée par le validator et respectée par l'emit, levier opposable pour le doigté Auteur (I-232).
- **Périmètre** : `converter/schemas.py`, `converter/emit.py`, `converter/validate_form.py`, `tests/test-auteur-codes-tension.py`.
- **Dépendances** : D-218, I-340, I-232, I-341 (livré) ; après #12 (D-184), avant toute prochaine P-conv.
- **Statut** : OUVERTE.
- **Label suggéré** : `prete`, priorité haute (rentabilité trieur : haute).

### 15. I-362/I-363 — Corrections dispositif v2 (retry après ouverture + lore_scenes) — ⛔ EXCLUE
- **Statut** : **DÉJÀ LIVRÉE**. Commit `cfe3545` confirmé : *« Merge corrections-dispositif-v2-i362-i363 (4be8173) : B1 retry/undo apres ouverture (I-362) + S1 lore_scenes test (I-363) - couvert H-1862 »*. Ce même commit sert de baseline « main ≥ » citée par 5 fiches du groupe A.
- **Action** : ne pas créer d'Issue — ban obsolète mais inoffensif.

### 16. D-219 (patch) — Rédaction patch director.md protocole conversation B
- **Objectif** : même si l'outillage moteur/webui de la conversation B existait (cf. #13), le Director n'a aucune instruction sur le protocole des 4 fenêtres ni sur la traduction des marqueurs en atmosphère. Un seul livrable : le texte de patch — l'application à `director.md` est un geste séparé.
- **Périmètre** : `PATCH-director-conversation-b-d219-2026-08-27.md` (poste technique, pas de dépôt git) ; lecture seule sur `director.md`.
- **Dépendances** : D-219, D-220, I-144, #13 (statut douteux) ; précédent patch caméra jamais appliqué (`7d04c11`, cf. #12).
- **Statut** : OUVERTE — la fiche dit elle-même que la part Director manque.
- **Note** : dépend de la résolution de #13 avant d'être vraiment actionnable.

### 17. I-229 — Détecteur de répétition à l'échelle campagne
- **Objectif** : aucun module ne « voit » les autres ; l'Auteur est le seul organe placé pour comparer deux scénarios. Détecteur déterministe (score par code D-218 + motif le plus proche) qui signale sans décider.
- **Périmètre** : `coderain/author.py`, `coderain/validator.py`, `tests/test-repetition-campagne.py` ; lecture seule `schemas/emit`, `partition-pconv3`.
- **Dépendances** : D-218, D-220 (interdiction rétro-création), I-232, D-209 front 3.
- **Statut** : OUVERTE.
- **Label suggéré** : `prete`, priorité haute (rentabilité trieur : haute).

### 18. I-335 — ↩️ REROUTÉE VAULT (pas de périmètre repo) — pas d'Issue GitHub
- **Décision Souhel (feu vert phase 1)** : même ligne de partage que #3 — livrable = écriture de vault, pas fermable par une lane repo. I-335 existe déjà comme item du registre `meta-rpg` : traité côté méta.
- Objectif d'origine (pour mémoire) : deux fichiers portent `id: MRPG-I-333` depuis le 25/08, rendant toute référence nue ambiguë entre deux sujets distincts. Renomme le plus récent et déréférence exhaustivement.

---

## Caduques par gel (D-224) — verdict `MRPG-H-2371`

**Ces 4 fiches portent sur `veilleur.ps1` du repo `boucle`, désormais gelé définitivement (`D-224` point 4). Pas d'Issue créée pour elles.**

### #2 — I-296 — Filtre marqueurs non accentués (Get-Lancables)
- **Objectif** : `Get-Lancables` n'écarte les fiches closes que sur formes accentuées (« livré », « fermée ») ; les graphies sans accent traversent et sont relancées comme lançables — faille de fiabilité du tampon.
- **Périmètre** : `veilleur.ps1` (fonction filtre), `tests/test-filtre-marqueurs-i296.ps1`, `tests/run-all.ps1` — repo `boucle`.
- **Dépendances** : D-192/D-213, I-289, I-272.
- **Leçon générique (phase 2, si utile)** : le filtre de statut dépendait d'un matching texte sensible aux accents — un futur dispatch GitHub Issues (labels, pas texte français à parser) n'hérite pas de ce risque tel quel ; pas de ligne de conception nécessaire.

### #5 — I-314 — Garde horodatés de clôture dans le futur
- **Objectif** : 3 horodatés de clôture mesurés en avance de +3,5 à +8 min sur le mtime réel, ce qui périme la chronologie du journal.
- **Périmètre** : `veilleur.ps1` (`Test-HorodateCoherence`), `tests/test-horodate-coherence.ps1`, `eveil-meta.md` — repo `boucle`.
- **Dépendances** : CLAUDE.md §4, I-310 ; après déban de I-296.
- **Leçon générique (phase 2)** : la dérive horloge/mtime observée (source non identifiée, +3,5 à +8 min) est un risque générique pour tout futur dispatch qui séquencerait sur des horodatages de fichiers plutôt que sur l'horloge GitHub (Issues/PR ont leurs propres timestamps serveur, moins exposés à ce type de dérive locale — mais si le dispatch garde un journal local, la garde de tolérance reste une bonne pratique à reprendre).

### #6 — I-320 — Vault Obsidian Sync (compteur d'ids H non caché)
- **Objectif** : le compteur d'ids H (`.compteur-h`) est un fichier point, donc ignoré par Obsidian Sync — source de bornes dupliquées dès une 2e machine.
- **Périmètre** : `veilleur.ps1` (`Get-CompteurHPath` / `Reserve-BorneIdsH`), `tests/test-vault-obsidian-sync-i320.ps1` — repo `boucle`.
- **Dépendances** : I-310 ; précédait #7 (I-271, même fichier).
- **Leçon générique** : propre au stockage Obsidian Sync du compteur, pas au futur dispatch (qui n'écrit pas dans ce fichier).

### #7 — I-271 — Collision id H-057 (garde allocataire)
- **Objectif** : deux entrées portaient `id: MRPG-H-057` ; garde qui refuse la pose d'un id déjà présent dans `registre-historisation/`.
- **Périmètre** : `veilleur.ps1` (`Test-IdHistorisationLibre`), `tests/test-collision-h057-i271.ps1` — repo `boucle`.
- **Dépendances** : I-310 ; après #6 (I-320, même fichier) ; jumelle de #18 (I-335).
- **Leçon générique (phase 2)** : celle-ci vaut vraiment pour le futur dispatch — tant que le journal H/I reste tenu dans le vault (indépendamment de qui alloue les ids), une garde anti-collision d'id à l'écriture reste nécessaire quel que soit l'outil amont. À reprendre dans la conception du dispatch si celui-ci écrit aussi des entrées H/I.

---

## Récapitulatif pour la création des Issues (phase 1)

| # | ID | Titre court | Statut | Repo cible |
|---|----|----|----|----|
| 1 | I-329 | Visualisation combats | OUVERTE | coderain |
| 2 | I-296 | Filtre marqueurs non accentués | **⚰️ CADUQUE PAR GEL** | — |
| 3 | I-023 | Chantier fil rouge doigté | **↩️ REROUTÉE VAULT** | — (vault, registre) |
| 4 | I-309 | Étage Aventure convertisseur | OUVERTE | coderain |
| 5 | I-314 | Garde horodatés futurs | **⚰️ CADUQUE PAR GEL** | — |
| 6 | I-320 | Vault Obsidian Sync | **⚰️ CADUQUE PAR GEL** | — |
| 7 | I-271 | Collision id H-057 | **⚰️ CADUQUE PAR GEL** | — |
| 8 | I-462 | Agentivité à la compression | OUVERTE | coderain |
| 9 | I-159 | Protection secrets par les données | OUVERTE | coderain |
| 10 | I-150 | Tension plafond vs prose | OUVERTE | coderain |
| 11 | I-341 | Record Personnage+Destinée | **EXCLUE (livrée `421c82c`)** | — |
| 12 | D-184 | Patch Director caméra v0 | OUVERTE | coderain |
| 13 | coeur-b | Conversation B outillée webui | **Issue de merge** (⚠️ re-vérifier `8934352`, cf. audit phase 1) | coderain |
| 14 | D-218 | Contrat codes de tension | OUVERTE | coderain |
| 15 | I-362/I-363 | Corrections dispositif v2 | **EXCLUE (livrée `cfe3545`)** | — |
| 16 | D-219 (patch) | Patch director.md conversation B | OUVERTE (dépend de #13) | coderain (doc) |
| 17 | I-229 | Détecteur répétition campagne | OUVERTE | coderain |
| 18 | I-335 | Collision id I-333 | **↩️ REROUTÉE VAULT** | — (vault, registre) |

**Issues créées en phase 1 (10 Issues GitHub au total, feu vert Souhel 28/08) :**
- **9 en coderain** : #1 (I-329), #4 (I-309), #8 (I-462), #9 (I-159), #10 (I-150), #12 (D-184), #14 (D-218), #16 (D-219 patch, dépend de #13/coeur-b mergé), #17 (I-229).
- **1 Issue de merge** (#13 coeur-b, label `prete`, avec la vigilance `8934352` notée ci-dessus — contenu à re-vérifier avant merge, pas simplement rejouer le `--ff-only` H-1842 — et le séquencement `coeur-interface-complet` derrière).
- **#3 (I-023) et #18 (I-335) : reroutées vault, pas d'Issue GitHub** — décision Souhel : ligne de partage `D-224`, GitHub ne porte que ce qu'une lane peut livrer dans le repo ; ces deux items existent déjà dans le registre `meta-rpg`, traités côté méta.

9 Issues ordinaires + 1 merge = 10 threads de travail sur GitHub. (Le chiffre « 16 ouvertes » du brief reprend le décompte brut de phase 0, avant que les 4 fiches `veilleur.ps1` ne soient tranchées caduques, que #13 ne soit reclassée en Issue de merge, et que #3/#18 ne soient reroutées vault : 16 − 4 (caduques) − 1 (coeur-b, recompté à part) − 2 (reroutées vault) = 9, cohérent.)
**4 fiches (#2, #5, #6, #7) : caduques par gel — voir section dédiée ci-dessus, pas d'Issue.**
**2 fiches (#3, #18) reroutées vault** (décision Souhel 28/08) — existent déjà comme items du registre `meta-rpg`, pas d'Issue GitHub : ligne de partage `D-224`, un livrable qui est une écriture de vault n'est fermable par aucune lane repo.
