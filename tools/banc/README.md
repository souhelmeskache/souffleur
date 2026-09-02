# tools/banc/ — scripts de veille du banc

- `jouer-tours-4.sh` : boucle de tours du banc (fil 2), avec détection d'agent
  bloqué ; sort sur lot fini, agent bloqué, nouveau craquement, timeout ou
  fichier PAUSE.
- `veiller.sh` : veille sur l'apparition d'un fichier du journal, sans
  envoyer de go ; mêmes conditions de sortie que ci-dessus.
- `circuit.sh` : teardown du circuit de lane (I-243, « ce qui crée détruit »).
  `nettoyer <lane-NNN|revue-NNN>` ferme le workspace herdr, retire le
  worktree Git et la branche ; `nettoyer --orphelins` purge les dossiers de
  `.herdr/worktrees/souffleur/` qu'aucun worktree Git ni workspace herdr ne
  tient plus ; `etat` liste en une commande lanes en vol, PR ouvertes,
  workspaces, worktrees et orphelins. Les deux verbes de `nettoyer` sont
  idempotents (sortie 0 si déjà propre). Appelé par `solder3.sh` après merge.
- `solder3.sh` : solde d'une PR — attente CI verte, puis revue fraîche,
  verdict, merge, puis `circuit.sh nettoyer` de la lane et de sa revue.
- `solder-issue.sh <ISSUE>` : attend la PR de `lane-<ISSUE>` (par branche,
  `closingIssuesReferences`, ou commentaire `TERMINÉ` de l'issue), sort si
  l'agent est bloqué (2 relevés) ou après 90 min, puis enchaîne `solder3.sh`.
- `attendre-termine.sh <ISSUE> <PR>` : attend un commentaire `TERMINÉ` posté
  sur l'issue après le lancement (cas d'un correctif poussé suite à REFUS),
  puis `solder3.sh <PR>`.

Origine : banc de nuit du 31/08 → 01/09/2026 (fiche #201). Versionnés en
l'état, pas encore intégrés au lanceur (#210).
