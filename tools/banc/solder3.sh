#!/bin/bash
# Alias de compatibilité (I-250) : solder3.sh <PR> == circuit.sh veiller <ISSUE>,
# où <ISSUE> est résolue via closingIssuesReferences de la PR. CI verte,
# revue fraîche, verdict, merge, teardown vivent désormais dans circuit.sh —
# ce script ne fait plus que déléguer, gardé pour l'habitude d'appel du
# poste META.
REPO=souhelmeskache/souffleur
PR=$1
ISSUE=$(gh pr view "$PR" -R "$REPO" --json closingIssuesReferences --jq '.closingIssuesReferences[0].number // empty')
if [ -z "$ISSUE" ]; then
  echo "Impossible de résoudre l'issue fermée par la PR $PR — impossible de déléguer à circuit.sh veiller." >&2
  exit 1
fi
exec bash "$(dirname "$0")/circuit.sh" veiller "$ISSUE"
