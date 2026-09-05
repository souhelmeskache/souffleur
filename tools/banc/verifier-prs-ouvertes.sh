#!/bin/bash
# tools/banc/verifier-prs-ouvertes.sh — classe le nombre de PR ouvertes sur
# le dépôt, extrait de verifier-avant-nuit.sh pour être testable
# indépendamment de `gh`/réseau (#297, seconde moitié de #292).
#
# Direction Souhel du 05/09 (D-280, #292) : les parties tournent en
# parallèle du circuit de code — une PR ouverte est l'état normal du dépôt
# et n'entre pas en collision avec une nuit. Simple avertissement, jamais un
# refus.
#
# Usage : gh pr list -R <repo> --json number --jq 'length' \
#           | tools/banc/verifier-prs-ouvertes.sh
#
# Sorties :
#   - 0 (ou vide/non numérique, échec gh) : rien, code 0.
#   - N > 0                               : AVERTISSEMENT sur stdout, code 0.
set -u

prs_ouvertes="$(cat)"

if [[ "$prs_ouvertes" =~ ^[0-9]+$ ]] && [ "$prs_ouvertes" -gt 0 ]; then
  echo "AVERTISSEMENT : $prs_ouvertes PR ouverte(s) sur le dépôt — sans effet sur la nuit."
fi

exit 0
