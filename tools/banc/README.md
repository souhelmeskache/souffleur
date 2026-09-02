# tools/banc/ — scripts de veille du banc

- `jouer-tours-4.sh` : boucle de tours du banc (fil 2), avec détection d'agent
  bloqué ; sort sur lot fini, agent bloqué, nouveau craquement, timeout ou
  fichier PAUSE.
- `veiller.sh` : veille sur l'apparition d'un fichier du journal, sans
  envoyer de go ; mêmes conditions de sortie que ci-dessus.
- `solder3.sh` : solde d'une PR — attente CI verte, puis revue fraîche,
  verdict, merge.

Origine : banc de nuit du 31/08 → 01/09/2026 (fiche #201). Versionnés en
l'état, pas encore intégrés au lanceur (#210).
