#!/bin/bash
# Solde d'UNE PR : CI verte -> revue FRAICHE -> verdict -> merge.
REPO=souhelmeskache/souffleur
LANCEUR="C:/Users/souhe/souffleur/tools/lancer-lane.ps1"
PR=$1
echo "=== PR $PR : attente CI verte ==="
for i in $(seq 1 60); do
  ck=$(gh pr view $PR -R $REPO --json statusCheckRollup --jq '[.statusCheckRollup[]? | (.conclusion // .state // "PENDING")] | join(",")')
  ms=$(gh pr view $PR -R $REPO --json mergeStateStatus --jq '.mergeStateStatus')
  echo "PR $PR mergeState=$ms checks=[$ck]"
  case "$ck" in
    *FAILURE*|*ERROR*|*CANCELLED*|*TIMED_OUT*) echo "CI ROUGE — STOP"; exit 1;;
    *SUCCESS*) if [ "$ms" = "CLEAN" ] || [ "$ms" = "BLOCKED" ] || [ "$ms" = "UNSTABLE" ]; then break; fi;;
  esac
  sleep 30
done
T0=$(date -u "+%Y-%m-%dT%H:%M:%SZ")
echo "=== PR $PR : revue FRAICHE (T0=$T0) — l'ancien verdict precede le push du merge de main ==="
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$LANCEUR" -Revue $PR 2>&1 | tail -1
body=""
for i in $(seq 1 80); do
  sleep 30
  body=$(gh pr view $PR -R $REPO --json comments --jq "[.comments[] | select(.createdAt > \"$T0\") | select(.body | startswith(\"REVUE :\"))] | last // {} | .body // \"\"")
  [ -n "$body" ] && break
done
[ -z "$body" ] && { echo "TIMEOUT verdict"; exit 1; }
head=$(echo "$body" | head -1)
echo "PR $PR verdict FRAIS: $head"
case "$head" in
  "REVUE : APPROUVE"*) ;;
  *) echo "NON MERGEE — verdict non approuvant :"; echo "$body" | head -40; exit 1;;
esac
for i in $(seq 1 40); do
  ms=$(gh pr view $PR -R $REPO --json mergeStateStatus --jq '.mergeStateStatus')
  [ "$ms" = "CLEAN" ] && break
  echo "mergeState=$ms (attente)"; sleep 30
done
head_branch=$(gh pr view $PR -R $REPO --json headRefName --jq '.headRefName')
if gh pr merge $PR -R $REPO --squash --delete-branch; then
  echo "PR $PR MERGEE"
  # Ce qui crée détruit (I-243) : teardown de la lane ET de sa revue,
  # idempotent, jamais un geste manuel.
  if [[ "$head_branch" =~ ^(lane|revue)-[0-9]+$ ]]; then
    bash /c/Users/souhe/souffleur/tools/banc/circuit.sh nettoyer "$head_branch"
  else
    echo "branche $head_branch : pas au format strict lane-NNN/revue-NNN, circuit.sh nettoyer sauté"
  fi
  bash /c/Users/souhe/souffleur/tools/banc/circuit.sh nettoyer "revue-$PR"
else
  echo "ECHEC MERGE"
fi
git -C C:/Users/souhe/souffleur pull --ff-only 2>&1 | tail -3
echo "=== FIN ==="
