#!/bin/bash
# tools/banc/verifier-workspace-banc-vide.sh — classe les workspaces herdr
# "banc*" d'une sortie `herdr workspace list`, extrait de
# verifier-avant-nuit.sh pour être testable indépendamment de herdr (#298).
#
# Le workspace herdr dédié au banc (label "banc" ou "banc-<date>",
# tools/lancer-banc-fumee.ps1) porte toujours au moins un pane (le pane
# ancre créé avec le workspace) — un pane_count > 1 signale qu'un pane
# MJ/joueur y est encore ouvert : une partie survivante d'une nuit
# précédente, que nuit.sh est censé avoir fermée à sa propre fin
# (finaliser_nuit -> fermer_panes_workspace_banc).
#
# Usage : herdr workspace list | tools/banc/verifier-workspace-banc-vide.sh
#         tools/banc/verifier-workspace-banc-vide.sh <fichier-sortie-herdr-workspace-list>
#
# Sorties :
#   - workspace(s) "banc*" avec pane_count > 1 : REFUS sur stderr, code 1.
#   - sinon                                     : rien, code 0.
set -u

ENTREE="${1:--}"
if [ "$ENTREE" = "-" ]; then
  SORTIE_HERDR="$(cat)"
else
  SORTIE_HERDR="$(cat "$ENTREE")"
fi

NON_VIDE="$(printf '%s' "$SORTIE_HERDR" | python -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for w in d.get("result", {}).get("workspaces", []) or []:
    label = w.get("label", "")
    if label.startswith("banc") and (w.get("pane_count") or 0) > 1:
        print(label + " (" + str(w.get("pane_count")) + " panes)")
')"

if [ -n "$NON_VIDE" ]; then
  echo "REFUS : workspace(s) banc non vide(s), partie survivante (#298) : $(printf '%s' "$NON_VIDE" | tr '\n' ' ') — ferme les panes (herdr pane close) avant de relancer une nuit." >&2
  exit 1
fi

exit 0
