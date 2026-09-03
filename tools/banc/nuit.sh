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
#                       [-Save <slug>] [-TimeoutTour <minutes>]
#                       [-FinA HH:MM] [-DryRun]
#
# Voir tools/banc/README.md pour le détail des sorties, codes de sortie, et
# « ce que la nuit ne fait pas ».
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LANCEUR_PS1="$REPO_ROOT/tools/lancer-banc-fumee.ps1"
FIXTURE_PY="$REPO_ROOT/bench/fixtures/personnage-banc.py"
METRIQUES_PY="$REPO_ROOT/tools/banc/metriques_nuit.py"
EXTRAIRE_PROSE_PY="$REPO_ROOT/tools/banc/extraire_prose.py"

# Frontière bash ⊥ Windows (#270) : source la conversion partagée avec
# verifier-liste-blanche-nuit.sh — jamais un chemin `pwd` brut (`/c/Users/...`)
# vers python.exe/powershell.exe (voir tools/banc/README.md).
source "$REPO_ROOT/tools/banc/chemin-windows.sh"

POLL_SECS=20
LIMITE_SESSION_IDLE_SECS=600   # 10 min — agent bloqué + idle sans progrès

# --- 0. Arguments ------------------------------------------------------------

PARTIES=""
DIRECTOR="sonnet"
TOURS=40
SAVE="banc-depart-beyond-the-vale-of-madness"
TIMEOUT_TOUR_MIN=6
FIN_A=""
DRYRUN=0
RUN_DIR_OVERRIDE=""
LANCEMENT_CMD_OVERRIDE=""

