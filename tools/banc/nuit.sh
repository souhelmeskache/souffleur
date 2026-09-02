#!/bin/bash
# tools/banc/nuit.sh — banc de nuit N1 (#201, D-276 ; Issue #260)
#
# Boucle-ferme SANS LLM : joue des parties complètes la nuit, sans humain,
# sans analyste, avec budget, arrêt propre et sorties en forme fixe. Ce
# script ne prend AUCUNE décision de jeu — il copie des fichiers, lance et
# ferme des agents existants (joueur, Director), attend des fichiers
# apparaître, et journalise des faits mécaniques (tours, craquements,
# métriques). Toute décision narrative reste dans les deux agents lancés
# (banc-mj/banc-joueur, gabarits gelés D-276 §4) ou dans le sous-agent
# narrateur qu'ils spawnent — jamais dans ce script.
#
# Usage :
#   tools/banc/nuit.sh -Parties N [-Director haiku|sonnet|ab] [-Tours 40]
#                       [-Save <slug>] [-TimeoutTour <minutes>] [-DryRun]
#
# Voir tools/banc/README.md pour le détail des sorties, codes de sortie, et
# « ce que la nuit ne fait pas ».
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LANCEUR_PS1="$REPO_ROOT/tools/lancer-banc-fumee.ps1"
FIXTURE_PY="$REPO_ROOT/bench/fixtures/personnage-banc.py"
METRIQUES_PY="$REPO_ROOT/tools/banc/metriques_nuit.py"

POLL_SECS=20
LIMITE_SESSION_IDLE_SECS=600   # 10 min — agent bloqué + idle sans progrès

# --- 0. Arguments ------------------------------------------------------------

PARTIES=""
DIRECTOR="sonnet"
TOURS=40
SAVE="beyond-the-vale-of-madness"
TIMEOUT_TOUR_MIN=6
DRYRUN=0
RUN_DIR_OVERRIDE=""
LANCEMENT_CMD_OVERRIDE=""

usage() {
  cat >&2 <<EOF
Usage : $0 -Parties N [-Director haiku|sonnet|ab] [-Tours 40] [-Save <slug>] [-TimeoutTour <minutes>] [-DryRun] [-RunDir <chemin>]
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -Parties) PARTIES="${2:-}"; shift 2 ;;
    -Director) DIRECTOR="${2:-}"; shift 2 ;;
    -Tours) TOURS="${2:-}"; shift 2 ;;
    -Save) SAVE="${2:-}"; shift 2 ;;
    -TimeoutTour) TIMEOUT_TOUR_MIN="${2:-}"; shift 2 ;;
    -DryRun) DRYRUN=1; shift ;;
    # -RunDir : usage interne / tests (tests/nuit_dryrun_test.py) — écrit le
    # run ailleurs que bench/nuit-AAAAMMJJ/, pour ne jamais toucher au vrai
    # dossier bench/ pendant un test (D-109/D-178). Non documenté comme
    # paramètre de nuit opérationnelle dans le README (usage réel : rien).
    -RunDir) RUN_DIR_OVERRIDE="${2:-}"; shift 2 ;;
    # -LancementCmd : usage interne / tests (tests/nuit_echec_lancement_test.py,
    # #263) — remplace l'appel powershell.exe/lancer-banc-fumee.ps1 par la
    # commande donnée (évaluée telle quelle), pour reproduire un échec de
    # lancement DÉTERMINISTE sans herdr/powershell réels. Non documenté comme
    # paramètre de nuit opérationnelle dans le README (usage réel : rien).
    -LancementCmd) LANCEMENT_CMD_OVERRIDE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "REFUS : argument inconnu '$1'." >&2; usage; exit 1 ;;
  esac
done

if ! [[ "$PARTIES" =~ ^[0-9]+$ ]] || [ "$PARTIES" -lt 1 ]; then
  echo "REFUS : -Parties doit être un entier >= 1 (reçu '$PARTIES')." >&2
  usage; exit 1
fi
case "$DIRECTOR" in
  haiku|sonnet|ab) ;;
  *) echo "REFUS : -Director doit être haiku, sonnet ou ab (reçu '$DIRECTOR')." >&2; exit 1 ;;
esac
if ! [[ "$TOURS" =~ ^[0-9]+$ ]] || [ "$TOURS" -lt 1 ]; then
  echo "REFUS : -Tours doit être un entier >= 1 (reçu '$TOURS')." >&2; exit 1
