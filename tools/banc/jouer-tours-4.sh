#!/bin/bash
# Boucle de tours du banc — fil 2, avec DETECTION D'AGENT BLOQUE.
# Sort (et reveille donc la session de controle) sur : lot fini, agent bloque,
# nouveau craquement, timeout, ou fichier PAUSE.
J="C:/Users/souhe/souffleur/bench/banc-fumee/20260831-202617"
SCRATCH="C:/Users/souhe/AppData/Local/Temp/claude/C--Vaults-MVP2-meta-rpg/748da970-dfac-4c86-8929-a9a5f1fa7bc8/scratchpad"
DEBUT=${1:-22}
FIN=${2:-25}
POLL=20
TIMEOUT_POLLS=${3:-45}
CRAQ0=$(ls "$J" | grep -ci "^craquement")

# codes : 0 produit · 2 agent bloque · 3 craquement · 4 timeout · 5 pause
attendre() {
  local f="$1" n=0
  while [ ! -s "$f" ]; do
    n=$((n+1))
    [ "$n" -gt "$TIMEOUT_POLLS" ] && { echo "TIMEOUT sur $(basename $f)"; return 4; }
    [ -f "$SCRATCH/PAUSE" ] && { echo "PAUSE demandee"; return 5; }
    c=$(ls "$J" | grep -ci "^craquement")
    [ "$c" -gt "$CRAQ0" ] && { echo "NOUVEAU CRAQUEMENT"; return 3; }
    if herdr agent list 2>/dev/null | tr ',' '\n' | grep -q 'agent_status":"blocked'; then
      sleep 10
      if herdr agent list 2>/dev/null | tr ',' '\n' | grep -q 'agent_status":"blocked'; then
        echo "AGENT BLOQUE (prompt de permission ?) en attendant $(basename $f)"
        return 2
      fi
    fi
    sleep $POLL
  done
  return 0
}

for N in $(seq "$DEBUT" "$FIN"); do
  NN=$(printf '%02d' "$N")
  PN=$(printf '%02d' $((N-1)))
  [ -f "$SCRATCH/PAUSE" ] && { echo "PAUSE avant le tour $NN"; exit 5; }
  echo "=== TOUR $NN — go joueur $(date '+%H:%M:%S')"
  herdr agent prompt banc-joueur "go — tour $NN : lis UNIQUEMENT $J/prose-$PN.md, joue ton tour (un paragraphe), puis ecris-le verbatim dans $J/action-$NN.md" >/dev/null 2>&1
  attendre "$J/action-$NN.md"; r=$?
  [ $r -ne 0 ] && { echo "ARRET au tour $NN (code $r) en attente de l'action"; exit $r; }
  ACTION=$(cat "$J/action-$NN.md")
  echo "--- action recue $(date '+%H:%M:%S')"
  herdr agent prompt banc-mj "go — tour $NN. Action du joueur (verbatim) : $ACTION" >/dev/null 2>&1
  attendre "$J/prose-$NN.md"; r=$?
  [ $r -ne 0 ] && { echo "ARRET au tour $NN (code $r) en attente de la prose"; exit $r; }
  echo "=== TOUR $NN joue $(date '+%H:%M:%S')"
done
echo "LOT $DEBUT-$FIN TERMINE"
