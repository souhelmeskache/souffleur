#!/bin/bash
# circuit.sh — verbes de teardown du circuit de lane (I-243, ce qui crée détruit).
#
# Usage :
#   tools/banc/circuit.sh nettoyer <lane-NNN|revue-NNN>   # ferme workspace + worktree + branche d'UNE lane/revue
#   tools/banc/circuit.sh nettoyer --orphelins            # purge les dossiers de worktree morts (ni Git ni herdr)
#   tools/banc/circuit.sh etat                             # photo lisible : lanes en vol, PR, workspaces, worktrees, orphelins
#
# Toutes les étapes de "nettoyer" tolèrent l'absence de leur cible : sortie 0
# si tout est déjà propre. Aucune suppression n'a lieu hors de $WORKTREES_DIR.
set -u

REPO=souhelmeskache/souffleur
MAIN_REPO="C:/Users/souhe/souffleur"
WORKTREES_DIR="C:/Users/souhe/.herdr/worktrees/souffleur"

# --- utilitaires JSON (pas de jq sur ce poste) ------------------------------

# Liste "label<TAB>workspace_id" des workspaces herdr, un par ligne.
workspaces_labels() {
  herdr workspace list 2>/dev/null | python -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for w in d.get("result", {}).get("workspaces", []) or []:
    print(w.get("label", "") + "\t" + w.get("workspace_id", ""))
'
}

# workspace_id du label passé en $1, vide si absent.
workspace_id_for_label() {
  workspaces_labels | awk -F'\t' -v l="$1" '$1==l{print $2; exit}'
}

# --- garde de chemin ---------------------------------------------------------

# Vérifie que $1 est un sous-dossier direct de $WORKTREES_DIR (jamais le
# checkout principal, jamais un ancêtre) ; sortie 1 + message sinon.
verifier_chemin_sous_worktrees() {
  local chemin="$1"
  case "$chemin" in
    "$WORKTREES_DIR"/*) ;;
    *)
      echo "REFUS : chemin '$chemin' hors de $WORKTREES_DIR — rien supprimé." >&2
      return 1
      ;;
  esac
  return 0
}

# --- nettoyer <label> --------------------------------------------------------

nettoyer_une() {
  local label="$1"
  case "$label" in
    lane-*|revue-*) ;;
    *)
      echo "REFUS : '$label' n'est ni lane-NNN ni revue-NNN." >&2
      return 1
      ;;
  esac

  local dest="$WORKTREES_DIR/$label"
  verifier_chemin_sous_worktrees "$dest" || return 1

  echo "=== nettoyer $label ==="

  # 1. ferme le workspace herdr dont le label correspond, s'il existe.
  local wsid
  wsid=$(workspace_id_for_label "$label")
  if [ -n "$wsid" ]; then
    echo "  workspace herdr $wsid (label=$label) — fermeture"
    herdr workspace close "$wsid" >/dev/null 2>&1
    echo "  workspace fermé (ou déjà absent après appel)"
  else
    echo "  aucun workspace herdr pour label=$label — rien à fermer"
  fi

  # 2. attend que le dossier soit libéré (plus tenu par aucun workspace),
  #    boucle bornée 30s.
  if [ -d "$dest" ]; then
    local i
    for i in $(seq 1 30); do
      wsid=$(workspace_id_for_label "$label")
      [ -z "$wsid" ] && break
      sleep 1
    done
    if [ -n "$wsid" ]; then
      echo "  attention : workspace $wsid encore présent après 30s d'attente"
    fi
  fi

  # 3. git worktree remove --force
  if git -C "$MAIN_REPO" worktree remove --force "$dest" >/dev/null 2>&1; then
    echo "  worktree Git $dest retiré"
  else
    echo "  worktree Git $dest : déjà absent (ou déjà pas un worktree)"
  fi

  # 4. git branch -D
  if git -C "$MAIN_REPO" branch -D "$label" >/dev/null 2>&1; then
    echo "  branche $label supprimée"
  else
    echo "  branche $label : déjà absente"
  fi

  # 5. si le dossier existe encore et n'est plus dans `git worktree list` : le supprime.
  if [ -d "$dest" ]; then
    if git -C "$MAIN_REPO" worktree list --porcelain | grep -qF "worktree $dest"; then
      echo "  dossier $dest toujours référencé par git worktree list — non touché"
    else
      verifier_chemin_sous_worktrees "$dest" || return 1
      rm -rf "$dest"
      echo "  dossier résiduel $dest supprimé"
    fi
  else
    echo "  dossier $dest : déjà absent"
  fi

  # 6. git worktree prune
  git -C "$MAIN_REPO" worktree prune
  echo "=== $label : nettoyé ==="
  return 0
}

# --- nettoyer --orphelins ----------------------------------------------------

nettoyer_orphelins() {
  echo "=== nettoyer --orphelins ($WORKTREES_DIR) ==="
  if [ ! -d "$WORKTREES_DIR" ]; then
    echo "  $WORKTREES_DIR absent — rien à faire."
    return 0
  fi

  local git_paths
  git_paths=$(git -C "$MAIN_REPO" worktree list --porcelain | awk '/^worktree /{print $2}')
  local herdr_paths
  herdr_paths=$(herdr worktree list 2>/dev/null | python -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for w in d.get("result", {}).get("worktrees", []) or []:
    p = w.get("checkout_path") or w.get("path") or ""
    if p:
        print(p)
' 2>/dev/null)

  local trouve=0
  local d
  for d in "$WORKTREES_DIR"/*/; do
    [ -d "$d" ] || continue
    d="${d%/}"
    local nom
    nom=$(basename "$d")

    # tenu par git worktree list ?
    if echo "$git_paths" | grep -qiF "$d"; then
      continue
    fi
    # tenu par un workspace herdr (par label, garde-fou en plus du chemin) ?
    local wsid
    wsid=$(workspace_id_for_label "$nom")
    if [ -n "$wsid" ]; then
      continue
    fi
    # tenu par `herdr worktree list` (au cas où le label ne correspond pas au dossier) ?
    if [ -n "$herdr_paths" ] && echo "$herdr_paths" | grep -qiF "$d"; then
      continue
    fi

    verifier_chemin_sous_worktrees "$d" || continue
    echo "  orphelin : $d — suppression"
    rm -rf "$d"
    trouve=1
  done

  if [ "$trouve" -eq 0 ]; then
    echo "  rien à faire — aucun dossier orphelin."
  fi
  git -C "$MAIN_REPO" worktree prune
  echo "=== --orphelins : terminé ==="
  return 0
}

