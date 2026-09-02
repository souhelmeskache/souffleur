# tools/banc/ — scripts de veille du banc

- `nuit.sh` / `nuit.cmd` / `verifier-avant-nuit.sh` / `metriques_nuit.py` :
  **banc de nuit N1** (#201, D-276 ; #260) — voir section dédiée ci-dessous.
- `jouer-tours-4.sh` : boucle de tours du banc (fil 2), avec détection d'agent
  bloqué ; sort sur lot fini, agent bloqué, nouveau craquement, timeout ou
  fichier PAUSE.
- `veiller.sh` : veille sur l'apparition d'un fichier du journal, sans
  envoyer de go ; mêmes conditions de sortie que ci-dessus.
- `circuit.sh` : **point d'entrée unique du circuit de lane** (I-243, « ce
  qui crée détruit » ; I-250, « la veille est dans l'outil, pas dans un
  scratchpad » ; #255, un seul point d'entrée). Sans argument, imprime
  l'aide des six verbes.
  - `lancer <ISSUE> [modele] [effort]` : enveloppe `lancer-lane.ps1 <ISSUE>
    [-Modele <modele>] [-Effort <effort>]` (appel
    `powershell.exe -NoProfile -ExecutionPolicy Bypass -File …`). Appelle
    systématiquement `garde` avant de lancer — plus de geste manuel séparé.
  - `revoir <PR>` : enveloppe `lancer-lane.ps1 -Revue <PR>`, même garde
    systématique avant lancement.
  - `garde` : vérifie `core.bare` sur le checkout principal
    (`git config --show-origin --get core.bare`) ; s'il est présent, le
    retire (`--unset`) et journalise une ligne datée (heure, origine,
    commande en cours) dans `tools/banc/core-bare.log` (I-231, #231 — cause
    de réapparition inconnue). Idempotent : sortie 0 que `core.bare` ait été
    trouvé et retiré, ou déjà absent. Appelée par `lancer`/`revoir`, et
    rejouable seule.
  - `nettoyer <lane-NNN|revue-NNN>` ferme le workspace herdr, retire le
    worktree Git et la branche ; `nettoyer --orphelins` purge les dossiers de
    `.herdr/worktrees/souffleur/` qu'aucun worktree Git ni workspace herdr ne
    tient plus ; `etat` liste en une commande lanes en vol, PR ouvertes,
    workspaces, worktrees et orphelins. Les deux verbes de `nettoyer` sont
    idempotents (sortie 0 si déjà propre). Appelé par `veiller` après merge
    et après chaque REFUS (teardown du worktree de revue).
  - `veiller <ISSUE>` : UN watcher par circuit, qui couvre toutes les phases
    d'une lane jusqu'à son merge.

    **Phases** (dans l'ordre, celle atteinte au moment d'une sortie non
    nulle est journalée sur l'Issue) :
    1. `attente_pr` — attend la PR de `lane-<ISSUE>` : par branche, puis
       `closingIssuesReferences`, puis commentaire `TERMINÉ` de l'issue.
    2. `ci` — attend la CI verte de la PR.
    3. `revue` — relance une revue fraîche (`lancer-lane.ps1 -Revue <PR>`)
       et attend son verdict (`REVUE : APPROUVE` / `REVUE : REFUS`).
    4. `merge` — sur `APPROUVE` : merge squash, `circuit.sh nettoyer` de la
       lane et de la revue, `pull --ff-only`, sortie 0.
    5. `attente_termine` — sur `REFUS` : renvoie automatiquement le verdict
       à la lane (`herdr agent prompt lane-<ISSUE> "<verdict>… pousse puis
       poste un nouveau TERMINÉ"`), nettoie le worktree de revue, puis
       attend un `TERMINÉ` postérieur au verdict et reboucle en phase `ci`.
       **Au plus 2 cycles de refus** — le 3ᵉ `REFUS` sort en code 4 (REFUS
       persistant) plutôt que de rerenvoyer indéfiniment.

    **Codes de sortie** :
    - `0` — succès : merge fait, ou Issue déjà soldée détectée au lancement
      (rejeu idempotent — Issue fermée ou PR déjà mergée pour elle).
    - `1` — CI rouge, verdict de revue absent/en timeout, ou échec du merge.
    - `2` — agent `lane-<ISSUE>` relevé `blocked` deux fois de suite : lit
      les 20 dernières lignes du pane (`herdr agent read`), les poste en
      commentaire `BLOQUÉ (watcher) : …` sur l'Issue.
    - `3` — 90 min sans changement de phase.
    - `4` — REFUS persistant (3ᵉ cycle).

    Chaque sortie non nulle poste en commentaire de l'Issue une ligne
    `VEILLE <ISSUE> : <code> <raison> <phase>` — le journal du circuit vit
    sur l'Issue, jamais dans un scratchpad.
  - `solder-issue.sh <ISSUE>`, `attendre-termine.sh <ISSUE> <PR>` et
    `solder3.sh <PR>` sont des alias de compatibilité qui délèguent tous à
    `circuit.sh veiller <ISSUE>` (habitude d'appel du poste META) ; la
    logique elle-même vit uniquement dans `circuit.sh`.

Origine : banc de nuit du 31/08 → 01/09/2026 (fiche #201). Versionnés en
l'état, pas encore intégrés au lanceur (#210).

## Banc de nuit N1 (#201, D-276 ; #260) — la boucle-ferme sans LLM

Joue des parties complètes la nuit, sans humain, sans analyste, avec budget,
arrêt propre et sorties en forme fixe. `nuit.sh` ne prend AUCUNE décision de
jeu : il copie des fichiers, lance/observe/ferme les deux agents existants
(joueur, Director — via `lancer-banc-fumee.ps1` réutilisé, pas réécrit), et
journalise des faits mécaniques. Toute décision narrative reste dans les
gabarits gelés (`tools/prompts/banc-mj.md`/`banc-joueur.md`, D-276 §4) ou le
sous-agent narrateur qu'ils spawnent.

### La commande du soir

```
.\tools\banc\nuit.cmd
```

Lancable par double-clic ou depuis un terminal ordinaire (PowerShell ou
cmd.exe), **sans ouvrir Claude Code**. Résout Git Bash lui-même (pas de
dépendance au PATH pour bash), reste ouverte le temps de la nuit, et
enchaîne : `git pull --ff-only` → garde de prérequis + « rien en vol »
(`verifier-avant-nuit.sh` : herdr joignable, `claude`/`gh` présents, save
présente, aucun agent `lane-*`/`revue-*` de circuit.sh, aucune PR ouverte) →
`tools/banc/nuit.sh -Parties 4 -Director ab` (défauts — un argument passé au
`.cmd` les remplace intégralement, ex. `.\tools\banc\nuit.cmd -Parties 8
-Director sonnet`) → affiche le chemin de `nuit.md` produit.

**Le matin** : ouvrir un fil et dire « lis la nuit » — Claude relit
`bench/nuit-AAAAMMJJ/nuit.md` et les `resume-run.md` de chaque partie.

### `nuit.sh` — paramètres

```
tools/banc/nuit.sh -Parties N [-Director haiku|sonnet|ab] [-Tours 40]
                    [-Save <slug>] [-TimeoutTour <minutes>] [-DryRun]
```

- `-Parties N` (obligatoire) : nombre de parties à jouer ce lancement — le
  budget de la nuit. Plafond dur : aucune (N+1)-ème partie n'est lancée.
- `-Director haiku|sonnet|ab` (défaut `sonnet`) : modèle du Director
  (agent MJ). `ab` alterne haiku/sonnet en commençant par haiku (N0 = 4
  parties : 2 et 2) — le casting de chaque partie est écrit dans son
  `resume-run.md`. Le joueur tourne toujours en haiku/low, le narrateur
  (sous-agent spawné par le Director) en haiku.
- `-Tours 40` : plafond de tours par partie.
- `-Save <slug>` (défaut `beyond-the-vale-of-madness`) : save source
  (`saves/<slug>`, résolution `coderain/config.py::saves_dir`), copiée
  fraîche pour chaque partie — jamais jouée directement.
- `-TimeoutTour <minutes>` (défaut 6) : au-delà, sans nouveau fichier de
  tour, la partie craque (`craquement-timeout-NN.md`) et se ferme ; la
  suivante démarre.
- `-DryRun` : crée toute l'arborescence (copies de save + fixture) et les
  `resume-run.md`/`nuit.md`, mais ne lance AUCUN agent — sert au test de
  forme (`tests/nuit_dryrun_test.py`) et à vérifier un montage sans
  consommer de budget de session.

Un second appel le même jour reprend au numéro de partie suivant (ne
réécrase jamais une partie déjà jouée — idempotence).

### Ce que fait une partie

1. Copie fraîche de la save vers `bench/nuit-AAAAMMJJ/partie-NN/save/` et
   installation de la fixture de personnage (`bench/fixtures/personnage-banc.py`,
   #257).
2. Lancement des deux agents (`lancer-banc-fumee.ps1`, avec `-ModeleMj`,
   `-ModeleJoueur`, `-SavesDirOverride` et `-JournalDirOverride` — trois
   paramètres additifs #260, défauts inchangés pour le banc de fumée
   historique) — le journal ET la save isolée de la partie vivent tous deux
   sous `bench/nuit-AAAAMMJJ/partie-NN/`.
3. Boucle de tours par lots (go joueur → `action-NN.md` → go MJ →
   `prose-NN.md`/`tour-NN.md`), jusqu'à fin de partie, craquement, ou
   `-Tours`.
4. Fermeture des agents (`herdr pane close` des deux panes — l'équivalent
   banc de `circuit.sh nettoyer`, I-243 : ce qui crée détruit).
5. Partie suivante.

### Sorties en forme fixe

`bench/nuit-AAAAMMJJ/partie-NN/` reçoit `tour-NN.md`, `prose-NN.md`,
`action-NN.md`, `craquement-*.md` (comme le banc de fumée) + un
`resume-run.md` MINIMAL écrit par le script (casting, tours joués, fin
atteinte O/N, raison de l'arrêt, liste des craquements, durée) — l'analyse
est N2, pas ce script.

`bench/nuit-AAAAMMJJ/nuit.md` : table des parties (director, tours joués,
fin atteinte, raison), budget consommé, raison de l'arrêt de la nuit, et les
métriques §3 de #201 (`tools/banc/metriques_nuit.py`, calculées par le
script, jamais un jugement).

### Budget, arrêt propre, codes de sortie

- **Timeout par tour** (`-TimeoutTour`, défaut 6 min) : craquement
  `timeout` journalisé, partie fermée, suivante lancée — n'arrête PAS la
  nuit.
- **Limite de session** : texte « session limit »/« usage limit » détecté
  dans un pane, OU agent `blocked` + idle sans progrès > 10 min → `nuit.md`
  écrit, les deux panes de la partie en cours sont fermés, **sortie 5** —
  arrête TOUTE la nuit (jamais un agent laissé en vol), même si `-Parties`
  n'est pas atteint.
- **Interruption (Ctrl+C)** : `trap INT/TERM` — ferme les agents en vol,
  écrit `nuit.md` avec `raison_arret: interrompu (SIGNAL)`, sort 130.
- **`0`** : la nuit s'est terminée normalement (budget `-Parties` consommé).
- **`1`** : argument invalide (refus avant tout lancement).
- **`5`** : limite de session — voir ci-dessus.
- **`130`** : interrompu (Ctrl+C).

### Ce que la nuit ne fait pas

- **Pas d'analyse, pas de correction** — N2/N3 lisent `nuit.md` et les
  `resume-run.md`, ce script les écrit seuls.
- **Pas de détection narrative de « fin de module »** : aucun signal
  générique de complétion narrative n'existe côté moteur sans jugement
  humain/LLM (hors périmètre #260 : « aucun LLM dans le script »). `fin
  atteinte` dans `resume-run.md` est un PROXY MÉCANIQUE — mort du joueur
  (`rpg.player.conditions` contient `"dead"`) — pas une lecture de la
  progression narrative. Une partie qui épuise `-Tours` sans mourir sort
  avec `fin_atteinte: N`, `raison_arret: tours_max`, sans que ce soit un
  échec.
- **Pas de protocole de tour 1 « froid »** : les gabarits gelés
  (`banc-mj.md`/`banc-joueur.md`, D-276 §4) supposent une reprise, pas un
  démarrage à vide. `nuit.sh` comble ce trou en envoyant le premier « go »
  au Director seul (« ouverture, pas d'action joueur — établis la scène
  d'ouverture ») plutôt qu'au joueur — une limite assumée, pas un défaut du
  gabarit.
- **Refus d'outil / combats sous-système dans les métriques** :
  `attack`/`roll_check` (refus) et `start_combat` (combat dnd5e-engine)
  n'écrivent aujourd'hui RIEN dans `events.jsonl` côté moteur — ces deux
  compteurs de `metriques_nuit.py` restent à 0 tant que ça ne change pas
  (hors périmètre #260 : aucune modification du moteur). Les bouchages
  (D-275) et les combats hors sous-système (deltas d'ennemi via
  `apply_envelope`) sont, eux, fiables dès aujourd'hui.
