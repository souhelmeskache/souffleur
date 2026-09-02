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

# --- envoi à blanc des deux gabarits (#263) ---------------------------------
#
# tools/lancer-banc-fumee.ps1 envoie chaque gabarit rendu en un seul argument
# à `herdr agent prompt` (I-385, échappement Win32) — un `"` interne cassant
# cet échappement casse la nuit ENTIÈRE en silence (nuit N0 du 02/09 : 4
# parties/4 craquées au lancement, 0 tour joué). Envoi à blanc vers un agent
# qu'on sait inexistant AVANT de démarrer la nuit : seul `agent_not_found`
# (rc 1) est attendu (parsing OK, agent introuvable — normal). Tout rc 2
# (erreur de parsing herdr, ex. `unknown option`) = échappement cassé =
# REFUS de la garde, la nuit ne démarre pas.
GARDE_ENVOI_PS1="$REPO_ROOT/tools/banc/verifier-envoi-gabarits.ps1"
GARDE_ENVOI_JSON="$(powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$GARDE_ENVOI_PS1" 2>&1)"
GARDE_ENVOI_RC=$?
if [ "$GARDE_ENVOI_RC" -ne 0 ]; then
  refus "envoi à blanc des gabarits en échec — $GARDE_ENVOI_JSON"
fi

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