usage() {
  cat >&2 <<EOF
Usage : $0 -Parties N [-Director haiku|sonnet|ab] [-Tours 40] [-Save <slug>] [-TimeoutTour <minutes>] [-FinA HH:MM] [-DryRun] [-RunDir <chemin>]
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -Parties) PARTIES="${2:-}"; shift 2 ;;
    -Director) DIRECTOR="${2:-}"; shift 2 ;;
    -Tours) TOURS="${2:-}"; shift 2 ;;
    -Save) SAVE="${2:-}"; shift 2 ;;
    -TimeoutTour) TIMEOUT_TOUR_MIN="${2:-}"; shift 2 ;;
    -FinA) FIN_A="${2:-}"; shift 2 ;;
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
if [ -n "$FIN_A" ] && ! [[ "$FIN_A" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
  echo "REFUS : -FinA doit être au format HH:MM, heure locale 00:00-23:59 (reçu '$FIN_A')." >&2
  exit 1
fi

# --- 0bis. Environnement propre (#271, nuit N0 02/09 : SAVES_DIR posée par
# `herdr pane split --env` sur un pane de partie précédente survivait dans ce
# pane et contaminait un relancement manuel de nuit.sh depuis celui-ci —
# « REFUS : save source introuvable » sur une save d'une AUTRE partie).
# NUIT_CONSERVER_SAVES_DIR : interne / tests uniquement (même convention que
# -RunDir/-LancementCmd) — un test qui pointe délibérément SAVES_DIR vers une
# Library jetable le pose à 1 pour que ce garde-fou ne l'efface pas. Non
# documenté comme paramètre de nuit opérationnelle : usage réel : rien.
if [ -n "${SAVES_DIR:-}" ] && [ -z "${NUIT_CONSERVER_SAVES_DIR:-}" ]; then
  echo "AVERTISSEMENT : SAVES_DIR hérité de l'environnement du pane ($SAVES_DIR) — ignoré (#271)." >&2
  unset SAVES_DIR
fi

# --- 1. Arborescence du run ----------------------------------------------

DATE_JOUR="$(date '+%Y%m%d')"
RUN_DIR="${RUN_DIR_OVERRIDE:-$REPO_ROOT/bench/nuit-$DATE_JOUR}"
mkdir -p "$RUN_DIR"
NUIT_MD="$RUN_DIR/nuit.md"

# Sentinelle d'arrêt (#271) — testée à chaque poll de attendre_fichier ET
# entre deux parties : Ctrl+C n'est pas garanti sous Windows (trap INT/TERM
# jamais exercé depuis un shell Windows, constat nuit N0 02/09) ; créer l'un
# de ces deux fichiers ARRÊTE la nuit proprement (nettoyage + nuit.md + sortie
# 130), quel que soit le shell qui l'a lancée. STOP_FILE est scopé à ce run ;
# PAUSE_FILE est le fichier déjà lu par lancer-lane.ps1 (tools/PAUSE).
STOP_FILE="$RUN_DIR/STOP"
PAUSE_FILE="$REPO_ROOT/tools/PAUSE"
arret_demande() {
  [ -f "$STOP_FILE" ] || [ -f "$PAUSE_FILE" ]
}

# "1" (vrai) si -FinA est posée et l'heure locale l'a atteinte/dépassée
# (#276) — FIN_A_EPOCH résolue une seule fois, voir § 1bis ci-dessus.
fin_a_atteinte() {
  [ -n "$FIN_A_EPOCH" ] && [ "$(date +%s)" -ge "$FIN_A_EPOCH" ]
}

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

# Une nuit ne joue JAMAIS une partie en cours — seulement une save de DÉPART
# gelée (tour 0, scène d'ouverture, personnage créé — Issue #275/I-465,
# constat #274 : la save `beyond-the-vale-of-madness` copiée jusqu'ici était
# la partie jouée jusqu'à la mort du personnage, prolongée en post-mortem).
# `tools/banc/save-depart.py` fabrique cette save de départ une fois, hors
# dépôt (D-224) ; ce garde refuse tout -Save qui ne serait pas à ce tour 0.
SAVE_SRC_DIR_WIN="$(chemin_windows_depuis_bash "$SAVE_SRC_DIR")"
NB_TOURS_SAVE="$(cd "$REPO_ROOT" && python -c "
import sys
sys.path.insert(0, '.')
from coderain.memory import MemoryStore
print(len(MemoryStore(r'$SAVE_SRC_DIR_WIN').turns()))
" 2>/dev/null)"
if ! [[ "$NB_TOURS_SAVE" =~ ^[0-9]+$ ]]; then
  echo "REFUS : impossible de lire le nombre de tours de la save '$SAVE' ($SAVE_SRC_DIR)." >&2
  exit 1
fi
if [ "$NB_TOURS_SAVE" -ne 0 ]; then
  echo "REFUS : la save '$SAVE' est au tour $NB_TOURS_SAVE, une nuit ne joue qu'une save de départ (tour 0)." >&2
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

# --- 1bis. Heure de fin -FinA (#276, revu deux fois en revue REFUS le 03/09) -
#
# FIN_A_EPOCH est résolue UNE FOIS ici et jamais recalculée pendant la nuit
# (la comparaison en boucle, fin_a_atteinte, reste monotone même si l'horloge
# franchit minuit).
#
# Deux règles, distinctes par construction (jamais une comparaison d'égalité
# à l'horloge courante -- une 2e revue REFUS du 03/09 a constaté un CI rouge
# sur une précédente version qui refusait/arrêtait sur « HH:MM == minute
# EXACTE du lancement » : selon l'instant précis où `date` s'exécute dans ce
# process face à l'instant où le TEST avait capturé « maintenant », la
# minute pouvait déjà avoir changé -- comparaison d'INÉGALITÉ ci-dessous,
# robuste à n'importe quel écart, jamais une course) :
#
# 1. AU LANCEMENT D'UNE NUIT FRAÎCHE ($START_INDEX == 1, aucune partie
#    encore jouée dans ce $RUN_DIR aujourd'hui) : HH:MM déjà passée pour
#    $DATE_JOUR bascule à DEMAIN plutôt que de refuser -- sinon le cas
#    d'usage NOMINAL de l'Issue (lancer nuit.cmd en soirée, -FinA 06:00 par
#    défaut = 06:00 le LENDEMAIN matin) refuserait tout lancement fait entre
#    06:00 et minuit, ce qui aurait tué le but même de #276 (1re revue
#    REFUS). Aucun refus nommé ne survit à cette bascule : sous une
#    sémantique « prochaine occurrence », aucune heure n'est jamais
#    authentiquement « passée » — seul le format -FinA reste refusable
#    (ci-dessus, avant cette section).
# 2. PENDANT LA NUIT (relancement en CONTINUATION, $START_INDEX > 1,
#    partie-01 déjà là) : JAMAIS de bascule au lendemain -- HH:MM déjà
#    atteinte pour $DATE_JOUR (par n'importe quelle marge, même minime) fait
#    s'arrêter la nuit tout de suite (fin_a_atteinte vrai dès le prochain
#    contrôle), par le chemin normal (même code que STOP). Une continuation
#    ne recule jamais son heure de fin d'un jour entier.
FIN_A_EPOCH=""
if [ -n "$FIN_A" ]; then
  FIN_A_EPOCH_JOUR="$(date -d "${DATE_JOUR:0:4}-${DATE_JOUR:4:2}-${DATE_JOUR:6:2} $FIN_A:00" +%s 2>/dev/null)"
  if [ -z "$FIN_A_EPOCH_JOUR" ]; then
    echo "REFUS : -FinA '$FIN_A' n'a pas pu être résolue en heure locale." >&2
    exit 1
  fi
  if [ "$FIN_A_EPOCH_JOUR" -gt "$(date +%s)" ]; then
    FIN_A_EPOCH="$FIN_A_EPOCH_JOUR"                       # encore à venir aujourd'hui
  elif [ "$START_INDEX" -eq 1 ]; then
    FIN_A_EPOCH=$((FIN_A_EPOCH_JOUR + 86400))             # nuit fraîche, déjà passée -> demain
  else
    FIN_A_EPOCH="$FIN_A_EPOCH_JOUR"                        # continuation, déjà atteinte -> arrêt
  fi
fi

# --- état en vol (pour le trap INT/TERM — jamais un agent laissé en vol) ----

PANE_MJ_COURANT=""
PANE_JOUEUR_COURANT=""
PARTIE_DIR_COURANTE=""
DEBUT_NUIT=$(date +%s)
TABLE_PARTIES=()   # lignes déjà écrites de la table nuit.md, dans l'ordre
RAISON_ARRET_NUIT=""
LIMITE_SESSION_TOUCHEE="non"   # #276 rapport-nuit.md — "oui" si sortie 5
DEPOT_RAPPORT_STATUT=""        # #276 — statut du dépôt sur l'Issue #201

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
  #
  # #271 (nuit N0 02/09, cas 1) : herdr refuse de fermer le DERNIER pane d'un
  # workspace (`confirmation_required`, "closing this pane would close a
  # worktree group") si le pane principal a déjà été fermé par ailleurs — ce
  # script ne dépend plus d'un pane "principal" pour réussir : sur ce refus,
  # on journalise et on bascule sur `/exit` envoyé à l'agent (voir
  # envoyer_exit_agent) plutôt que de laisser l'agent en vol sans recours.
  local p sortie nom
  for p in "$PANE_MJ_COURANT" "$PANE_JOUEUR_COURANT"; do
    [ -n "$p" ] || continue
    if [ "$p" = "$PANE_MJ_COURANT" ]; then nom="banc-mj"; else nom="banc-joueur"; fi
    sortie="$(herdr pane close "$p" 2>&1)"
    if [ $? -ne 0 ]; then
      if printf '%s' "$sortie" | grep -q 'confirmation_required'; then
        echo "AVERTISSEMENT : pane close $p ($nom) refusé (confirmation_required, dernier pane du workspace, #271) — envoi /exit à la place." >&2
      else
        echo "AVERTISSEMENT : pane close $p ($nom) a échoué : $sortie" >&2
      fi
      envoyer_exit_agent "$nom"
    fi
  done
  PANE_MJ_COURANT=""
  PANE_JOUEUR_COURANT=""
}

# "1" si l'agent nommé $1 apparaît dans `herdr agent list`, vide sinon.
agent_existe() {
  herdr agent list 2>/dev/null | grep -q "\"name\":\"$1\"" && echo 1
}

# Envoie /exit à un agent via `send-keys` — JAMAIS `agent prompt` depuis bash
# (#271, annexe : "/exit" y est réécrit "C:/Program Files/Git/exit" par la
# conversion de chemin MSYS de Git Bash). Une touche à la fois (aucun
# argument ne commence par "/") pour ne déclencher aucune conversion.
envoyer_exit_agent() {
  local nom="$1"
  herdr agent send-keys "$nom" slash e x i t enter >/dev/null 2>&1
}

# Attend (bornée 30 s, #271) que ni banc-mj ni banc-joueur n'apparaissent plus
# dans `herdr agent list`. Rend 0 si les deux sont partis, 1 sinon.
attendre_agents_fermes() {
  local n=0 max=15   # 15 * 2s = 30s
  while [ "$n" -lt "$max" ]; do
    if [ -z "$(agent_existe banc-mj)" ] && [ -z "$(agent_existe banc-joueur)" ]; then
      return 0
    fi
    n=$((n + 1))
    sleep 2
  done
  return 1
}

# Ferme les panes de la partie courante ET VÉRIFIE que les agents ne
# survivent plus (#271, nuit N0 02/09 cas 1 : un agent banc-joueur survivant
# a fait échouer TOUTE partie suivante par collision de nom sur `agent
# start`). Un agent survivant après `pane close` reçoit `/exit` puis une
# dernière vérification ; s'il survit encore, la nuit s'arrête plutôt que de
# risquer une partie suivante sur un nom déjà pris.
fermer_et_verifier_agents() {
  local partie_dir="$1" nn="$2"
  fermer_panes
  if attendre_agents_fermes; then
    return 0
  fi
  echo "AVERTISSEMENT : agent(s) survivant(s) après fermeture des panes (#271) — envoi /exit." >&2
  local nom
  for nom in banc-mj banc-joueur; do
    [ -n "$(agent_existe "$nom")" ] && envoyer_exit_agent "$nom"
  done
  if attendre_agents_fermes; then
    return 0
  fi
  local survivants=""
  for nom in banc-mj banc-joueur; do
    [ -n "$(agent_existe "$nom")" ] && survivants="$survivants $nom"
  done
  ecrire_craquement "$partie_dir" "$nn" "nettoyage" \
    "agent(s) non fermé(s) après pane close + /exit (#271) :$survivants"
  RAISON_ARRET_NUIT="agent non fermé (partie $nn :$survivants)"
  finaliser_nuit
  exit 7
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

# Attend qu'un fichier existe et soit non vide. Rend 0 (produit), 3 (arrêt
# demandé — sentinelle STOP/PAUSE, #271), 4 (timeout du tour, craquement
# LOCAL à la partie), 5 (limite de session — arrêt de TOUTE la nuit, budget
# #260), 8 (heure de fin -FinA atteinte — arrêt de TOUTE la nuit, #276).
attendre_fichier() {
  local fichier="$1"
  local n=0 bloque_polls=0
  local max_polls=$(( (TIMEOUT_TOUR_SECS + POLL_SECS - 1) / POLL_SECS ))
  local max_polls_bloque=$(( (LIMITE_SESSION_IDLE_SECS + POLL_SECS - 1) / POLL_SECS ))
  while [ ! -s "$fichier" ]; do
    if arret_demande; then
      echo "ARRÊT DEMANDÉ (fichier STOP/PAUSE détecté, #271)"
      return 3
    fi
    if fin_a_atteinte; then
      echo "HEURE DE FIN ATTEINTE ($FIN_A, #276)"
      return 8
    fi
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
  # Frontière bash ⊥ Windows (#270) : $save_dir est embarqué en LITTÉRAL dans
  # le code source Python ci-dessous (r'...') — MSYS ne traduit que les
  # arguments argv d'un exe natif, pas une chaîne cachée dans un -c ; il faut
  # convertir explicitement avant.
  local save_dir_win; save_dir_win="$(chemin_windows_depuis_bash "$save_dir")"
  python -c "
import json, sys
try:
    d = json.load(open(r'$save_dir_win/state.json', encoding='utf-8'))
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
  finaliser_nuit
  exit 130
}
trap 'nettoyage_interruption INT' INT
trap 'nettoyage_interruption TERM' TERM

# --- 4. nuit.md ---------------------------------------------------------------

ecrire_nuit_md() {
  local duree_s="${1:-$(( $(date +%s) - DEBUT_NUIT ))}"
  local metriques
  metriques="$(python "$METRIQUES_PY" "$RUN_DIR" 2>/dev/null)"
  {
    echo "# nuit — $DATE_JOUR"
    echo
    echo "Save : $SAVE — Director : $DIRECTOR — Tours max/partie : $TOURS — "\
"Timeout tour : ${TIMEOUT_TOUR_MIN}min${FIN_A:+ — Fin à : $FIN_A}"
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
    echo
    echo "Rapport de nuit : $RUN_DIR/rapport-nuit.md — dépôt Issue #201 : "\
"${DEPOT_RAPPORT_STATUT:-non tenté}"
  } > "$NUIT_MD"
}

# --- 4bis. rapport-nuit.md (#276) --------------------------------------------
#
# Écrit à CHAQUE finalisation de la nuit (finaliser_nuit ci-dessous), quelle
# que soit la raison d'arrêt (STOP, heure de fin, limite de session, échec de
# lancement répété, agent non fermé, budget -Parties atteint) — l'étend
# `tools/banc/metriques_nuit.py`, ne duplique rien (§ « Livrer » 2 de #276).
ecrire_rapport_nuit() {
  local duree_s="$1" err_path="$RUN_DIR/.rapport-nuit.err"
  if ! python "$METRIQUES_PY" "$RUN_DIR" rapport \
       "${RAISON_ARRET_NUIT:-budget -Parties atteint}" "$duree_s" "$LIMITE_SESSION_TOUCHEE" \
       > "$RUN_DIR/rapport-nuit.md" 2>"$err_path"; then
    # Jamais une erreur silencieuse (même discipline que deposer_rapport_201
    # ci-dessous) : rapport-nuit.md nomme l'échec plutôt que d'être vide.
    {
      echo "# rapport-nuit — ÉCHEC DE CALCUL"
      echo
      echo "Le calcul de $METRIQUES_PY a échoué -- métriques indisponibles."
      echo
      echo '```'
      cat "$err_path" 2>/dev/null
      echo '```'
    } > "$RUN_DIR/rapport-nuit.md"
  fi
  rm -f "$err_path"
}

# Poste rapport-nuit.md en commentaire sur l'Issue #201 (fiche du banc) via
# `gh`, si disponible et authentifié -- sinon rend un statut nommé, jamais
# une erreur silencieuse (§ « Livrer » 3 de #276 : « le fichier seul, et la
# raison dans nuit.md »). Jamais tenté en -DryRun (aucun effet de bord
# externe sur un montage de test).
deposer_rapport_201() {
  if [ "$DRYRUN" -eq 1 ]; then
    echo "non posté (-DryRun)"; return
  fi
  if ! command -v gh >/dev/null 2>&1; then
    echo "non posté (gh indisponible)"; return
  fi
  if ! gh auth status >/dev/null 2>&1; then
    echo "non posté (gh non authentifié)"; return
  fi
  if gh issue comment 201 --repo souhelmeskache/souffleur \
       --body-file "$RUN_DIR/rapport-nuit.md" >/dev/null 2>&1; then
    echo "posté sur #201"
  else
    echo "non posté (échec gh issue comment)"
  fi
}

# Point d'entrée UNIQUE de fin de nuit (#276) — appelé à la place de
# `ecrire_nuit_md` seul sur CHAQUE chemin de sortie : rapport-nuit.md
# d'abord (dépôt #201 tenté ensuite), puis nuit.md (qui cite le statut du
# dépôt) -- jamais l'inverse, sinon nuit.md ne pourrait pas citer le statut
# du dépôt qui n'aurait pas encore eu lieu.
finaliser_nuit() {
  local duree_s=$(( $(date +%s) - DEBUT_NUIT ))
  ecrire_rapport_nuit "$duree_s"
  DEPOT_RAPPORT_STATUT="$(deposer_rapport_201)"
  ecrire_nuit_md "$duree_s"
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
    fermer_et_verifier_agents "$partie_dir" "00"
    ecrire_resume_run "$partie_dir" "$pnn" "$modele" 0 "N" "$raison" $(( $(date +%s) - t0 )) "${craquements[@]}"
    TABLE_PARTIES+=("| $pnn | $modele | 0 | N | $raison |")
    if [ "$ECHECS_LANCEMENT_CONSECUTIFS" -ge 2 ]; then
      RAISON_ARRET_NUIT="lancement impossible (2 échecs de lancement consécutifs, partie $pnn)"
      finaliser_nuit
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
      herdr agent prompt banc-mj "go — tour $nn : ouverture, pas d'action joueur — établis la scène d'ouverture (opening_scene) puis écris tour-$nn.md en conséquence" >/dev/null 2>&1
    else
      echo "=== partie $pnn tour $nn — go joueur $(date '+%H:%M:%S')"
      herdr agent prompt banc-joueur "go — tour $nn : lis UNIQUEMENT $partie_dir/prose-$pn.md, joue ton tour (un paragraphe), puis écris-le verbatim dans $partie_dir/action-$nn.md" >/dev/null 2>&1
      attendre_fichier "$partie_dir/action-$nn.md"; r=$?
      if [ "$r" -eq 3 ]; then RAISON_ARRET_NUIT="arrêt demandé (fichier STOP/PAUSE, partie $pnn, tour $nn)"; fermer_et_verifier_agents "$partie_dir" "$nn"; finaliser_nuit; exit 130; fi
      if [ "$r" -eq 8 ]; then RAISON_ARRET_NUIT="heure de fin atteinte ($FIN_A) (partie $pnn, tour $nn)"; fermer_et_verifier_agents "$partie_dir" "$nn"; finaliser_nuit; exit 130; fi
      if [ "$r" -eq 5 ]; then RAISON_ARRET_NUIT="limite de session (partie $pnn, tour $nn)"; LIMITE_SESSION_TOUCHEE="oui"; fermer_panes; finaliser_nuit; exit 5; fi
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

    attendre_fichier "$partie_dir/tour-$nn.md"; r=$?
    if [ "$r" -eq 3 ]; then RAISON_ARRET_NUIT="arrêt demandé (fichier STOP/PAUSE, partie $pnn, tour $nn)"; fermer_et_verifier_agents "$partie_dir" "$nn"; finaliser_nuit; exit 130; fi
    if [ "$r" -eq 8 ]; then RAISON_ARRET_NUIT="heure de fin atteinte ($FIN_A) (partie $pnn, tour $nn)"; fermer_et_verifier_agents "$partie_dir" "$nn"; finaliser_nuit; exit 130; fi
    if [ "$r" -eq 5 ]; then RAISON_ARRET_NUIT="limite de session (partie $pnn, tour $nn)"; LIMITE_SESSION_TOUCHEE="oui"; fermer_panes; finaliser_nuit; exit 5; fi
    if [ "$r" -ne 0 ]; then
      raison="craquement-timeout"
      ecrire_craquement "$partie_dir" "$nn" "timeout" "timeout en attendant tour-$nn.md"
      craquements+=("craquement-timeout-$nn.md")
      break
    fi

    # Extraction MÉCANIQUE de prose-NN.md depuis tour-NN.md (#269) — jamais
    # espérée du MJ : l'organe zéro-spoiler (D-219) doit exister même si le
    # MJ n'a écrit que tour-NN.md (le seul livrable que le gabarit spécifie).
    extraction_err="$(python "$EXTRAIRE_PROSE_PY" "$partie_dir/tour-$nn.md" "$partie_dir/prose-$nn.md" 2>&1)"
    if [ $? -ne 0 ]; then
      raison="craquement-prose-absente"
      ecrire_craquement "$partie_dir" "$nn" "prose-absente" "$extraction_err"
      craquements+=("craquement-prose-absente-$nn.md")
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
  fermer_et_verifier_agents "$partie_dir" "$pnn"

  ecrire_resume_run "$partie_dir" "$pnn" "$modele" "$tours_joues" "$fin_atteinte" "$raison" \
    $(( $(date +%s) - t0 )) "${craquements[@]}"
  TABLE_PARTIES+=("| $pnn | $modele | $tours_joues | $fin_atteinte | $raison |")
}

# --- 6. Boucle des parties ----------------------------------------------------

i=1
while [ "$i" -le "$PARTIES" ]; do
  if arret_demande; then
    echo "=== ARRÊT DEMANDÉ (fichier STOP/PAUSE, #271) — nuit interrompue avant partie $i ==="
    RAISON_ARRET_NUIT="arrêt demandé (fichier STOP/PAUSE)"
    finaliser_nuit
    exit 130
  fi
  if fin_a_atteinte; then
    echo "=== HEURE DE FIN ATTEINTE ($FIN_A, #276) — nuit interrompue avant partie $i ==="
    RAISON_ARRET_NUIT="heure de fin atteinte ($FIN_A)"
    finaliser_nuit
    exit 130
  fi
  jouer_partie "$i"
  i=$((i + 1))
done

finaliser_nuit
echo "=== nuit $DATE_JOUR terminée : $NUIT_MD ==="
exit 0
