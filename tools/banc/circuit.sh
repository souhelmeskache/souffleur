#!/bin/bash
# circuit.sh — point d'entrée unique du circuit de lane (I-243/#255).
#
# Usage :
#   tools/banc/circuit.sh lancer <ISSUE> [modele] [effort] # lance une lane (enveloppe lancer-lane.ps1)
#   tools/banc/circuit.sh veiller <ISSUE>                   # veille de circuit, toutes phases jusqu'au merge
#   tools/banc/circuit.sh revoir <PR>                       # lance une lane de revue adversariale sur une PR
#   tools/banc/circuit.sh nettoyer <lane-NNN|revue-NNN>     # ferme workspace + worktree + branche d'UNE lane/revue
#   tools/banc/circuit.sh nettoyer --orphelins              # purge les dossiers de worktree morts (ni Git ni herdr)
#   tools/banc/circuit.sh etat                              # photo lisible : lanes en vol, PR, workspaces, worktrees, orphelins
#   tools/banc/circuit.sh garde                             # garde core.bare (#231), rejouable seule
#
# Toutes les étapes de "nettoyer" tolèrent l'absence de leur cible : sortie 0
# si tout est déjà propre. Aucune suppression n'a lieu hors de $WORKTREES_DIR.
set -u

REPO=souhelmeskache/souffleur
MAIN_REPO="C:/Users/souhe/souffleur"
WORKTREES_DIR="C:/Users/souhe/.herdr/worktrees/souffleur"
LANCEUR="C:/Users/souhe/souffleur/tools/lancer-lane.ps1"
CORE_BARE_LOG="$MAIN_REPO/tools/banc/core-bare.log"