fi
if ! [[ "$TIMEOUT_TOUR_MIN" =~ ^[0-9]+$ ]] || [ "$TIMEOUT_TOUR_MIN" -lt 1 ]; then
  echo "REFUS : -TimeoutTour doit être un entier de minutes >= 1 (reçu '$TIMEOUT_TOUR_MIN')." >&2; exit 1
fi
TIMEOUT_TOUR_SECS=$((TIMEOUT_TOUR_MIN * 60))

# --- 1. Arborescence du run ----------------------------------------------

DATE_JOUR="$(date '+%Y%m%d')"
RUN_DIR="${RUN_DIR_OVERRIDE:-$REPO_ROOT/bench/nuit-$DATE_JOUR}"
mkdir -p "$RUN_DIR"
NUIT_MD="$RUN_DIR/nuit.md"

# Résolution SAVES_DIR de production (coderain/config.py) — jamais un chemin
# en dur : respecte un override déjà en place sur ce poste.
SAVE_SRC_DIR="$(cd "$REPO_ROOT" && python -c "
import sys
sys.path.insert(0, '.')
from coderain.config import saves_dir
print(saves_dir())
" 2>/dev/null)/$SAVE"
if [ ! -d "$SAVE_SRC_DIR" ]; then
  echo "REFUS : save source introuvable ($SAVE_SRC_DIR)." >&2
  exit 1
fi

# Prochain numéro de partie : reprend après les parties déjà jouées AUJOURD'HUI
# dans ce même $RUN_DIR (idempotence — un second appel le même jour n'écrase
# jamais une partie déjà jouée).
START_INDEX=1
for d in "$RUN_DIR"/partie-*/; do
  [ -d "$d" ] || continue
  START_INDEX=$((START_INDEX + 1))
done

# --- état en vol (pour le trap INT/TERM — jamais un agent laissé en vol) ----

PANE_MJ_COURANT=""
PANE_JOUEUR_COURANT=""
PARTIE_DIR_COURANTE=""
DEBUT_NUIT=$(date +%s)
TABLE_PARTIES=()   # lignes déjà écrites de la table nuit.md, dans l'ordre
RAISON_ARRET_NUIT=""

# Échecs de LANCEMENT consécutifs (#263) — distinct des craquements de tour
# (timeout, fixture) qui n'arrêtent que la partie courante. Un gabarit cassé
# à l'envoi (nuit N0 du 02/09) échoue au lancement de TOUTE partie de la même
# façon : consommer tout le budget -Parties sur cet échec identique, répété,
# est un symptôme de la même famille que le budget « atteint » silencieux.
# Deux échecs consécutifs → arrêt de la nuit (voir README, § codes de sortie).
ECHECS_LANCEMENT_CONSECUTIFS=0

# --- 2. Aides ---------------------------------------------------------------

fermer_panes() {
  # Ferme au mieux les deux panes de la partie courante — jamais fatal (un
  # pane déjà fermé, ou jamais ouvert, ne bloque pas la fermeture de
  # l'autre). "L'équivalent banc" de circuit.sh nettoyer (#255/I-243).
  local p
  for p in "$PANE_MJ_COURANT" "$PANE_JOUEUR_COURANT"; do
    [ -n "$p" ] || continue
    herdr pane close "$p" >/dev/null 2>&1
  done
  PANE_MJ_COURANT=""
  PANE_JOUEUR_COURANT=""
}

ecrire_craquement() {
  local partie_dir="$1" nn="$2" type="$3" detail="$4"
  {
    echo "# Craquement — tour $nn ($type)"
    echo
    echo "Horodatage : $(date '+%Y-%m-%d %H:%M:%S')"
    echo
    echo '```'
    printf '%s\n' "$detail"
    echo '```'
  } > "$partie_dir/craquement-$type-$nn.md"
}

# Casting Director pour la partie de rang $1 (1-based, RELATIF à cet appel de
# nuit.sh) — "ab" alterne haiku/sonnet en commençant par haiku (N0 = 4
# parties : 2 haiku, 2 sonnet, cf. Issue #260).
modele_director_pour() {
  local rang="$1"
  case "$DIRECTOR" in
    ab) if [ $((rang % 2)) -eq 1 ]; then echo haiku; else echo sonnet; fi ;;
    *) echo "$DIRECTOR" ;;
  esac
}

# "1" si l'agent nommé $1 (banc-mj|banc-joueur) est `blocked`, vide sinon.
agent_est_bloque() {
  herdr agent list 2>/dev/null | tr '{' '\n' \
    | grep "\"name\":\"$1\"" | grep -q '"agent_status":"blocked' && echo 1
}

