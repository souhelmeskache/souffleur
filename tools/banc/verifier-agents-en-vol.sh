#!/bin/bash
# tools/banc/verifier-agents-en-vol.sh — classe les agents « en vol » d'une
# sortie `herdr agent list`, extrait de verifier-avant-nuit.sh pour être
# testable indépendamment de herdr (#292).
#
# Direction Souhel du 05/09 (#292) : les parties de banc tournent désormais
# en parallèle des lanes de code — une lane `lane-*`/`revue-*` (circuit.sh)
# en vol n'est plus une anomalie et ne doit plus refuser la nuit. Seul un
# agent du BANC (`banc-mj*`/`banc-joueur*`) survivant entre réellement en
# collision (collision de nom au démarrage, #271/#282) et reste un REFUS.
#
# Usage : herdr agent list | tools/banc/verifier-agents-en-vol.sh
#         tools/banc/verifier-agents-en-vol.sh <fichier-sortie-herdr-agent-list>
#
# Sorties :
#   - agent(s) banc-mj*/banc-joueur* présent(s) : REFUS sur stderr, code 1.
#   - sinon, agent(s) lane-*/revue-* présent(s)  : AVERTISSEMENT sur stdout,
#     code 0 (la nuit démarre quand même).
#   - sinon                                       : rien, code 0.
set -u

ENTREE="${1:--}"
if [ "$ENTREE" = "-" ]; then
  SORTIE_HERDR="$(cat)"
else
  SORTIE_HERDR="$(cat "$ENTREE")"
fi

agents_banc_en_vol="$(printf '%s' "$SORTIE_HERDR" | tr '{' '\n' \
  | grep -oE '"name":"banc-(mj|joueur)(-[0-9]+)?"' | sort -u | tr '\n' ' ')"
if [ -n "$agents_banc_en_vol" ]; then
  echo "REFUS : agent(s) du banc déjà en vol : $agents_banc_en_vol — ferme-les (herdr pane close / /exit) avant de relancer une nuit." >&2
  exit 1
fi

agents_lane_en_vol="$(printf '%s' "$SORTIE_HERDR" | tr '{' '\n' \
  | grep -oE '"name":"(lane|revue)-[0-9]+"' | sort -u | tr '\n' ' ')"
if [ -n "$agents_lane_en_vol" ]; then
  nb="$(printf '%s\n' $agents_lane_en_vol | grep -c .)"
  echo "AVERTISSEMENT : $nb lane(s) en vol : $agents_lane_en_vol — une lane de code en vol n'entre pas en collision avec la nuit (#292), la nuit démarre quand même."
fi

exit 0
