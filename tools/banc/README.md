# tools/banc/ — scripts de veille du banc

- `jouer-tours-4.sh` : boucle de tours du banc (fil 2), avec détection d'agent
  bloqué ; sort sur lot fini, agent bloqué, nouveau craquement, timeout ou
  fichier PAUSE.
- `veiller.sh` : veille sur l'apparition d'un fichier du journal, sans
  envoyer de go ; mêmes conditions de sortie que ci-dessus.
- `solder3.sh` : solde d'une PR — attente CI verte, puis revue fraîche,
  verdict, merge.
- `solder-issue.sh <ISSUE>` : attend la PR de `lane-<ISSUE>` (par branche,
  `closingIssuesReferences`, ou commentaire `TERMINÉ` de l'issue), sort si
  l'agent est bloqué (2 relevés) ou après 90 min, puis enchaîne `solder3.sh`.
- `attendre-termine.sh <ISSUE> <PR>` : attend un commentaire `TERMINÉ` posté
  sur l'issue après le lancement (cas d'un correctif poussé suite à REFUS),
  puis `solder3.sh <PR>`.

Origine : banc de nuit du 31/08 → 01/09/2026 (fiche #201). Versionnés en
l'état, pas encore intégrés au lanceur (#210).