# "1" si un des deux panes de la partie affiche un texte de limite de
# session/usage, vide sinon.
limite_session_detectee() {
  local p
  for p in "$PANE_MJ_COURANT" "$PANE_JOUEUR_COURANT"; do
    [ -n "$p" ] || continue
    if herdr pane read "$p" --lines 60 2>/dev/null | grep -qiE 'session limit|usage limit'; then
      echo 1; return 0
    fi
  done
}

# Attend qu'un fichier existe et soit non vide. Rend 0 (produit), 2 (partie
# non applicable ici — inutilisé), 4 (timeout du tour, craquement LOCAL à la
# partie), 5 (limite de session — arrêt de TOUTE la nuit, budget #260).
attendre_fichier() {
  local fichier="$1"
  local n=0 bloque_polls=0
  local max_polls=$(( (TIMEOUT_TOUR_SECS + POLL_SECS - 1) / POLL_SECS ))
  local max_polls_bloque=$(( (LIMITE_SESSION_IDLE_SECS + POLL_SECS - 1) / POLL_SECS ))
  while [ ! -s "$fichier" ]; do
    if [ -n "$(limite_session_detectee)" ]; then
      echo "LIMITE DE SESSION (texte détecté dans un pane)"
      return 5
    fi
    if [ -n "$(agent_est_bloque banc-mj)" ] || [ -n "$(agent_est_bloque banc-joueur)" ]; then
      bloque_polls=$((bloque_polls + 1))
      if [ "$bloque_polls" -ge "$max_polls_bloque" ]; then
        echo "LIMITE DE SESSION (agent bloqué, idle > $((LIMITE_SESSION_IDLE_SECS / 60)) min sans progrès)"
        return 5
      fi
    else
      bloque_polls=0
    fi
    n=$((n + 1))
    if [ "$n" -gt "$max_polls" ]; then
      echo "TIMEOUT tour (> ${TIMEOUT_TOUR_MIN}min) en attendant $(basename "$fichier")"
      return 4
    fi
    sleep "$POLL_SECS"
  done
  return 0
}

# "0" (vrai) si la fixture / le save signale la fin de partie — PROXY
# MÉCANIQUE (mort du joueur, `rpg.player.conditions` contient "dead"), PAS
# une détection narrative de fin de module : voir tools/banc/README.md,
# « ce que la nuit ne fait pas ». Aucun signal générique de "module terminé"
# n'existe côté moteur sans jugement humain/LLM (hors périmètre #260 :
# "aucun LLM dans le script").
partie_module_termine() {
  local save_dir="$1"
  python -c "
import json, sys
try:
    d = json.load(open(r'$save_dir/state.json', encoding='utf-8'))
except Exception:
    sys.exit(1)
conds = ((d.get('rpg') or {}).get('player') or {}).get('conditions') or []
sys.exit(0 if 'dead' in conds else 1)
" 2>/dev/null
}

ecrire_resume_run() {
  local partie_dir="$1" pnn="$2" modele="$3" tours_joues="$4" fin_atteinte="$5" \
        raison="$6" duree_s="$7"
  shift 7
  local craquements=("$@")
  {
    echo "# resume-run — partie $pnn"
    echo
    echo "casting: joueur=haiku(low) director=$modele(medium) narrateur=haiku"
    echo "tours_joues: $tours_joues"
    echo "fin_atteinte: $fin_atteinte"
    echo "raison_arret: $raison"
    echo "duree_s: $duree_s"
    if [ "${#craquements[@]}" -gt 0 ]; then
      echo "craquements:"
      local c
      for c in "${craquements[@]}"; do echo "  - $c"; done
    else
      echo "craquements: (aucun)"
    fi
  } > "$partie_dir/resume-run.md"
}

# --- 3. Trap INT/TERM (Complément 2, #260) — jamais un agent laissé en vol ---

nettoyage_interruption() {
  local sig="$1"
  echo
  echo "=== nuit.sh interrompu ($sig) — fermeture des agents en vol ==="
  fermer_panes
  RAISON_ARRET_NUIT="interrompu ($sig)"
  ecrire_nuit_md
  exit 130
}
trap 'nettoyage_interruption INT' INT
trap 'nettoyage_interruption TERM' TERM

# --- 4. nuit.md ---------------------------------------------------------------