# --- etat ---------------------------------------------------------------------

etat() {
  echo "=== circuit : état ==="

  echo "--- lanes/revues en vol (herdr agent list) ---"
  local agents
  agents=$(herdr agent list 2>/dev/null | python -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for a in d.get("result", {}).get("agents", []) or []:
    n = a.get("name", "")
    if n.startswith("lane-") or n.startswith("revue-"):
        print(n + "\t" + a.get("agent_status", "?") + "\t" + a.get("cwd", ""))
')
  if [ -n "$agents" ]; then
    echo "$agents" | awk -F'\t' '{printf "  %-14s statut=%-10s %s\n", $1, $2, $3}'
  else
    echo "  (aucune)"
  fi

  echo "--- PR ouvertes ---"
  local prs
  prs=$(gh pr list -R "$REPO" --json number,headRefName,mergeStateStatus 2>/dev/null \
    | python -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for p in d or []:
    print("  PR #" + str(p.get("number")) + "\tbranche=" + str(p.get("headRefName")) + "\tmergeState=" + str(p.get("mergeStateStatus")))
')
  if [ -n "$prs" ]; then
    echo -e "$prs"
  else
    echo "  (aucune)"
  fi

  echo "--- workspaces herdr ---"
  local ws
  ws=$(workspaces_labels)
  if [ -n "$ws" ]; then
    echo "$ws" | awk -F'\t' '{printf "  label=%-14s workspace_id=%s\n", $1, $2}'
  else
    echo "  (aucun)"
  fi

  echo "--- worktrees Git ---"
  git -C "$MAIN_REPO" worktree list | sed 's/^/  /'

  echo "--- orphelins ($WORKTREES_DIR) ---"
  if [ ! -d "$WORKTREES_DIR" ]; then
    echo "  ($WORKTREES_DIR absent)"
  else
    local git_paths herdr_paths trouve=0 d nom wsid
    git_paths=$(git -C "$MAIN_REPO" worktree list --porcelain | awk '/^worktree /{print $2}')
    herdr_paths=$(herdr worktree list 2>/dev/null | python -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for w in d.get("result", {}).get("worktrees", []) or []:
    p = w.get("checkout_path") or w.get("path") or ""
    if p:
        print(p)
' 2>/dev/null)
    for d in "$WORKTREES_DIR"/*/; do
      [ -d "$d" ] || continue
      d="${d%/}"
      nom=$(basename "$d")
      echo "$git_paths" | grep -qiF "$d" && continue
      wsid=$(workspace_id_for_label "$nom")
      [ -n "$wsid" ] && continue
      [ -n "$herdr_paths" ] && echo "$herdr_paths" | grep -qiF "$d" && continue
      echo "  orphelin : $d"
      trouve=1
    done
    [ "$trouve" -eq 0 ] && echo "  (aucun)"
  fi

  echo "=== fin état ==="
  return 0
}

# --- dispatch -----------------------------------------------------------------

case "${1:-}" in
  nettoyer)
    case "${2:-}" in
      --orphelins) nettoyer_orphelins ;;
      lane-*|revue-*) nettoyer_une "$2" ;;
      *)
        echo "Usage : $0 nettoyer <lane-NNN|revue-NNN>" >&2
        echo "        $0 nettoyer --orphelins" >&2
        exit 1
        ;;
    esac
    ;;
  etat)
    etat
    ;;
  *)
    echo "Usage : $0 nettoyer <lane-NNN|revue-NNN>|--orphelins" >&2
    echo "        $0 etat" >&2
    exit 1
    ;;
esac
