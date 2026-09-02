#!/bin/bash
# Usage: attendre-termine.sh <ISSUE> <PR> — attend un commentaire "TERMINÉ" poste sur l'issue APRES maintenant
# (donc apres le push du correctif), sort si l'agent lane-<ISSUE> est bloque (2 releves) ou apres 90 min, puis solder3.sh <PR>.
REPO=souhelmeskache/souffleur; ISSUE=$1; PR=$2; nb=0
T0=$(date -u "+%Y-%m-%dT%H:%M:%SZ")
for i in $(seq 1 180); do
  c=$(gh issue view $ISSUE -R $REPO --json comments --jq "[.comments[] | select(.createdAt > \"$T0\") | select(.body | startswith(\"TERMIN\"))] | length")
  [ "$c" != "0" ] && [ -n "$c" ] && break
  L=$(herdr agent list 2>/dev/null | tr '{' '\n' | grep "\"name\":\"lane-$ISSUE\"")
  if echo "$L" | grep -q 'agent_status":"blocked'; then nb=$((nb+1)); [ $nb -ge 2 ] && { echo "$(date '+%H:%M:%S') AGENT lane-$ISSUE BLOQUE — STOP"; exit 2; }; else nb=0; fi
  echo "$(date '+%H:%M:%S') #$ISSUE : pas de TERMINÉ depuis $T0"; sleep 30
done
[ "$c" = "0" ] && { echo "TIMEOUT sans TERMINÉ — STOP"; exit 3; }
echo "=== TERMINÉ recu sur #$ISSUE, solde de la PR $PR ==="
exec bash /c/Users/souhe/souffleur/tools/banc/solder3.sh $PR
