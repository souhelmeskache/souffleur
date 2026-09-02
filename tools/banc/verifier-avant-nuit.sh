#!/bin/bash
# tools/banc/verifier-avant-nuit.sh — garde avant de lancer une nuit (#260,
# complément cadrage nuit.cmd) : prérequis (herdr joignable, claude/gh
# présents, save présente) + « rien en vol » (aucun agent lane-*/revue-* de
# circuit.sh, aucune PR ouverte sur le dépôt). Sortie non nulle et message
# clair sur REFUS — jamais un lancement à l'aveugle.
#
# Usage : tools/banc/verifier-avant-nuit.sh [save-slug]
set -u

REPO=souhelmeskache/souffleur
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SAVE="${1:-beyond-the-vale-of-madness}"

refus() {
  echo "REFUS : $1" >&2
  exit 1
}

command -v herdr >/dev/null 2>&1 || refus "herdr introuvable dans le PATH."
herdr workspace list >/dev/null 2>&1 || refus "herdr injoignable (herdr workspace list a échoué)."
command -v claude >/dev/null 2>&1 || refus "claude introuvable dans le PATH."
command -v gh >/dev/null 2>&1 || refus "gh introuvable dans le PATH."

SAVE_SRC="$(cd "$REPO_ROOT" && python -c "
import sys
sys.path.insert(0, '.')
from coderain.config import saves_dir
print(saves_dir())
" 2>/dev/null)/$SAVE"
[ -d "$SAVE_SRC" ] || refus "save '$SAVE' introuvable ($SAVE_SRC)."

# --- rien en vol : agents lane-*/revue-* (circuit.sh), PR ouvertes ---------
agents_en_vol="$(herdr agent list 2>/dev/null | tr '{' '\n' \
  | grep -oE '"name":"(lane|revue)-[0-9]+"' | sort -u | tr '\n' ' ')"
[ -z "$agents_en_vol" ] || refus "agent(s) de circuit en vol : $agents_en_vol — attends la fin ou nettoie (circuit.sh nettoyer)."

prs_ouvertes="$(gh pr list -R "$REPO" --json number --jq 'length' 2>/dev/null || echo '')"
if [ -n "$prs_ouvertes" ] && [ "$prs_ouvertes" != "0" ]; then
  refus "$prs_ouvertes PR ouverte(s) sur $REPO — circuit pas au repos."
fi

echo "OK : prérequis satisfaits, rien en vol (save '$SAVE')."
exit 0
