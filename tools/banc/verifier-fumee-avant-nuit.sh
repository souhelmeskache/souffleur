#!/bin/bash
# tools/banc/verifier-fumee-avant-nuit.sh — verdict MÉCANIQUE du run de fumée
# lancé par nuit.cmd avant toute nuit (#313, décision Souhel 06/09, I-468
# point 3) : « le banc se prouve sur lui-même avant de mesurer le jeu ».
# nuit.cmd lance d'abord tools/banc/nuit.sh pour une paire, 3 tours, Director
# sonnet, dans un -RunDir dédié (jamais bench/nuit-<date>/, cf. #309) — ce
# script en lit ensuite le résultat et rend le verdict, aucun LLM, aucun
# jugement narratif, extrait pour être testable indépendamment d'un vrai run
# herdr/claude (même discipline que verifier-agents-en-vol.sh /
# verifier-workspace-banc-vide.sh).
#
# Un craquement de tour (timeout, sortie de processus, prose absente/
# polluée — voir tools/banc/nuit.sh § arbitrage de prose) laisse un
# `craquement-*.md` dans partie-01/ et interrompt la boucle de tours avant
# d'écrire les prose-NN.md suivants : détecter l'un OU l'autre suffit à
# couvrir les trois craquements cités par #313, sans avoir besoin de les
# distinguer ici.
#
# Usage : tools/banc/verifier-fumee-avant-nuit.sh <run-dir> [tours attendus, défaut 3]
# Sortie 0 (« OK : ... ») si partie-01/ porte <tours> prose-NN.md non vides
# ET aucun craquement-*.md ; sortie 1 et message REFUS sinon.
set -u

RUN_DIR="${1:-}"
TOURS="${2:-3}"

refus() {
  echo "REFUS : $1" >&2
  exit 1
}

[ -n "$RUN_DIR" ] || refus "usage : $0 <run-dir> [tours]"
[[ "$TOURS" =~ ^[0-9]+$ ]] && [ "$TOURS" -ge 1 ] || refus "tours attendus doit être un entier >= 1 (reçu '$TOURS')."

PARTIE_DIR="$RUN_DIR/partie-01"
[ -d "$PARTIE_DIR" ] || refus "run de fumée : aucun dossier partie-01 dans $RUN_DIR (aucun tour joué)."

CRAQUEMENTS=("$PARTIE_DIR"/craquement-*.md)
if [ -e "${CRAQUEMENTS[0]}" ]; then
  NOMS=""
  for c in "${CRAQUEMENTS[@]}"; do NOMS="$NOMS $(basename "$c")"; done
  refus "run de fumée : le banc a craqué --$NOMS"
fi

n=1
while [ "$n" -le "$TOURS" ]; do
  NN="$(printf '%02d' "$n")"
  PROSE="$PARTIE_DIR/prose-$NN.md"
  [ -s "$PROSE" ] || refus "run de fumée : prose du tour $NN absente ou vide ($PROSE)."
  n=$((n + 1))
done

echo "OK : run de fumée concluant ($TOURS tours, prose non vide, aucun craquement)."
exit 0