# Imprime l'aide des six verbes — appelée sans argument ou sur verbe inconnu.
usage() {
  cat >&2 <<EOF
Usage :
  $0 lancer <ISSUE> [modele] [effort]   # lance une lane (enveloppe lancer-lane.ps1)
  $0 veiller <ISSUE>                    # veille de circuit, toutes phases jusqu'au merge
  $0 revoir <PR>                        # lance une lane de revue adversariale sur une PR
  $0 nettoyer <lane-NNN|revue-NNN>      # ferme workspace + worktree + branche d'UNE lane/revue
  $0 nettoyer --orphelins               # purge les dossiers de worktree morts (ni Git ni herdr)
  $0 etat                               # photo lisible du circuit
  $0 garde                              # garde core.bare (#231), rejouable seule
EOF
}

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
# checkout principal, jamais un ancêtre) ; sortie 1 + message sinon. Résout
# le chemin (realpath -m — fonctionne même si la cible n'existe pas encore)
# avant le test de préfixe : un label ou un dossier contenant des segments
# ".." ne doit jamais pouvoir remonter hors de $WORKTREES_DIR (REVUE #247).
verifier_chemin_sous_worktrees() {
  local chemin="$1"
  local resolu resolu_racine
  resolu=$(realpath -m -- "$chemin") || {
    echo "REFUS : impossible de résoudre le chemin '$chemin' — rien supprimé." >&2
    return 1
  }
  resolu_racine=$(realpath -m -- "$WORKTREES_DIR") || {
    echo "REFUS : impossible de résoudre $WORKTREES_DIR — rien supprimé." >&2
    return 1
  }
  case "$resolu" in
    "$resolu_racine"/*) ;;
    *)
      echo "REFUS : chemin '$chemin' (résolu '$resolu') hors de $resolu_racine — rien supprimé." >&2
      return 1
      ;;
  esac
  return 0
}

# --- nettoyer <label> --------------------------------------------------------

nettoyer_une() {
  local label="$1"
  # Validation stricte (pas un simple préfixe glob) : un label du genre
  # "lane-1/../../.." matcherait "lane-*" mais remonterait hors de
  # $WORKTREES_DIR une fois concaténé à $dest — refusé ici avant toute
  # construction de chemin (REVUE #247).
  if ! [[ "$label" =~ ^(lane|revue)-[0-9]+$ ]]; then
    echo "REFUS : '$label' n'est pas au format strict lane-NNN ou revue-NNN." >&2
    return 1
  fi

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
    if git -C "$MAIN_REPO" worktree list --porcelain | grep -qxF "worktree $dest"; then
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

    # tenu par git worktree list ? (ligne entière — un chemin ne doit pas
    # matcher comme simple sous-chaîne d'un autre, ex. lane-1 dans lane-11)
    if echo "$git_paths" | grep -qixF "$d"; then
      continue
    fi
    # tenu par un workspace herdr (par label, garde-fou en plus du chemin) ?
    local wsid
    wsid=$(workspace_id_for_label "$nom")
    if [ -n "$wsid" ]; then
      continue
    fi
    # tenu par `herdr worktree list` (au cas où le label ne correspond pas au dossier) ?
    if [ -n "$herdr_paths" ] && echo "$herdr_paths" | grep -qixF "$d"; then
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
      echo "$git_paths" | grep -qixF "$d" && continue
      wsid=$(workspace_id_for_label "$nom")
      [ -n "$wsid" ] && continue
      [ -n "$herdr_paths" ] && echo "$herdr_paths" | grep -qixF "$d" && continue
      echo "  orphelin : $d"
      trouve=1
    done
    [ "$trouve" -eq 0 ] && echo "  (aucun)"
  fi

  echo "=== fin état ==="
  return 0
}

# --- veiller <issue> ----------------------------------------------------------
#
# UN watcher par circuit de lane, toutes phases (I-250) : attente de la PR,
# CI verte, revue fraîche, merge sur APPROUVE, renvoi automatique du verdict
# à la lane sur REFUS (au plus 2 cycles), signalement d'agent bloqué. Le
# journal du circuit vit sur l'Issue (commentaires), jamais dans un
# scratchpad — voir journal_sortie ci-dessous et tools/banc/README.md.
#
# Codes de sortie : 0 succès (merge fait, ou issue déjà soldée — rejeu
# idempotent) ; 1 CI rouge / verdict de revue absent ou en timeout / échec du
# merge ; 2 agent lane-<issue> bloqué (2 relevés de suite) ; 3 90 min sans
# changement de phase ; 4 REFUS persistant (3e cycle de refus).

# Parseur de verdict de revue : lit le corps d'un commentaire "REVUE : ..."
# sur stdin (première ligne), imprime APPROUVE, REFUS ou ABSENT.
parser_verdict() {
  local head
  head=$(head -1)
  case "$head" in
    "REVUE : APPROUVE"*) echo "APPROUVE" ;;
    "REVUE : REFUS"*) echo "REFUS" ;;
    *) echo "ABSENT" ;;
  esac
}

# Parseur de commentaire TERMINÉ : lit le corps sur stdin, imprime le numéro
# de PR extrait de la dernière URL /pull/NNN qu'il contient (vide si aucune).
parser_termine_pr() {
  grep -oE '/pull/[0-9]+' | grep -oE '[0-9]+' | tail -1
}

# PR déjà mergée pour cette issue (closingIssuesReferences), vide si aucune —
# base du rejeu idempotent.
pr_mergee_pour_issue() {
  local issue="$1"
  gh pr list -R "$REPO" --state merged --json number,closingIssuesReferences \
    --jq "[.[] | select(.closingIssuesReferences[]?.number == $issue)] | .[0].number // empty" 2>/dev/null
}

# PR ouverte pour cette issue : branche lane-<issue>, puis
# closingIssuesReferences, puis dernier commentaire TERMINÉ de l'issue
# (même ordre que l'ancien solder-issue.sh — vécu sur #220 et #226 : la PR
# n'a pas toujours la branche lane-<issue>).
pr_ouverte_pour_issue() {
  local issue="$1" pr
  pr=$(gh pr list -R "$REPO" --head "lane-$issue" --state open --json number --jq '.[0].number // empty')
  if [ -n "$pr" ]; then echo "$pr"; return 0; fi
  pr=$(gh pr list -R "$REPO" --state open --json number,closingIssuesReferences \
    --jq "[.[] | select(.closingIssuesReferences[]?.number == $issue)] | .[0].number // empty")
  if [ -n "$pr" ]; then echo "$pr"; return 0; fi
  gh issue view "$issue" -R "$REPO" --json comments \
    --jq '[.comments[] | select(.body | startswith("TERMIN")) | .body] | last // empty' \
    | parser_termine_pr
}

# "1" si l'agent lane-<issue> est bloqué, vide sinon.
agent_lane_bloque() {
  local issue="$1"
  herdr agent list 2>/dev/null | tr '{' '\n' | grep "\"name\":\"lane-$issue\"" | grep -q 'agent_status":"blocked' && echo 1
}

# Vrai (code 0) si l'agent lane-<issue> apparaît dans `herdr agent list`,
# quel que soit son statut — "lane vivante" au sens de #280 : encore là pour
# recevoir un renvoi de verdict (CI rouge ou REFUS de revue), par opposition
# à une lane disparue (workspace fermé, agent jamais démarré/déjà terminé).
agent_lane_vivante() {
  local issue="$1"
  herdr agent list 2>/dev/null | tr '{' '\n' | grep -q "\"name\":\"lane-$issue\""
}

# Identifiant du dernier run CI (workflow) de la branche de la PR $1, pour le
# message de renvoi "lis `gh run view <id> --log-failed`" (#280). Vide si
# indisponible — le message le mentionne alors sans planter dessus.
obtenir_run_id_ci() {
  local pr="$1" head_branch
  head_branch=$(gh pr view "$pr" -R "$REPO" --json headRefName --jq '.headRefName' 2>/dev/null)
  [ -n "$head_branch" ] || return 0
  gh run list -R "$REPO" --branch "$head_branch" -L 1 --json databaseId --jq '.[0].databaseId // empty' 2>/dev/null
}

# Poste "VEILLE <issue> : <code> <raison> <phase>" en commentaire de l'Issue
# (le journal du circuit vit sur l'Issue, jamais un scratchpad), puis quitte
# avec ce code. Sortie 0 : pas de ligne de journal, ce n'est pas un échec.
journal_sortie() {
  local issue="$1" code="$2" raison="$3" phase="$4"
  if [ "$code" != "0" ]; then
    gh issue comment "$issue" -R "$REPO" --body "VEILLE $issue : $code $raison $phase"
  fi
  exit "$code"
}

# Phase 1 (attente_pr) : attend la PR de l'issue. Sort du sous-programme par
# return, jamais exit — appelée par affectation directe (pas de $(...) pour
# les branches qui sortent), pour que la sortie du script reste possible.
# Succès : $_PR posé, return 0. Bloqué 2 relevés : $_BLOQUE_EXTRAIT posé,
# return 2. 90 min sans PR : return 3.
attendre_pr() {
  local issue="$1" pr nb=0 i
  for i in $(seq 1 180); do
    pr=$(pr_ouverte_pour_issue "$issue")
    if [ -n "$pr" ]; then _PR="$pr"; return 0; fi
    if [ -n "$(agent_lane_bloque "$issue")" ]; then
      nb=$((nb+1))
      if [ "$nb" -ge 2 ]; then
        _BLOQUE_EXTRAIT=$(herdr agent read "lane-$issue" --lines 20 2>/dev/null)
        return 2
      fi
    else
      nb=0
    fi
    echo "$(date '+%H:%M:%S') #$issue : pas de PR encore"
    sleep 30
  done
  return 3
}

# Phase 5, second temps (attente_termine) : après renvoi du verdict de REFUS,
# attend un nouveau commentaire TERMINÉ posté après l'appel. Mêmes codes de
# retour qu'attendre_pr (0/2/3), pas de $_PR à poser (PR inchangée).
attendre_termine() {
  local issue="$1" t0 c nb=0 i
  t0=$(date -u "+%Y-%m-%dT%H:%M:%SZ")
  for i in $(seq 1 180); do
    c=$(gh issue view "$issue" -R "$REPO" --json comments --jq "[.comments[] | select(.createdAt > \"$t0\") | select(.body | startswith(\"TERMIN\"))] | length")
    if [ -n "$c" ] && [ "$c" != "0" ]; then return 0; fi
    if [ -n "$(agent_lane_bloque "$issue")" ]; then
      nb=$((nb+1))
      if [ "$nb" -ge 2 ]; then
        _BLOQUE_EXTRAIT=$(herdr agent read "lane-$issue" --lines 20 2>/dev/null)
        return 2
      fi
    else
      nb=0
    fi
    echo "$(date '+%H:%M:%S') #$issue : pas de TERMINÉ depuis $t0"
    sleep 30
  done
  return 3
}

# Phase 2 (ci) : attend la CI de la PR. Return 0 verte, 1 rouge, 3 90 min.
attendre_ci() {
  local pr="$1" ck ms i
  for i in $(seq 1 180); do
    ck=$(gh pr view "$pr" -R "$REPO" --json statusCheckRollup --jq '[.statusCheckRollup[]? | (.conclusion // .state // "PENDING")] | join(",")')
    ms=$(gh pr view "$pr" -R "$REPO" --json mergeStateStatus --jq '.mergeStateStatus')
    echo "PR $pr mergeState=$ms checks=[$ck]"
    case "$ck" in
      *FAILURE*|*ERROR*|*CANCELLED*|*TIMED_OUT*) return 1 ;;
      *SUCCESS*) if [ "$ms" = "CLEAN" ] || [ "$ms" = "BLOCKED" ] || [ "$ms" = "UNSTABLE" ]; then return 0; fi ;;
    esac
    sleep 30
  done
  return 3
}

# Phase 3 (revue) : relance une revue fraîche (lancer-lane.ps1 -Revue) puis
# attend son verdict. Succès : $_VERDICT_BODY posé (corps complet du
# commentaire REVUE), return 0. 90 min sans verdict : return 3.
lancer_revue() {
  local pr="$1" t0 body i
  t0=$(date -u "+%Y-%m-%dT%H:%M:%SZ")
  echo "=== PR $pr : revue FRAICHE (T0=$t0) ==="
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$LANCEUR" -Revue "$pr" 2>&1 | tail -1
  for i in $(seq 1 180); do
    body=$(gh pr view "$pr" -R "$REPO" --json comments --jq "[.comments[] | select(.createdAt > \"$t0\") | select(.body | startswith(\"REVUE :\"))] | last // {} | .body // \"\"")
    if [ -n "$body" ]; then _VERDICT_BODY="$body"; return 0; fi
    sleep 30
  done
  return 3
}

# Phase 4 (merge) : merge squash + teardown lane/revue (circuit.sh nettoyer,
# I-243 — ce qui crée détruit) + pull --ff-only du checkout principal.
merger_et_nettoyer() {
  local pr="$1" i ms head_branch
  for i in $(seq 1 40); do
    ms=$(gh pr view "$pr" -R "$REPO" --json mergeStateStatus --jq '.mergeStateStatus')
    [ "$ms" = "CLEAN" ] && break
    echo "mergeState=$ms (attente)"; sleep 30
  done
  head_branch=$(gh pr view "$pr" -R "$REPO" --json headRefName --jq '.headRefName')
  if gh pr merge "$pr" -R "$REPO" --squash --delete-branch; then
    echo "PR $pr MERGEE"
    if [[ "$head_branch" =~ ^(lane|revue)-[0-9]+$ ]]; then
      nettoyer_une "$head_branch"
    else
      echo "branche $head_branch : pas au format strict lane-NNN/revue-NNN, nettoyer sauté"
    fi
    nettoyer_une "revue-$pr"
    git -C "$MAIN_REPO" pull --ff-only 2>&1 | tail -3
    return 0
  fi
  echo "ECHEC MERGE"
  return 1
}

# --- veiller : boucle principale ----------------------------------------------

veiller() {
  local issue="$1"
  [ -n "$issue" ] || { echo "Usage : $0 veiller <ISSUE>" >&2; exit 1; }

  # Rejeu idempotent (I-250) : issue déjà fermée, ou PR déjà mergée pour
  # cette issue -> sortie 0 immédiate, sans rien poster.
  local etat pr_deja
  etat=$(gh issue view "$issue" -R "$REPO" --json state --jq .state 2>/dev/null)
  if [ "$etat" = "CLOSED" ]; then
    echo "Issue #$issue déjà fermée — rien à faire."
    exit 0
  fi
  pr_deja=$(pr_mergee_pour_issue "$issue")
  if [ -n "$pr_deja" ]; then
    echo "PR #$pr_deja déjà mergée pour #$issue — rien à faire."
    exit 0
  fi

  echo "=== veiller #$issue : phase attente_pr ==="
  local _PR _BLOQUE_EXTRAIT _VERDICT_BODY
  attendre_pr "$issue"
  case $? in
    2) gh issue comment "$issue" -R "$REPO" --body "BLOQUÉ (watcher) : $_BLOQUE_EXTRAIT"
       journal_sortie "$issue" 2 "agent bloqué" "attente_pr" ;;
    3) journal_sortie "$issue" 3 "90 min sans PR" "attente_pr" ;;
  esac
  local pr="$_PR"
  echo "=== PR $pr trouvée pour #$issue ==="

  local cycle=0
  while :; do
    echo "=== veiller #$issue : phase ci (PR $pr) ==="
    attendre_ci "$pr"
    case $? in
      1)
        # CI rouge (#280) : ce n'est une sortie que si la lane est morte —
        # sinon c'est un verdict de plus à lui renvoyer, même compteur de
        # cycles que les REFUS de revue ci-dessous (2 max, puis sortie 4).
        if ! agent_lane_vivante "$issue"; then
          journal_sortie "$issue" 1 "CI rouge, lane absente" "ci"
        fi
        cycle=$((cycle+1))
        if [ "$cycle" -gt 2 ]; then
          journal_sortie "$issue" 4 "CI rouge persistante ($cycle cycles)" "ci"
        fi
        local run_id
        run_id=$(obtenir_run_id_ci "$pr")
        echo "=== veiller #$issue : CI rouge (cycle $cycle) — renvoi automatique à lane-$issue ==="
        herdr agent prompt "lane-$issue" "CI ROUGE sur la PR #$pr (run $run_id) : lis \`gh run view $run_id --log-failed\`, corrige, pousse, reposte TERMINÉ" >/dev/null 2>&1

        echo "=== veiller #$issue : phase attente_termine (CI rouge, cycle $cycle) ==="
        attendre_termine "$issue"
        case $? in
          2) gh issue comment "$issue" -R "$REPO" --body "BLOQUÉ (watcher) : $_BLOQUE_EXTRAIT"
             journal_sortie "$issue" 2 "agent bloqué" "attente_termine" ;;
          3) journal_sortie "$issue" 3 "90 min sans TERMINÉ après CI rouge" "attente_termine" ;;
        esac
        continue
        ;;
      3) journal_sortie "$issue" 3 "90 min sans CI verte" "ci" ;;
    esac

    echo "=== veiller #$issue : phase revue (PR $pr) ==="
    lancer_revue "$pr"
    [ $? -eq 0 ] || journal_sortie "$issue" 1 "timeout verdict de revue" "revue"
    local verdict
    verdict=$(echo "$_VERDICT_BODY" | parser_verdict)
    echo "PR $pr verdict : $verdict"

    if [ "$verdict" = "APPROUVE" ]; then
      echo "=== veiller #$issue : phase merge (PR $pr) ==="
      if merger_et_nettoyer "$pr"; then
        exit 0
      fi
      journal_sortie "$issue" 1 "échec du merge" "merge"
    fi

    if [ "$verdict" != "REFUS" ]; then
      journal_sortie "$issue" 1 "verdict de revue absent" "revue"
    fi

    # REFUS avec lane morte (#280, symétrique du cas CI ci-dessus, mesuré
    # sur #271 le 03/09) : inutile d'attendre 90 min un TERMINÉ impossible —
    # sortie immédiate, teardown de la revue quand même (ce qui crée détruit).
    if ! agent_lane_vivante "$issue"; then
      nettoyer_une "revue-$pr"
      journal_sortie "$issue" 1 "REFUS, lane absente — relancer un agent neuf sur le worktree avec le verdict" "revue"
    fi

    cycle=$((cycle+1))
    if [ "$cycle" -gt 2 ]; then
      journal_sortie "$issue" 4 "REFUS persistant ($cycle cycles)" "revue"
    fi

    echo "=== veiller #$issue : REFUS (cycle $cycle) — renvoi automatique du verdict à lane-$issue ==="
    herdr agent prompt "lane-$issue" "$_VERDICT_BODY — pousse puis poste un nouveau TERMINÉ" >/dev/null 2>&1
    nettoyer_une "revue-$pr"

    echo "=== veiller #$issue : phase attente_termine (cycle $cycle) ==="
    attendre_termine "$issue"
    case $? in
      2) gh issue comment "$issue" -R "$REPO" --body "BLOQUÉ (watcher) : $_BLOQUE_EXTRAIT"
         journal_sortie "$issue" 2 "agent bloqué" "attente_termine" ;;
      3) journal_sortie "$issue" 3 "90 min sans TERMINÉ après refus" "attente_termine" ;;
    esac
  done
}

# --- garde <core.bare> (I-231) -------------------------------------------------
#
# core.bare = true réapparaît dans .git/config du checkout principal (cause
# inconnue, #231) et casse tout worktree qui en dépend — geste manuel avant
# chaque lancement jusqu'ici. Vérifié/retiré ici, systématiquement avant
# `lancer`/`revoir`, et rejouable seul en verbe `garde`. Idempotent : sortie
# 0 que core.bare ait été trouvé (et retiré) ou déjà absent.
garde_core_bare() {
  local commande="${1:-garde (manuel)}"
  local valeur
  valeur=$(git -C "$MAIN_REPO" config --show-origin --get core.bare 2>/dev/null)
  if [ -z "$valeur" ]; then
    echo "garde core.bare : absent — rien à faire."
    return 0
  fi
  echo "garde core.bare : présent ($valeur) — retrait."
  git -C "$MAIN_REPO" config --unset core.bare
  printf '%s\t%s\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$valeur" "$commande" >> "$CORE_BARE_LOG"
  echo "garde core.bare : retiré, journalisé dans $CORE_BARE_LOG"
  return 0
}

# --- lancer <issue> [modele] [effort] / revoir <pr> ---------------------------
#
# Enveloppent lancer-lane.ps1 (point d'entrée unique, #255) : `circuit.sh
# lancer`/`revoir` sont désormais l'unique façon d'invoquer le lanceur — la
# garde core.bare (#231) est systématique avant tout lancement, jamais un
# geste manuel séparé.

lancer() {
  local issue="${1:-}" modele="${2:-}" effort="${3:-}"
  if [ -z "$issue" ]; then
    echo "Usage : $0 lancer <ISSUE> [modele] [effort]" >&2
    return 1
  fi
  garde_core_bare "lancer $issue"
  local args=(-NoProfile -ExecutionPolicy Bypass -File "$LANCEUR" "$issue")
  [ -n "$modele" ] && args+=(-Modele "$modele")
  [ -n "$effort" ] && args+=(-Effort "$effort")
  powershell.exe "${args[@]}"
}

revoir() {
  local pr="${1:-}"
  if [ -z "$pr" ]; then
    echo "Usage : $0 revoir <PR>" >&2
    return 1
  fi
  garde_core_bare "revoir $pr"
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$LANCEUR" -Revue "$pr"
}

# --- dispatch -----------------------------------------------------------------
#
# Gardé derrière ce test (BASH_SOURCE == $0) pour que les tests puissent
# `source` ce fichier et appeler ses fonctions (parser_verdict, ...) sans
# déclencher le dispatch.
if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then
case "${1:-}" in
  lancer)
    lancer "${2:-}" "${3:-}" "${4:-}"
    ;;
  revoir)
    revoir "${2:-}"
    ;;
  garde)
    garde_core_bare "garde (manuel)"
    ;;
  nettoyer)
    case "${2:-}" in
      --orphelins) nettoyer_orphelins ;;
      lane-[0-9]*|revue-[0-9]*) nettoyer_une "$2" ;;
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
  veiller)
    [ -n "${2:-}" ] || { echo "Usage : $0 veiller <ISSUE>" >&2; exit 1; }
    veiller "$2"
    ;;
  *)
    usage
    exit 1
    ;;
esac
fi
