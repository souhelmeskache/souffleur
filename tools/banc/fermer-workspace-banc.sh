#!/bin/bash
# tools/banc/fermer-workspace-banc.sh — ferme TOUS les panes du workspace
# herdr dont le label est exactement <label>, jamais le workspace lui-même
# (#298). Extrait de nuit.sh (finaliser_nuit) pour être testable avec un
# faux `herdr` sur PATH, même discipline que les autres gardes du banc
# (verifier-agents-en-vol.sh, #292).
#
# Le workspace herdr dédié au banc (tools/lancer-banc-fumee.ps1) porte
# toujours au moins un pane (le pane ancre créé avec le workspace) ; ce
# script ferme aussi bien ce pane ancre que tout pane MJ/joueur résiduel —
# le workspace lui-même n'est JAMAIS fermé de force ici (pas de `herdr
# workspace close`, garde symétrique de circuit.sh nettoyer) : il ne
# disparaît que devenu vide, par la fermeture normale de ses panes.
#
# Usage : tools/banc/fermer-workspace-banc.sh <label>
#
# Absent (aucun workspace de ce label) ou déjà vide : sortie 0, silencieuse.
set -u

LABEL="${1:?Usage: $0 <label>}"

# workspace_id du workspace herdr dont le label est EXACTEMENT $1, vide si
# absent.
workspace_id_pour_label() {
  herdr workspace list 2>/dev/null | python -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
label = sys.argv[1]
for w in d.get("result", {}).get("workspaces", []) or []:
    if w.get("label") == label:
        print(w.get("workspace_id", ""))
        break
' "$1"
}

wsid="$(workspace_id_pour_label "$LABEL")"
[ -n "$wsid" ] || exit 0

panes="$(herdr pane list --workspace "$wsid" 2>/dev/null | python -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for p in d.get("result", {}).get("panes", []) or []:
    print(p.get("pane_id", ""))
')"
[ -n "$panes" ] || exit 0

while IFS= read -r p; do
  [ -n "$p" ] || continue
  herdr pane close "$p" >/dev/null 2>&1
done <<< "$panes"

exit 0
