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
SAVE="${1:-banc-depart-beyond-the-vale-of-madness}"

source "$REPO_ROOT/tools/banc/chemin-windows.sh"

refus() {
  echo "REFUS : $1" >&2
  exit 1
}

command -v herdr >/dev/null 2>&1 || refus "herdr introuvable dans le PATH."
herdr workspace list >/dev/null 2>&1 || refus "herdr injoignable (herdr workspace list a échoué)."
command -v claude >/dev/null 2>&1 || refus "claude introuvable dans le PATH."
command -v gh >/dev/null 2>&1 || refus "gh introuvable dans le PATH."

# --- liste blanche du banc complète (#267) ----------------------------------
#
# tools/lancer-banc-fumee.ps1 GARANTIT désormais la liste blanche d'un
# .claude/settings.local.json déjà présent (fusion des entrées manquantes,
# #267) au lieu de le laisser tel quel — mais cette garde tourne AVANT le
# lanceur : si le fichier existe déjà et n'a pas encore été complété (ex.
# posé à la main, ou par un ancien correctif #210/#224 plus étroit), la nuit
# ne doit pas démarrer avec une liste blanche incomplète (constat nuit N0,
# 02/09 : agents bloqués sur demande de permission jusqu'au timeout).
#
# Vérification déléguée à verifier-liste-blanche-nuit.sh (extrait pour être
# testable indépendamment de herdr/gh/claude — tests/verifier_liste_blanche_nuit_test.py).
GARDE_LISTE_BLANCHE_SORTIE="$("$REPO_ROOT/tools/banc/verifier-liste-blanche-nuit.sh" "$REPO_ROOT/.claude/settings.local.json" 2>&1)"
GARDE_LISTE_BLANCHE_RC=$?
if [ "$GARDE_LISTE_BLANCHE_RC" -ne 0 ]; then
  refus "${GARDE_LISTE_BLANCHE_SORTIE#REFUS : }"
fi

SAVE_SRC="$(cd "$REPO_ROOT" && python -c "
import sys
sys.path.insert(0, '.')
from coderain.config import saves_dir
print(saves_dir())
" 2>/dev/null)/$SAVE"
[ -d "$SAVE_SRC" ] || refus "save '$SAVE' introuvable ($SAVE_SRC)."

# --- save de DÉPART gelée, tour 0 (#275/I-465) ------------------------------
#
# Une nuit ne joue jamais une partie en cours : la save source doit être au
# tour 0 (transcript.md vierge), fabriquée par tools/banc/save-depart.py.
# Même garde que nuit.sh (Issue #275) — vérifiée ici AUSSI pour échouer tôt,
# avant même de tenter un lancement.
SAVE_SRC_WIN="$(chemin_windows_depuis_bash "$SAVE_SRC")"
NB_TOURS_SAVE="$(cd "$REPO_ROOT" && python -c "
import sys
sys.path.insert(0, '.')
from coderain.memory import MemoryStore
print(len(MemoryStore(r'$SAVE_SRC_WIN').turns()))
" 2>/dev/null)"
[[ "$NB_TOURS_SAVE" =~ ^[0-9]+$ ]] || refus "impossible de lire le nombre de tours de la save '$SAVE' ($SAVE_SRC)."
[ "$NB_TOURS_SAVE" -eq 0 ] || refus "la save '$SAVE' est au tour $NB_TOURS_SAVE, une nuit ne joue qu'une save de départ (tour 0)."

# --- module installé, pas un monde vide (#281, à côté de la garde tour 0) ---
#
# `save-depart.py` installe désormais la partition associée (module.json +
# lieux/PNJ projetés) — REFUS si la save n'a pas de module.json ou si ses
# lieux sont au gabarit vide (fabriquée avant #281, ou par un autre chemin).
MODULE_OK="$(cd "$REPO_ROOT" && python -c "
import sys, json
sys.path.insert(0, '.')
from coderain.memory import MemoryStore
save_dir = r'$SAVE_SRC_WIN'
try:
    json.load(open(save_dir + '/module.json', encoding='utf-8'))
    nb_lieux = len(MemoryStore(save_dir).entries('locations.md'))
    print(1 if nb_lieux > 0 else 0)
except Exception:
    print(0)
" 2>/dev/null)"
[ "$MODULE_OK" = "1" ] || refus "la save '$SAVE' n'a pas de module installé, une nuit ne joue pas un monde vide."

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

# --- rien en vol : lane(s) en avertissement, agent(s) du banc en REFUS -----
#
# Direction Souhel du 05/09 (#292) : une lane `lane-*`/`revue-*` (circuit.sh)
# en vol est l'état normal du poste, le jour comme la nuit — elle vit dans
# son propre worktree et ses agents portent d'autres noms ; elle n'entre
# plus en collision avec une nuit et n'est plus refusée, seulement signalée.
# Seul un banc-mj/banc-joueur (ou leur forme suffixée par paire
# "banc-mj-NN", nuit.sh -Paires > 1, #282) survivant d'une nuit précédente
# entre réellement en collision : `herdr agent start` de la nuit qui démarre
# échouerait par collision de nom (#271, déjà constaté en séquentiel) —
# refusé ICI, avant tout lancement, plutôt que de laisser chaque partie
# craquer une à une au lancement. Classification déléguée à
# verifier-agents-en-vol.sh (extrait pour être testable indépendamment de
# herdr — tests/verifier_agents_en_vol_test.py).
SORTIE_AGENTS_EN_VOL="$(herdr agent list 2>/dev/null | "$REPO_ROOT/tools/banc/verifier-agents-en-vol.sh" 2>&1)"
AGENTS_EN_VOL_RC=$?
if [ "$AGENTS_EN_VOL_RC" -ne 0 ]; then
  refus "${SORTIE_AGENTS_EN_VOL#REFUS : }"
fi
[ -z "$SORTIE_AGENTS_EN_VOL" ] || echo "$SORTIE_AGENTS_EN_VOL"

# --- workspace(s) banc non vide(s) : partie survivante (#298) ---------------
#
# Classification déléguée à verifier-workspace-banc-vide.sh (extrait pour
# être testable indépendamment de herdr, même discipline que
# verifier-agents-en-vol.sh, #292).
SORTIE_WORKSPACE_BANC="$(herdr workspace list 2>/dev/null | "$REPO_ROOT/tools/banc/verifier-workspace-banc-vide.sh" 2>&1)"
WORKSPACE_BANC_RC=$?
if [ "$WORKSPACE_BANC_RC" -ne 0 ]; then
  refus "${SORTIE_WORKSPACE_BANC#REFUS : }"
fi

prs_ouvertes="$(gh pr list -R "$REPO" --json number --jq 'length' 2>/dev/null || echo '')"
if [ -n "$prs_ouvertes" ] && [ "$prs_ouvertes" != "0" ]; then
  refus "$prs_ouvertes PR ouverte(s) sur $REPO — circuit pas au repos."
fi

echo "OK : prérequis satisfaits, rien en vol (save '$SAVE')."
exit 0