ecrire_nuit_md() {
  local duree_s=$(( $(date +%s) - DEBUT_NUIT ))
  local metriques
  metriques="$(python "$METRIQUES_PY" "$RUN_DIR" 2>/dev/null)"
  {
    echo "# nuit — $DATE_JOUR"
    echo
    echo "Save : $SAVE — Director : $DIRECTOR — Tours max/partie : $TOURS — "\
"Timeout tour : ${TIMEOUT_TOUR_MIN}min"
    echo
    echo "Durée totale : ${duree_s}s"
    echo "Raison d'arrêt de la nuit : ${RAISON_ARRET_NUIT:-budget -Parties atteint}"
    echo
    echo "## Parties"
    echo
    echo "| partie | director | tours joués | fin atteinte | raison |"
    echo "|---|---|---|---|---|"
    local ligne
    for ligne in "${TABLE_PARTIES[@]}"; do
      echo "$ligne"
    done
    echo
    echo "## Métriques (§3 #201)"
    echo
    printf '%s' "$metriques"
  } > "$NUIT_MD"
}

# --- 5. Boucle d'une partie ---------------------------------------------------

jouer_partie() {
  local rang="$1"
  local partie_num=$((START_INDEX + rang - 1))
  local pnn; pnn=$(printf '%02d' "$partie_num")
  local partie_dir="$RUN_DIR/partie-$pnn"
  local modele; modele="$(modele_director_pour "$rang")"
  local t0=$(date +%s)
  local raison="" fin_atteinte="N" tours_joues=0
  local craquements=()

  PARTIE_DIR_COURANTE="$partie_dir"
  mkdir -p "$partie_dir"

  echo "=== partie $pnn : copie fraîche de la save '$SAVE' ==="
  local save_dest="$partie_dir/save"
  rm -rf "$save_dest"
  cp -r "$SAVE_SRC_DIR" "$save_dest"

  echo "=== partie $pnn : fixture personnage (#257) ==="
  if ! python "$FIXTURE_PY" "$save_dest" > "$partie_dir/fixture.log" 2>&1; then
    raison="fixture"
    ecrire_craquement "$partie_dir" "00" "fixture" "$(cat "$partie_dir/fixture.log")"
    craquements+=("craquement-fixture-00.md")
    ecrire_resume_run "$partie_dir" "$pnn" "$modele" 0 "N" "$raison" $(( $(date +%s) - t0 )) "${craquements[@]}"
    TABLE_PARTIES+=("| $pnn | $modele | 0 | N | $raison |")
    return 0
  fi

  if [ "$DRYRUN" -eq 1 ]; then
    echo "=== partie $pnn : -DryRun — aucun agent lancé ==="
    ecrire_resume_run "$partie_dir" "$pnn" "$modele" 0 "N" "dry-run" $(( $(date +%s) - t0 ))
    TABLE_PARTIES+=("| $pnn | $modele | 0 | N | dry-run |")
    return 0
  fi

  echo "=== partie $pnn : lancement (director=$modele) ==="
  local session_tour="nuit-$DATE_JOUR-p$pnn"
  if [ -n "$LANCEMENT_CMD_OVERRIDE" ]; then
    # Test uniquement (#263) — voir -LancementCmd ci-dessus. Sous-shell
    # obligatoire : un `eval "exit 1"` direct sortirait CE script, pas
    # seulement la commande de test.
    ( eval "$LANCEMENT_CMD_OVERRIDE" ) > "$partie_dir/lancement.log" 2>&1
  else
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$LANCEUR_PS1" \
      -SessionTour "$session_tour" -Save save -Tours "$TOURS" \
      -ModeleMj "$modele" -ModeleJoueur haiku \
      -SavesDirOverride "$partie_dir" -JournalDirOverride "$partie_dir" \
      > "$partie_dir/lancement.log" 2>&1
  fi
  local rc_lancement=$?
  PANE_MJ_COURANT="$(grep -m1 '^Pane MJ' "$partie_dir/lancement.log" | sed 's/^[^:]*: *//' | tr -d '\r\n')"
  PANE_JOUEUR_COURANT="$(grep -m1 '^Pane joueur-banc' "$partie_dir/lancement.log" | sed 's/^[^:]*: *//' | tr -d '\r\n')"
  if [ "$rc_lancement" -ne 0 ]; then
    raison="lancement"
    ECHECS_LANCEMENT_CONSECUTIFS=$((ECHECS_LANCEMENT_CONSECUTIFS + 1))
    ecrire_craquement "$partie_dir" "00" "lancement" "$(tail -30 "$partie_dir/lancement.log")"
    craquements+=("craquement-lancement-00.md")
    fermer_panes
    ecrire_resume_run "$partie_dir" "$pnn" "$modele" 0 "N" "$raison" $(( $(date +%s) - t0 )) "${craquements[@]}"
    TABLE_PARTIES+=("| $pnn | $modele | 0 | N | $raison |")
    if [ "$ECHECS_LANCEMENT_CONSECUTIFS" -ge 2 ]; then
      RAISON_ARRET_NUIT="lancement impossible (2 échecs de lancement consécutifs, partie $pnn)"
      ecrire_nuit_md
      exit 6
    fi
    return 0
  fi
  ECHECS_LANCEMENT_CONSECUTIFS=0

  # --- boucle de tours (fil 2, sans LLM dans CE script) ---------------------
  local tour=1
  while [ "$tour" -le "$TOURS" ]; do
    local nn pn r
    nn=$(printf '%02d' "$tour")
    pn=$(printf '%02d' $((tour - 1)))

    if [ "$tour" -eq 1 ]; then
      # Ouverture (limite assumée #260 — voir README, « ce que la nuit ne
      # fait pas ») : le gabarit banc-mj.md (gelé D-276 §4) ne décrit pas de
      # protocole de tour 1 froid — le MJ ouvre lui-même la scène
      # (opening_scene) plutôt que d'attendre une action joueur inexistante.
      herdr agent prompt banc-mj "go — tour $nn : ouverture, pas d'action joueur — établis la scène d'ouverture (opening_scene) puis écris tour-$nn.md/prose-$nn.md en conséquence" >/dev/null 2>&1
    else
      echo "=== partie $pnn tour $nn — go joueur $(date '+%H:%M:%S')"
      herdr agent prompt banc-joueur "go — tour $nn : lis UNIQUEMENT $partie_dir/prose-$pn.md, joue ton tour (un paragraphe), puis écris-le verbatim dans $partie_dir/action-$nn.md" >/dev/null 2>&1
      attendre_fichier "$partie_dir/action-$nn.md"; r=$?
      if [ "$r" -eq 5 ]; then RAISON_ARRET_NUIT="limite de session (partie $pnn, tour $nn)"; fermer_panes; ecrire_nuit_md; exit 5; fi
      if [ "$r" -ne 0 ]; then
        raison="craquement-timeout"
        ecrire_craquement "$partie_dir" "$nn" "timeout" "timeout en attendant action-$nn.md"
        craquements+=("craquement-timeout-$nn.md")
        break
      fi
      local action; action="$(cat "$partie_dir/action-$nn.md")"
      echo "=== partie $pnn tour $nn — go MJ $(date '+%H:%M:%S')"
      herdr agent prompt banc-mj "go — tour $nn. Action du joueur (verbatim) : $action" >/dev/null 2>&1
    fi

    attendre_fichier "$partie_dir/prose-$nn.md"; r=$?
    if [ "$r" -eq 5 ]; then RAISON_ARRET_NUIT="limite de session (partie $pnn, tour $nn)"; fermer_panes; ecrire_nuit_md; exit 5; fi
    if [ "$r" -ne 0 ]; then
      raison="craquement-timeout"
      ecrire_craquement "$partie_dir" "$nn" "timeout" "timeout en attendant prose-$nn.md"
      craquements+=("craquement-timeout-$nn.md")
      break
    fi

    tours_joues=$tour
    echo "=== partie $pnn tour $nn joué $(date '+%H:%M:%S')"

    if [ -n "$(partie_module_termine "$save_dest")" ]; then
      fin_atteinte="O"
      raison="fin_module"
      break
    fi
    tour=$((tour + 1))
  done

  if [ -z "$raison" ]; then
    raison="tours_max"
  fi

  echo "=== partie $pnn : fermeture des agents ==="
  fermer_panes

  ecrire_resume_run "$partie_dir" "$pnn" "$modele" "$tours_joues" "$fin_atteinte" "$raison" \
    $(( $(date +%s) - t0 )) "${craquements[@]}"
  TABLE_PARTIES+=("| $pnn | $modele | $tours_joues | $fin_atteinte | $raison |")
}

# --- 6. Boucle des parties ----------------------------------------------------

i=1
while [ "$i" -le "$PARTIES" ]; do
  jouer_partie "$i"
  i=$((i + 1))
done

ecrire_nuit_md
echo "=== nuit $DATE_JOUR terminée : $NUIT_MD ==="
exit 0
