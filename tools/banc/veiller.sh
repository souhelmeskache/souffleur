#!/bin/bash
# Veille sur l'apparition d'un fichier du journal, sans envoyer de go.
# Sort sur : fichier produit (0) · agent bloque (2) · craquement neuf (3) · timeout (4) · pause (5)
J="C:/Users/souhe/souffleur/bench/banc-fumee/20260831-202617"
SCRATCH="C:/Users/souhe/AppData/Local/Temp/claude/C--Vaults-MVP2-meta-rpg/748da970-dfac-4c86-8929-a9a5f1fa7bc8/scratchpad"
CIBLE="$1"
TIMEOUT_POLLS=${2:-30}
CRAQ0=$(ls "$J" | grep -ci "^craquement")
n=0
while [ ! -s "$J/$CIBLE" ]; do
  n=$((n+1))
  [ "$n" -gt "$TIMEOUT_POLLS" ] && { echo "TIMEOUT sur $CIBLE"; exit 4; }
  [ -f "$SCRATCH/PAUSE" ] && { echo "PAUSE demandee"; exit 5; }
  c=$(ls "$J" | grep -ci "^craquement")
  [ "$c" -gt "$CRAQ0" ] && { echo "NOUVEAU CRAQUEMENT"; ls "$J" | grep -i "^craquement"; exit 3; }
  if herdr agent list 2>/dev/null | tr ',' '\n' | grep -q 'agent_status":"blocked'; then
    sleep 10
    if herdr agent list 2>/dev/null | tr ',' '\n' | grep -q 'agent_status":"blocked'; then
      echo "AGENT BLOQUE en attendant $CIBLE"; exit 2
    fi
  fi
  sleep 20
done
echo "$CIBLE produit $(date '+%H:%M:%S')"
