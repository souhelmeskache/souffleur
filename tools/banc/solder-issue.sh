#!/bin/bash
# Usage: solder-issue.sh <ISSUE> — attend la PR de lane-<ISSUE>, sort si l'agent est bloque (2 releves) ou apres 90 min, puis solder3.sh.
# La PR peut ne pas avoir la branche lane-<ISSUE> (vecu sur #220 et #226) : on cherche aussi
# par closingIssuesReferences, puis par le numero de PR cite dans un commentaire TERMINE de l'issue.
REPO=souhelmeskache/souffleur; ISSUE=$1; nb=0
for i in $(seq 1 180); do
  PR=$(gh pr list -R $REPO --head lane-$ISSUE --state open --json number --jq '.[0].number // empty')
  if [ -z "$PR" ]; then
    PR=$(gh pr list -R $REPO --state open --json number,closingIssuesReferences --jq "[.[] | select(.closingIssuesReferences[]?.number == $ISSUE)] | .[0].number // empty")
  fi
  if [ -z "$PR" ]; then
    PR=$(gh issue view $ISSUE -R $REPO --json comments --jq '[.comments[] | select(.body | startswith("TERMIN")) | .body] | last // empty' | grep -oE '/pull/[0-9]+' | grep -oE '[0-9]+' | tail -1)
  fi
  [ -n "$PR" ] && break
  L=$(herdr agent list 2>/dev/null | tr '{' '\n' | grep "\"name\":\"lane-$ISSUE\"")
  if echo "$L" | grep -q 'agent_status":"blocked'; then nb=$((nb+1)); [ $nb -ge 2 ] && { echo "$(date '+%H:%M:%S') AGENT lane-$ISSUE BLOQUE — STOP"; exit 2; }; else nb=0; fi
  echo "$(date '+%H:%M:%S') #$ISSUE : pas de PR encore"; sleep 30
done
[ -z "$PR" ] && { echo "TIMEOUT sans PR — STOP"; exit 3; }
echo "=== PR $PR trouvee pour #$ISSUE ==="
exec bash /c/Users/souhe/souffleur/tools/banc/solder3.sh $PR
