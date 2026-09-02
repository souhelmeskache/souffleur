# tools/banc/ — scripts de veille du banc

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
