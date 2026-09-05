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
#   tools/banc/nuit.sh [-Parties N] [-Paires N] [-Director haiku|sonnet|ab]
#                       [-Tours 200] [-Save <slug>] [-TimeoutTour <minutes>]
#                       [-FinA HH:MM] [-DryRun]
#   -Parties ou -FinA requis (au moins un des deux) -- sans -Parties, la nuit
#   boucle sans plafond de parties, bornée par -FinA seule (Souhel #279).
#
# -Paires N (défaut 1, Issue #282) : N parties tournent SIMULTANÉMENT (N
# paires Director/joueur, N copies de save, N `.turn/` étanches -- Issue
# #287) ; quand l'une finit, la suivante du budget -Parties prend sa place,
# jusqu'à épuisement du budget ou -FinA.
#
# Voir tools/banc/README.md pour le détail des sorties, codes de sortie, et
# « ce que la nuit ne fait pas ».
set -u

# Ceinture et bretelles (Issue #279) : chaque script Python du banc force déjà
# UTF-8 sur stdout/stderr lui-même (reconfigure), mais cet export protège
# aussi tout script tiers/futur appelé depuis ici sans ce garde — sous
# Windows, sys.stdout est en cp1252 hors terminal UTF-8 explicite, et un
# caractère hors cp1252 (« », accents) dans une sortie faisait planter le
# script avant même d'écrire quoi que ce soit (UnicodeEncodeError, nuit du
# 03/09).
export PYTHONIOENCODING=utf-8

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LANCEUR_PS1="$REPO_ROOT/tools/lancer-banc-fumee.ps1"
FIXTURE_PY="$REPO_ROOT/bench/fixtures/personnage-banc.py"
METRIQUES_PY="$REPO_ROOT/tools/banc/metriques_nuit.py"
EXTRAIRE_PROSE_PY="$REPO_ROOT/tools/banc/extraire_prose.py"
ARBITRER_PROSE_PY="$REPO_ROOT/tools/banc/arbitrer_prose.py"
DETECTER_FIN_PY="$REPO_ROOT/tools/banc/detecter_fin.py"

# Frontière bash ⊥ Windows (#270) : source la conversion partagée avec
# verifier-liste-blanche-nuit.sh — jamais un chemin `pwd` brut (`/c/Users/...`)
# vers python.exe/powershell.exe (voir tools/banc/README.md).
source "$REPO_ROOT/tools/banc/chemin-windows.sh"

POLL_SECS=20
LIMITE_SESSION_IDLE_SECS=600   # 10 min — agent bloqué + idle sans progrès

# --- 0. Arguments ------------------------------------------------------------

PARTIES=""
PAIRES=1
DIRECTOR="sonnet"
# Défaut relevé 40 -> 200 (#306, décision Souhel 05/09 : « j'ai besoin de
# voir des parties COMPLÈTES, pas des bancs qui testent le début du
# scénario ») — 40 était un réglage de fumée (banc de fumée manuel), jamais
# calibré pour une nuit : N1 a joué 2 x 40 tours sans jamais dépasser
# l'ouverture du module. Toujours borné par -FinA (inchangé).
TOURS=200
SAVE="banc-depart-beyond-the-vale-of-madness"
TIMEOUT_TOUR_MIN=6
FIN_A=""
DRYRUN=0
RUN_DIR_OVERRIDE=""
LANCEMENT_CMD_OVERRIDE=""

usage() {
  cat >&2 <<EOF
Usage : $0 [-Parties N] [-Paires N] [-Director haiku|sonnet|ab] [-Tours 200] [-Save <slug>] [-TimeoutTour <minutes>] [-FinA HH:MM] [-DryRun] [-RunDir <chemin>]
       -Parties ou -FinA requis (au moins un des deux).
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -Parties) PARTIES="${2:-}"; shift 2 ;;
    -Paires) PAIRES="${2:-}"; shift 2 ;;
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

# -Parties devient optionnel (Souhel #279, constat N1 : -Parties 4 a fini la
# nuit à 01:30 pour un -FinA 06:00, 4h30 perdues) -- SI -FinA est donnée, la
# nuit boucle sans plafond de parties, bornée par -FinA seule (§ 6 ci-dessous
# et fin_a_atteinte()). Sans aucun des deux, la nuit n'aurait aucune borne
# d'arrêt : refusé nommément.
if [ -n "$PARTIES" ]; then
  if ! [[ "$PARTIES" =~ ^[0-9]+$ ]] || [ "$PARTIES" -lt 1 ]; then
    echo "REFUS : -Parties doit être un entier >= 1 (reçu '$PARTIES')." >&2
    usage; exit 1
  fi
elif [ -z "$FIN_A" ]; then
  echo "REFUS : -Parties ou -FinA requis (au moins un des deux) -- sans borne, la nuit ne s'arrêterait jamais." >&2
  usage; exit 1
fi
if ! [[ "$PAIRES" =~ ^[0-9]+$ ]] || [ "$PAIRES" -lt 1 ]; then
  echo "REFUS : -Paires doit être un entier >= 1 (reçu '$PAIRES')." >&2
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

# Workspace herdr DÉDIÉ à cette nuit (#298) — passé à chaque appel de
# lancer-banc-fumee.ps1 (-WorkspaceLabel) : les panes MJ/joueur de TOUTE
# partie de cette nuit (séquentielle ou en paires parallèles, #282) vivent
# dans ce workspace, jamais dans celui d'une lane ou de l'opérateur (jamais
# `herdr pane current`, voir tools/banc/README.md § « Workspace dédié au
# banc »). Un label par jour calendaire (pas juste "banc") : une nuit qui se
# relance en continuation le même jour ($START_INDEX > 1 ci-dessous) réutilise
# le même workspace, jamais un doublon.
WORKSPACE_LABEL_BANC="banc-$DATE_JOUR"

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

# Une nuit ne doit jamais pouvoir jouer un monde VIDE (#281, à côté de la
# garde tour 0 ci-dessus) : `save-depart.py` installe désormais la partition
# (module.json + lieux/PNJ projetés) — ce garde refuse toute save qui ne
# porterait pas ce module (fabriquée avant #281, ou par un autre chemin).
MODULE_OK="$(cd "$REPO_ROOT" && python -c "
import sys, json
sys.path.insert(0, '.')
from coderain.memory import MemoryStore
save_dir = r'$SAVE_SRC_DIR_WIN'
try:
    json.load(open(save_dir + '/module.json', encoding='utf-8'))
    nb_lieux = len(MemoryStore(save_dir).entries('locations.md'))
    print(1 if nb_lieux > 0 else 0)
except Exception:
    print(0)
" 2>/dev/null)"
if [ "$MODULE_OK" != "1" ]; then
  echo "REFUS : la save '$SAVE' n'a pas de module installé, une nuit ne joue pas un monde vide." >&2
  exit 1
fi

# `.turn/` (mcp_server._turn_dir(), coderain/mcp/narrateur.py +
# position_etat.py) est le scratch d'assemblage de contexte de CHAQUE
# Director -- Issue #287 : il dérive de la save CHARGÉE (store.dir), jamais
# de mcp_server.ROOT. Chaque partie a déjà sa propre copie de save
# (partie-NN/save/), donc son propre `.turn/` sous ce dossier -- N Directors
# concurrents (-Paires > 1) sont étanches entre eux sans changement ici.

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
PID_SONDE=""   # #305, complément de spec 05/09 17:00 — voir demarrer_sonde_ecran
DEBUT_NUIT=$(date +%s)
RAISON_ARRET_NUIT=""
AVERTISSEMENT_PRE_NUIT="${AVERTISSEMENT_PRE_NUIT:-}"  # #292 -- avertissement
                                                       # (ex. lane en vol) de
                                                       # verifier-avant-nuit.sh,
                                                       # transmis par nuit.cmd,
                                                       # reporté dans nuit.md.
LIMITE_SESSION_TOUCHEE="non"   # #276 rapport-nuit.md — "oui" si sortie 5
DEPOT_RAPPORT_STATUT=""        # #276 — statut du dépôt sur l'Issue #201

# --- N paires simultanées (#282) --------------------------------------------
#
# PAIRES_MODE distingue le chemin séquentiel historique (-Paires 1, INCHANGÉ
# — TABLE_PARTIES/RAISON_ARRET_NUIT en globales, finaliser_nuit appelée
# directement depuis jouer_partie) du chemin parallèle (-Paires > 1, § 6bis
# ci-dessous) : chaque paire tourne dans un SUBSHELL bash (`&`) — un
# subshell hérite les globales au fork mais n'écrit jamais dans celles du
# parent, donc RAISON_ARRET_NUIT ne peut plus être une simple globale
# partagée entre paires. ARRET_DIR (mkdir atomique — seul le premier
# `mkdir` réussit, même entre process concurrents sur un même système de
# fichiers) porte l'arrêt de toute la nuit décrété par N'IMPORTE QUELLE
# paire ; PAIRES_MODE=0 en séquentiel (arreter_toute_la_nuit garde alors le
# comportement EXACT d'avant #282).
PAIRES_MODE=0
ARRET_DIR="$RUN_DIR/.arret-nuit"

# Échecs de LANCEMENT consécutifs (#263) — distinct des craquements de tour
# (timeout, fixture) qui n'arrêtent que la partie courante. Un gabarit cassé
# à l'envoi (nuit N0 du 02/09) échoue au lancement de TOUTE partie de la même
# façon : consommer tout le budget -Parties sur cet échec identique, répété,
# est un symptôme de la même famille que le budget « atteint » silencieux.
# Deux échecs consécutifs → arrêt de la nuit (voir README, § codes de sortie).
ECHECS_LANCEMENT_CONSECUTIFS=0

# --- 2. Aides ---------------------------------------------------------------

# Déclare un arrêt de TOUTE la nuit (#282) — ARRET_DIR (mkdir, atomique)
# n'est écrit que par le PREMIER appelant : entre paires concurrentes qui
# détecteraient la même condition (ex. -FinA atteinte pendant que N paires
# tournent), une seule gagne la course, les autres continuent (silencieuses)
# — le contenu d'ARRET_DIR fait foi, jamais un jugement sur qui a "raison".
declarer_arret_nuit() {
  local code="$1" raison="$2" limite="${3:-non}"
  if mkdir "$ARRET_DIR" 2>/dev/null; then
    printf '%s' "$code" > "$ARRET_DIR/code"
    printf '%s' "$raison" > "$ARRET_DIR/raison"
    printf '%s' "$limite" > "$ARRET_DIR/limite_session"
  fi
}

# Point de sortie UNIQUE des chemins « toute la nuit s'arrête » (STOP/PAUSE,
# -FinA, limite de session, agent non fermé, lancement impossible). En
# séquentiel (PAIRES_MODE=0) : comportement EXACT d'avant #282 —
# finaliser_nuit tourne ICI, dans le process principal. En parallèle
# (PAIRES_MODE=1, appelé depuis le SUBSHELL d'une paire) : finaliser_nuit ne
# doit tourner QU'UNE FOIS, après que TOUTES les paires ont rendu la main
# (§ 6bis) — cette fonction se contente de déclarer l'arrêt et de sortir du
# subshell de la paire courante ; la boucle parallèle appelle finaliser_nuit
# elle-même une fois tous les `wait` revenus.
arreter_toute_la_nuit() {
  local code="$1" raison="$2" limite="${3:-non}"
  if [ "$PAIRES_MODE" = "1" ]; then
    declarer_arret_nuit "$code" "$raison" "$limite"
  else
    RAISON_ARRET_NUIT="$raison"
    [ "$limite" = "oui" ] && LIMITE_SESSION_TOUCHEE="oui"
    finaliser_nuit
  fi
  exit "$code"
}

# Sonde d'écran (#305, complément de spec 05/09 17:00) : lit LES DEUX panes
# de la partie toutes les 10s, PENDANT TOUTE LA PARTIE (pas seulement à la
# détection d'un processus sorti, et pas seulement à mi-timeout comme #299)
# — mesure du 05/09 16:43-17:00 (deux runs de plus) : les deux runs qui ont
# survécu étaient les deux qui tournaient sous une sonde équivalente ; deux
# observations ne prouvent rien, mais la sonde est gratuite et donne l'écran
# au moment exact d'une sortie, morte ou vive. Journalise dans
# `partie-NN/ecran-<role>.log` (bloc horodaté, 12 dernières lignes du pane),
# DÉDOUBLONNÉ : n'ajoute une entrée que si le contenu du pane a changé depuis
# la dernière lecture de CE rôle — un pane inchangé entre deux tours ne noie
# pas le journal. Tourne dans un SUBSHELL bash détaché (`&`), jamais une
# boucle d'attente qui bloquerait ce script (Issue #244) : ce n'est pas un
# poll d'attente d'un fichier, c'est une observation continue en tâche de
# fond, tuée par `arreter_sonde_ecran` (appelée depuis `fermer_panes`, donc
# sur CHAQUE chemin qui ferme les panes de la partie — timeout, craquement,
# STOP/PAUSE/-FinA, fin normale, interruption Ctrl+C).
demarrer_sonde_ecran() {
  local partie_dir="$1" pane_mj="$2" pane_joueur="$3"
  (
    dernier_mj=""
    dernier_joueur=""
    while true; do
      if [ -n "$pane_mj" ]; then
        contenu_mj="$(herdr pane read "$pane_mj" --lines 12 2>/dev/null)"
        if [ "$contenu_mj" != "$dernier_mj" ]; then
          { echo "--- $(date '+%Y-%m-%d %H:%M:%S') ---"; printf '%s\n' "$contenu_mj"; } \
            >> "$partie_dir/ecran-mj.log"
          dernier_mj="$contenu_mj"
        fi
      fi
      if [ -n "$pane_joueur" ]; then
        contenu_joueur="$(herdr pane read "$pane_joueur" --lines 12 2>/dev/null)"
        if [ "$contenu_joueur" != "$dernier_joueur" ]; then
          { echo "--- $(date '+%Y-%m-%d %H:%M:%S') ---"; printf '%s\n' "$contenu_joueur"; } \
            >> "$partie_dir/ecran-joueur.log"
          dernier_joueur="$contenu_joueur"
        fi
      fi
      sleep 10
    done
  ) &
  PID_SONDE=$!
}

# Arrête la sonde d'écran de la partie courante — idempotent (aucun effet si
# aucune sonde n'est en vol, ex. partie craquée avant le lancement).
arreter_sonde_ecran() {
  if [ -n "$PID_SONDE" ]; then
    kill "$PID_SONDE" 2>/dev/null
    wait "$PID_SONDE" 2>/dev/null
    PID_SONDE=""
  fi
}

# 30 dernières lignes du journal de sonde du rôle $2 ("mj"|"joueur") de la
# partie $1 — cité par le craquement `processus-sorti` (#305), à côté du
# `herdr pane read` ponctuel déjà capturé à la détection : la sonde couvre
# l'INSTANT de la sortie (relevé toutes les 10s), le `pane read` ponctuel
# seulement l'instant de la détection (jusqu'à 10s plus tard).
journal_ecran_role() {
  local partie_dir="$1" role="$2"
  tail -n 30 "$partie_dir/ecran-$role.log" 2>/dev/null
}

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
  #
  # $1/$2 (#282, défauts "banc-mj"/"banc-joueur") : noms d'agent réels de
  # CETTE paire — suffixés par paire en parallèle (-Paires > 1) pour que le
  # message d'avertissement nomme le bon agent.
  #
  # Arrête d'abord la sonde d'écran (#305) — jamais un process de sonde
  # laissé en vol après la fermeture des panes qu'elle lit.
  arreter_sonde_ecran
  local agent_mj="${1:-banc-mj}" agent_joueur="${2:-banc-joueur}"
  local p sortie nom
  for p in "$PANE_MJ_COURANT" "$PANE_JOUEUR_COURANT"; do
    [ -n "$p" ] || continue
    if [ "$p" = "$PANE_MJ_COURANT" ]; then nom="$agent_mj"; else nom="$agent_joueur"; fi
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

# Ferme TOUS les panes encore ouverts dans le workspace dédié au banc de
# cette nuit ($WORKSPACE_LABEL_BANC, #298) -- appelée une seule fois, à la
# toute fin de la nuit (finaliser_nuit, tout chemin d'arrêt confondu), APRÈS
# que chaque partie a déjà fermé ses propres panes MJ/joueur
# (fermer_et_verifier_agents) : filet de sécurité pour tout pane résiduel
# (ex. le pane ancre créé avec le workspace, jamais utilisé par une partie).
# Déléguée à fermer-workspace-banc.sh (extrait pour être testable avec un
# faux herdr, même discipline que verifier-agents-en-vol.sh) -- ce script ne
# ferme JAMAIS le workspace lui-même (pas de `herdr workspace close`, garde
# symétrique de circuit.sh nettoyer) : il ne disparaît que devenu vide, par
# la fermeture normale de ses panes.
fermer_panes_workspace_banc() {
  "$REPO_ROOT/tools/banc/fermer-workspace-banc.sh" "$WORKSPACE_LABEL_BANC"
}

# "1" si l'agent nommé $1 apparaît dans `herdr agent list`, vide sinon.
agent_existe() {
  herdr agent list 2>/dev/null | grep -q "\"name\":\"$1\"" && echo 1
}

# "1" si l'agent nommé $1 est SORTI du point de vue du PROCESSUS (#305) : le
# pane reste vivant (« Resume this session with: claude --resume <id> »
# affiché dedans) mais `herdr agent get` ne détecte plus aucun agent —
# `agent_not_found`. Distinct d'un agent « muet » (#299, encore détecté par
# `herdr agent list`, juste silencieux) : un processus sorti ne progressera
# JAMAIS tant qu'il n'est pas relancé, une relance mi-timeout (`herdr agent
# prompt`) tombe alors dans le vide — constat #299 mis à jour 05/09 (runs de
# 15:00/15:09/16:35), le banc attendait 6 min un agent déjà mort.
agent_processus_sorti() {
  local nom="$1" sortie
  sortie="$(herdr agent get "$nom" 2>&1)"
  if [ $? -ne 0 ] && printf '%s' "$sortie" | grep -q 'agent_not_found'; then
    echo 1
  fi
}

# Pane courant de la partie pour le rôle $1 ("joueur"|"mj").
pane_pour_role() {
  if [ "$1" = "joueur" ]; then printf '%s' "$PANE_JOUEUR_COURANT"
  else printf '%s' "$PANE_MJ_COURANT"; fi
}

# Relance un agent dont le PROCESSUS claude est sorti (#305) : lit dans le
# pane la commande de reprise affichée par Claude Code à la sortie
# (« Resume this session with: claude --resume <id> »), relance `herdr agent
# start` DANS LE MÊME PANE avec `--resume <id>` comme ARGUMENT AGENT (après
# `--`, comme `--model`/`--effort`/`--permission-mode` — jamais une option de
# `herdr` lui-même, qui n'en a pas), ATTEND l'interactive_ready (`agent
# prompt ... --wait --until working --timeout 15000`, même idiome que le
# lancement initial dans `lancer-banc-fumee.ps1`) puis renvoie le go du tour
# en cours à l'identique (`go_texte`). Rend 0 SEULEMENT si toute la séquence
# a réussi jusqu'à la réception effective du go, 1 sinon (id de session
# introuvable dans le pane, `herdr agent start` a échoué, ou le go n'a
# jamais été reçu sous 15s) — variables GLOBALES en sortie (même convention
# que RELANCE_ENVOYEE/TRANSCRIPTION_TIMEOUT, #299) :
# - ID_SESSION_PROCESSUS : id de session lu dans le pane (vide si
#   introuvable).
# - PANE_LOG_PROCESSUS : 30 dernières lignes du pane, capturées AVANT la
#   tentative — utiles au craquement même si la relance échoue aussi.
relancer_processus_sorti() {
  local agent="$1" role="$2" modele="$3" effort="$4" go_texte="$5"
  local pane; pane="$(pane_pour_role "$role")"
  PANE_LOG_PROCESSUS="$(herdr pane read "$pane" --lines 30 2>/dev/null)"
  ID_SESSION_PROCESSUS="$(printf '%s' "$PANE_LOG_PROCESSUS" \
    | grep -oE 'claude --resume [A-Za-z0-9._-]+' | tail -1 | sed 's/^claude --resume //')"
  [ -n "$pane" ] || return 1
  [ -n "$ID_SESSION_PROCESSUS" ] || return 1
  if ! herdr agent start "$agent" --kind claude --pane "$pane" \
       -- --resume "$ID_SESSION_PROCESSUS" --model "$modele" --effort "$effort" \
       --permission-mode acceptEdits >/dev/null 2>&1; then
    return 1
  fi
  # Attend l'`interactive_ready` avant d'envoyer le go (revue REFUS #305) :
  # `agent start` a déjà attendu la détection interactive dans le pane (son
  # propre --timeout, 30s par défaut) mais un `claude --resume` fraîchement
  # redémarré peut rester quelques secondes de plus avant d'accepter
  # vraiment un prompt — même idiome que `lancer-banc-fumee.ps1` au premier
  # lancement (`agent prompt ... --wait --until working --timeout 15000`),
  # ici l'échec d'envoi est PROPAGÉ dans le code de retour (jamais un OK qui
  # ne certifierait que `agent start`, pas la réception réelle du go).
  if ! herdr agent prompt "$agent" "$go_texte" --wait --until working --timeout 15000 >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

# Envoie /exit à un agent via `send-keys` — JAMAIS `agent prompt` depuis bash
# (#271, annexe : "/exit" y est réécrit "C:/Program Files/Git/exit" par la
# conversion de chemin MSYS de Git Bash). Une touche à la fois (aucun
# argument ne commence par "/") pour ne déclencher aucune conversion.
envoyer_exit_agent() {
  local nom="$1"
  herdr agent send-keys "$nom" slash e x i t enter >/dev/null 2>&1
}

# Attend (bornée 30 s, #271) que ni $1 (agent MJ) ni $2 (agent joueur) —
# défauts "banc-mj"/"banc-joueur", suffixés par paire en parallèle (#282) —
# n'apparaissent plus dans `herdr agent list`. Rend 0 si les deux sont
# partis, 1 sinon.
attendre_agents_fermes() {
  local agent_mj="${1:-banc-mj}" agent_joueur="${2:-banc-joueur}"
  local n=0 max=15   # 15 * 2s = 30s
  while [ "$n" -lt "$max" ]; do
    if [ -z "$(agent_existe "$agent_mj")" ] && [ -z "$(agent_existe "$agent_joueur")" ]; then
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
  local partie_dir="$1" nn="$2" agent_mj="${3:-banc-mj}" agent_joueur="${4:-banc-joueur}"
  fermer_panes "$agent_mj" "$agent_joueur"
  if attendre_agents_fermes "$agent_mj" "$agent_joueur"; then
    return 0
  fi
  echo "AVERTISSEMENT : agent(s) survivant(s) après fermeture des panes (#271) — envoi /exit." >&2
  local nom
  for nom in "$agent_mj" "$agent_joueur"; do
    [ -n "$(agent_existe "$nom")" ] && envoyer_exit_agent "$nom"
  done
  if attendre_agents_fermes "$agent_mj" "$agent_joueur"; then
    return 0
  fi
  local survivants=""
  for nom in "$agent_mj" "$agent_joueur"; do
    [ -n "$(agent_existe "$nom")" ] && survivants="$survivants $nom"
  done
  ecrire_craquement "$partie_dir" "$nn" "nettoyage" \
    "agent(s) non fermé(s) après pane close + /exit (#271) :$survivants"
  arreter_toute_la_nuit 7 "agent non fermé (partie $nn :$survivants)"
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
# #260), 8 (heure de fin -FinA atteinte — arrêt de TOUTE la nuit, #276), 9
# (processus sorti, relance impossible ou déjà tentée — craquement LOCAL à
# la partie, #305).
#
# $4 (agent_attendu) / $5 (role_attendu, "joueur"|"mj") / $6 (nn, numéro de
# tour) — Issue #299 : à mi-timeout sans fichier, relance UNE FOIS l'agent
# attendu (`herdr agent prompt`) plutôt que d'attendre en silence jusqu'au
# craquement — constat N1/partie 03 et bench/nuit-20260905/partie-04 : un
# agent (joueur Haiku, puis Director Haiku) se tait après un appel d'outil,
# sans erreur ni relance, jusqu'au craquement `timeout` (6 min perdus).
# $7 (modele_attendu) / $8 (effort_attendu) / $9 (go_texte_attendu) —
# Issue #305 : à CHAQUE relevé (pas seulement mi-timeout), si `herdr agent
# get $agent_attendu` rend `agent_not_found`, le PROCESSUS claude est sorti
# (pane vivant, « muet » est un diagnostic différent, #299) — relance
# immédiate dans le même pane (`relancer_processus_sorti`, mêmes
# modèle/effort/permission-mode que le lancement) plutôt que d'attendre le
# timeout sur un mort (constat #299 mis à jour 05/09 : runs de 15:00/15:09/
# 16:35, 6 min perdues à chaque fois). Une seule relance de PROCESSUS par
# appel (donc par tour) : la seconde sortie détectée craque directement
# (retour 9).
# Variables GLOBALES en sortie (relues par l'appelant pour le craquement,
# une fonction bash ne peut pas rendre une chaîne) :
# - RELANCE_ENVOYEE : "oui"/"non" — une relance mi-timeout a-t-elle été
#   envoyée (#299).
# - TRANSCRIPTION_TIMEOUT : 30 dernières lignes de `herdr agent read
#   $agent_attendu`, capturées AVANT toute fermeture de pane (#299 point 2 —
#   aujourd'hui l'écran est perdu avec le pane, seule la transcription de
#   session Claude Code restait lisible après coup).
# - RELANCE_PROCESSUS_ENVOYEE : "oui"/"non" — une relance de processus a-t-elle
#   été tentée (#305).
# - ID_SESSION_PROCESSUS / PANE_LOG_PROCESSUS : id de session lu dans le pane
#   et ses 30 dernières lignes (#305, `herdr agent read` est impossible sur un
#   processus sorti — l'agent n'existe plus, seul le pane reste lisible).
attendre_fichier() {
  local fichier="$1" agent_mj="${2:-banc-mj}" agent_joueur="${3:-banc-joueur}"
  local agent_attendu="${4:-}" role_attendu="${5:-}" nn="${6:-}"
  local modele_attendu="${7:-}" effort_attendu="${8:-}" go_texte_attendu="${9:-}"
  local n=0 bloque_polls=0
  local max_polls=$(( (TIMEOUT_TOUR_SECS + POLL_SECS - 1) / POLL_SECS ))
  local max_polls_bloque=$(( (LIMITE_SESSION_IDLE_SECS + POLL_SECS - 1) / POLL_SECS ))
  local mi_polls=$(( max_polls / 2 )); [ "$mi_polls" -ge 1 ] || mi_polls=1
  RELANCE_ENVOYEE="non"
  TRANSCRIPTION_TIMEOUT=""
  RELANCE_PROCESSUS_ENVOYEE="non"
  ID_SESSION_PROCESSUS=""
  PANE_LOG_PROCESSUS=""
  while [ ! -s "$fichier" ]; do
    if arret_demande; then
      echo "ARRÊT DEMANDÉ (fichier STOP/PAUSE détecté, #271)"
      return 3
    fi
    if fin_a_atteinte; then
      echo "HEURE DE FIN ATTEINTE ($FIN_A, #276)"
      return 8
    fi
    if [ -n "$agent_attendu" ] && [ -n "$(agent_processus_sorti "$agent_attendu")" ]; then
      if [ "$RELANCE_PROCESSUS_ENVOYEE" = "non" ]; then
        RELANCE_PROCESSUS_ENVOYEE="oui"
        if relancer_processus_sorti "$agent_attendu" "$role_attendu" "$modele_attendu" \
             "$effort_attendu" "$go_texte_attendu"; then
          echo "PROCESSUS SORTI ($role_attendu, tour $nn) — reprise --resume $ID_SESSION_PROCESSUS : OK"
          sleep "$POLL_SECS"
          continue
        else
          echo "PROCESSUS SORTI ($role_attendu, tour $nn) — reprise --resume $ID_SESSION_PROCESSUS : ÉCHEC"
          return 9
        fi
      else
        PANE_LOG_PROCESSUS="$(herdr pane read "$(pane_pour_role "$role_attendu")" --lines 30 2>/dev/null)"
        echo "PROCESSUS SORTI À NOUVEAU ($role_attendu, tour $nn) après relance — craquement (#305)"
        return 9
      fi
    fi
    if [ -n "$(limite_session_detectee)" ]; then
      echo "LIMITE DE SESSION (texte détecté dans un pane)"
      return 5
    fi
    if [ -n "$(agent_est_bloque "$agent_mj")" ] || [ -n "$(agent_est_bloque "$agent_joueur")" ]; then
      bloque_polls=$((bloque_polls + 1))
      if [ "$bloque_polls" -ge "$max_polls_bloque" ]; then
        echo "LIMITE DE SESSION (agent bloqué, idle > $((LIMITE_SESSION_IDLE_SECS / 60)) min sans progrès)"
        return 5
      fi
    else
      bloque_polls=0
    fi
    n=$((n + 1))
    if [ "$RELANCE_ENVOYEE" = "non" ] && [ "$n" -ge "$mi_polls" ] && [ -n "$agent_attendu" ]; then
      echo "RELANCE (mi-timeout, tour $nn) : $role_attendu=$agent_attendu n'a pas écrit $(basename "$fichier") — renvoi"
      herdr agent prompt "$agent_attendu" \
        "relance — tour $nn : le fichier $fichier n'est pas écrit, reprends là où tu en es et écris-le" \
        >/dev/null 2>&1
      RELANCE_ENVOYEE="oui"
    fi
    if [ "$n" -gt "$max_polls" ]; then
      echo "TIMEOUT tour (> ${TIMEOUT_TOUR_MIN}min) en attendant $(basename "$fichier")"
      if [ -n "$agent_attendu" ]; then
        TRANSCRIPTION_TIMEOUT="$(herdr agent read "$agent_attendu" 2>/dev/null | tail -30)"
      fi
      return 4
    fi
    sleep "$POLL_SECS"
  done
  return 0
}

# Détection MÉCANIQUE de fin de partie (#306) — remplace l'ancien proxy
# joueur-mort-seul : vrai désormais si (a) joueur mort (`rpg.player.conditions`
# contient "dead", proxy historique inchangé), OU (b) le nœud courant de la
# save (même lecture que coderain/assembleur_position.py — position +
# module.json → partition → nodes/<id>.md) est un nœud TERMINAL de la
# partition (`liens: []` + `charniere_sortie` présente, id != "avant-propos").
# Voir tools/banc/detecter_fin.py — aucun LLM, aucun jugement narratif (hors
# périmètre #260/#306 : "aucun LLM dans le script"). Rend deux GLOBALES,
# relues par l'appelant (une fonction bash ne peut pas rendre deux valeurs) :
# - FIN_COURANTE : "non"|"mort"|"fin_module".
# - NOEUD_ATTEINT_COURANT : id du nœud courant, ou "(aucun)" si aucune
#   position lisible — LA mesure de progression écrite dans resume-run.md à
#   chaque sortie (tours_max, craquement, fin de partie), pas seulement fin
#   atteinte.
FIN_COURANTE="non"
NOEUD_ATTEINT_COURANT="(aucun)"
detecter_fin_partie() {
  local save_dir="$1"
  # Frontière bash ⊥ Windows (#270) : chemin_windows_depuis_bash avant tout
  # appel Python — même garde que chemin_windows_depuis_bash ci-dessus.
  local save_dir_win; save_dir_win="$(chemin_windows_depuis_bash "$save_dir")"
  local sortie
  sortie="$(python "$DETECTER_FIN_PY" "$save_dir_win" 2>/dev/null)"
  FIN_COURANTE="$(printf '%s\n' "$sortie" | grep '^fin:' | sed 's/^fin: *//')"
  NOEUD_ATTEINT_COURANT="$(printf '%s\n' "$sortie" | grep '^noeud:' | sed 's/^noeud: *//')"
  [ -n "$FIN_COURANTE" ] || FIN_COURANTE="non"
  [ -n "$NOEUD_ATTEINT_COURANT" ] || NOEUD_ATTEINT_COURANT="(aucun)"
}

# Écrit resume-run.md pour une partie interrompue EN COURS DE TOUR par
# STOP/PAUSE ou -FinA (#306) — jusqu'ici cette partie ne recevait AUCUN
# resume-run.md (construire_table_parties la reportait "en cours /
# interrompue", sans nœud), puisque le chemin `arreter_toute_la_nuit`
# n'écrivait jamais resume-run.md avant de sortir tout le script. Appelée
# juste avant `arreter_toute_la_nuit` dans chaque branche STOP/PAUSE/-FinA
# de jouer_partie — `fermer_et_verifier_agents` doit déjà avoir tourné
# (les panes sont fermés avant toute lecture de la save, jamais pendant
# qu'un agent y écrit encore).
enregistrer_interruption_partie() {
  local partie_dir="$1" pnn="$2" modele="$3" tours_joues="$4" paire="$5" \
        save_dest="$6" raison="$7" t0="$8"
  shift 8
  local craquements=("$@")
  detecter_fin_partie "$save_dest"
  ecrire_resume_run "$partie_dir" "$pnn" "$modele" "$tours_joues" "N" "$raison" \
    $(( $(date +%s) - t0 )) "$paire" "$NOEUD_ATTEINT_COURANT" "${craquements[@]}"
}

ecrire_resume_run() {
  local partie_dir="$1" pnn="$2" modele="$3" tours_joues="$4" fin_atteinte="$5" \
        raison="$6" duree_s="$7" paire="$8" noeud="$9"
  shift 9
  local craquements=("$@")
  {
    echo "# resume-run — partie $pnn"
    echo
    echo "casting: joueur=haiku(low) director=$modele(medium) narrateur=haiku"
    # paire (#282) : numéro de la paire Director/joueur qui a joué cette
    # partie — "01" en séquentiel (une seule paire) ; suffixe réel du
    # dossier bench/nuit-AAAAMMJJ/partie-NN/ le cas échéant en parallèle.
    # Relu par tools/banc/metriques_nuit.py::calculer (« Paires simultanées »).
    echo "paire: $paire"
    echo "tours_joues: $tours_joues"
    echo "fin_atteinte: $fin_atteinte"
    echo "raison_arret: $raison"
    # noeud_final (fin atteinte) / noeud_atteint (sinon) — #306 : LA mesure
    # de progression, à chaque sortie (tours_max, craquement, fin de partie),
    # pas seulement quand la partie a fini le module.
    if [ "$fin_atteinte" = "O" ]; then
      echo "noeud_final: ${noeud:-(aucun)}"
    else
      echo "noeud_atteint: ${noeud:-(aucun)}"
    fi
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

# Table des parties (#282) : reconstruite MÉCANIQUEMENT en relisant chaque
# resume-run.md déjà écrit sous $RUN_DIR, plutôt qu'accumulée dans une
# globale au fil de la nuit (TABLE_PARTIES avant #282) — une globale ne
# survit pas au fork d'un subshell de paire (§ 6bis), et cette lecture
# fonctionne identiquement en séquentiel et en parallèle. Une partie sans
# resume-run.md (interrompue en cours de tour par STOP/-FinA/limite de
# session, avant l'écriture normale de fin de jouer_partie) rend une ligne
# "en cours / interrompue" plutôt que d'être absente de la table.
construire_table_parties() {
  local d pnn resume modele tours fin raison noeud
  for d in "$RUN_DIR"/partie-*/; do
    [ -d "$d" ] || continue
    pnn="$(basename "$d" | sed 's/^partie-//')"
    resume="$d/resume-run.md"
    if [ -f "$resume" ]; then
      modele="$(grep -o 'director=[a-zA-Z0-9_-]*' "$resume" | head -1 | sed 's/director=//')"
      tours="$(grep '^tours_joues:' "$resume" | head -1 | sed 's/^tours_joues: *//')"
      fin="$(grep '^fin_atteinte:' "$resume" | head -1 | sed 's/^fin_atteinte: *//')"
      raison="$(grep '^raison_arret:' "$resume" | head -1 | sed 's/^raison_arret: *//')"
      # noeud_final (fin atteinte) OU noeud_atteint (sinon) — #306, un seul
      # des deux existe par resume-run.md (voir ecrire_resume_run).
      noeud="$(grep -E '^noeud_(final|atteint):' "$resume" | head -1 | sed -E 's/^noeud_(final|atteint): *//')"
      echo "| $pnn | ${modele:-?} | ${tours:-0} | ${fin:-N} | ${raison:-?} | ${noeud:-?} |"
    else
      echo "| $pnn | ? | 0 | N | en cours / interrompue | ? |"
    fi
  done
}

ecrire_nuit_md() {
  local duree_s="${1:-$(( $(date +%s) - DEBUT_NUIT ))}"
  local metriques
  metriques="$(python "$METRIQUES_PY" "$RUN_DIR" 2>/dev/null)"
  {
    echo "# nuit — $DATE_JOUR"
    echo
    echo "Save : $SAVE — Director : $DIRECTOR — Paires simultanées : $PAIRES — "\
"Tours max/partie : $TOURS — Timeout tour : ${TIMEOUT_TOUR_MIN}min"\
"${FIN_A:+ — Fin à : $FIN_A}"
    echo
    echo "Durée totale : ${duree_s}s"
    echo "Raison d'arrêt de la nuit : ${RAISON_ARRET_NUIT:-budget -Parties atteint}"
    if [ -n "$AVERTISSEMENT_PRE_NUIT" ]; then
      echo
      echo "## Avertissements"
      echo
      echo "$AVERTISSEMENT_PRE_NUIT"
    fi
    echo
    echo "## Parties"
    echo
    echo "| partie | director | tours joués | fin atteinte | raison | nœud atteint / terminal |"
    echo "|---|---|---|---|---|---|"
    construire_table_parties
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
  # Fermeture des panes du workspace banc (#298) : jamais sous -RunDir (usage
  # interne/tests uniquement, § -RunDir ci-dessus) -- un test tournant sur ce
  # poste pendant qu'une VRAIE nuit joue dans le workspace "$WORKSPACE_LABEL_BANC"
  # ne doit jamais fermer les panes de cette nuit réelle.
  if [ -z "$RUN_DIR_OVERRIDE" ]; then
    fermer_panes_workspace_banc
  fi
  ecrire_rapport_nuit "$duree_s"
  DEPOT_RAPPORT_STATUT="$(deposer_rapport_201)"
  ecrire_nuit_md "$duree_s"
}

# --- 5. Boucle d'une partie ---------------------------------------------------

# $2/$3/$4 (#282, défauts "banc-mj"/"banc-joueur"/"01") : noms d'agent réels
# et numéro de paire de CETTE partie — suffixés par paire en parallèle
# (-Paires > 1, § 6bis) pour qu'aucune paire concurrente ne collisionne sur
# un nom d'agent (#271) ni un pane, chacune sa propre copie de save (déjà
# vrai avant #282, $partie_dir isole toujours chaque partie).
jouer_partie() {
  local rang="$1" agent_mj="${2:-banc-mj}" agent_joueur="${3:-banc-joueur}" paire="${4:-01}"
  local partie_num=$((START_INDEX + rang - 1))
  local pnn; pnn=$(printf '%02d' "$partie_num")
  local partie_dir="$RUN_DIR/partie-$pnn"
  local modele; modele="$(modele_director_pour "$rang")"
  local t0=$(date +%s)
  local raison="" fin_atteinte="N" tours_joues=0
  local craquements=()
  # Modèle/effort de CHAQUE agent réel de cette partie (#305, relance de
  # processus sorti — `herdr agent start ... --resume` doit reprendre à
  # l'identique du lancement initial, `lancer-banc-fumee.ps1`, jamais ni
  # -ModeleMj/-ModeleJoueur ci-dessous, ni le mode `acceptEdits` hardcodé).
  local modele_joueur="haiku" effort_mj="medium" effort_joueur="low"

  PARTIE_DIR_COURANTE="$partie_dir"
  mkdir -p "$partie_dir"
  # Réinitialise les globales de détection de fin (#306) — jamais un résidu
  # de la partie précédente reporté ici si celle-ci craque avant le premier
  # tour joué (fixture, lancement).
  FIN_COURANTE="non"
  NOEUD_ATTEINT_COURANT="(aucun)"

  echo "=== partie $pnn (paire $paire) : copie fraîche de la save '$SAVE' ==="
  local save_dest="$partie_dir/save"
  rm -rf "$save_dest"
  cp -r "$SAVE_SRC_DIR" "$save_dest"

  echo "=== partie $pnn : fixture personnage (#257) ==="
  if ! python "$FIXTURE_PY" "$save_dest" > "$partie_dir/fixture.log" 2>&1; then
    raison="fixture"
    ecrire_craquement "$partie_dir" "00" "fixture" "$(cat "$partie_dir/fixture.log")"
    craquements+=("craquement-fixture-00.md")
    ecrire_resume_run "$partie_dir" "$pnn" "$modele" 0 "N" "$raison" $(( $(date +%s) - t0 )) "$paire" "(aucun)" "${craquements[@]}"
    return 0
  fi

  if [ "$DRYRUN" -eq 1 ]; then
    echo "=== partie $pnn : -DryRun — aucun agent lancé ==="
    ecrire_resume_run "$partie_dir" "$pnn" "$modele" 0 "N" "dry-run" $(( $(date +%s) - t0 )) "$paire" "(aucun)"
    return 0
  fi

  echo "=== partie $pnn : lancement (director=$modele, agents=$agent_mj/$agent_joueur) ==="
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
      -AgentMj "$agent_mj" -AgentJoueur "$agent_joueur" \
      -WorkspaceLabel "$WORKSPACE_LABEL_BANC" \
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
    fermer_et_verifier_agents "$partie_dir" "00" "$agent_mj" "$agent_joueur"
    ecrire_resume_run "$partie_dir" "$pnn" "$modele" 0 "N" "$raison" $(( $(date +%s) - t0 )) "$paire" "(aucun)" "${craquements[@]}"
    if [ "$ECHECS_LANCEMENT_CONSECUTIFS" -ge 2 ]; then
      arreter_toute_la_nuit 6 "lancement impossible (2 échecs de lancement consécutifs, partie $pnn)"
    fi
    return 0
  fi
  ECHECS_LANCEMENT_CONSECUTIFS=0

  # Sonde d'écran (#305) : démarrée dès que les deux panes existent, tourne
  # jusqu'à `fermer_panes` (tout chemin de fin de partie confondu, voir
  # `demarrer_sonde_ecran` ci-dessus).
  demarrer_sonde_ecran "$partie_dir" "$PANE_MJ_COURANT" "$PANE_JOUEUR_COURANT"

  # --- boucle de tours (fil 2, sans LLM dans CE script) ---------------------
  local tour=1
  while [ "$tour" -le "$TOURS" ]; do
    local nn pn r go_ts go_texte_mj go_texte_joueur
    nn=$(printf '%02d' "$tour")
    pn=$(printf '%02d' $((tour - 1)))

    if [ "$tour" -eq 1 ]; then
      # Ouverture (limite assumée #260 — voir README, « ce que la nuit ne
      # fait pas ») : le gabarit banc-mj.md (gelé D-276 §4) ne décrit pas de
      # protocole de tour 1 froid — le MJ ouvre lui-même la scène
      # (opening_scene) plutôt que d'attendre une action joueur inexistante.
      go_texte_mj="go — tour $nn : ouverture, pas d'action joueur — établis la scène d'ouverture (opening_scene) puis écris tour-$nn.md en conséquence"
      go_ts=$(date +%s)
      herdr agent prompt "$agent_mj" "$go_texte_mj" >/dev/null 2>&1
    else
      echo "=== partie $pnn tour $nn — go joueur $(date '+%H:%M:%S')"
      go_texte_joueur="go — tour $nn : lis UNIQUEMENT $partie_dir/prose-$pn.md, joue ton tour (un paragraphe), puis écris-le verbatim dans $partie_dir/action-$nn.md"
      herdr agent prompt "$agent_joueur" "$go_texte_joueur" >/dev/null 2>&1
      attendre_fichier "$partie_dir/action-$nn.md" "$agent_mj" "$agent_joueur" "$agent_joueur" "joueur" "$nn" \
        "$modele_joueur" "$effort_joueur" "$go_texte_joueur"; r=$?
      if [ "$r" -eq 3 ]; then fermer_et_verifier_agents "$partie_dir" "$nn" "$agent_mj" "$agent_joueur"; enregistrer_interruption_partie "$partie_dir" "$pnn" "$modele" "$tours_joues" "$paire" "$save_dest" "arret-demande" "$t0" "${craquements[@]}"; arreter_toute_la_nuit 130 "arrêt demandé (fichier STOP/PAUSE, partie $pnn, tour $nn)"; fi
      if [ "$r" -eq 8 ]; then fermer_et_verifier_agents "$partie_dir" "$nn" "$agent_mj" "$agent_joueur"; enregistrer_interruption_partie "$partie_dir" "$pnn" "$modele" "$tours_joues" "$paire" "$save_dest" "fin-a-atteinte" "$t0" "${craquements[@]}"; arreter_toute_la_nuit 130 "heure de fin atteinte ($FIN_A) (partie $pnn, tour $nn)"; fi
      if [ "$r" -eq 5 ]; then fermer_panes "$agent_mj" "$agent_joueur"; arreter_toute_la_nuit 5 "limite de session (partie $pnn, tour $nn)" "oui"; fi
      if [ "$r" -eq 9 ]; then
        raison="craquement-processus-sorti"
        ecrire_craquement "$partie_dir" "$nn" "processus-sorti" "$(printf \
          'agent : joueur (%s)\nfichier attendu : %s\nid_session : %s\nrelance tentée : %s\n\n--- 30 dernières lignes de `herdr pane read` (détection) ---\n%s\n\n--- 30 dernières lignes de la sonde d'"'"'écran (partie-%s/ecran-joueur.log, #305) ---\n%s\n' \
          "$agent_joueur" "$partie_dir/action-$nn.md" "$ID_SESSION_PROCESSUS" "$RELANCE_PROCESSUS_ENVOYEE" "$PANE_LOG_PROCESSUS" \
          "$pnn" "$(journal_ecran_role "$partie_dir" "joueur")")"
        craquements+=("craquement-processus-sorti-$nn.md")
        detecter_fin_partie "$save_dest"
        break
      fi
      if [ "$r" -ne 0 ]; then
        raison="craquement-timeout"
        ecrire_craquement "$partie_dir" "$nn" "timeout" "$(printf \
          'agent : joueur (%s)\nfichier attendu : %s\nrelance envoyée : %s\n\n--- 30 dernières lignes de `herdr agent read %s` ---\n%s\n' \
          "$agent_joueur" "$partie_dir/action-$nn.md" "$RELANCE_ENVOYEE" "$agent_joueur" "$TRANSCRIPTION_TIMEOUT")"
        craquements+=("craquement-timeout-$nn.md")
        detecter_fin_partie "$save_dest"
        break
      fi
      local action; action="$(cat "$partie_dir/action-$nn.md")"
      echo "=== partie $pnn tour $nn — go MJ $(date '+%H:%M:%S')"
      go_texte_mj="go — tour $nn. Action du joueur (verbatim) : $action"
      go_ts=$(date +%s)
      herdr agent prompt "$agent_mj" "$go_texte_mj" >/dev/null 2>&1
    fi

    attendre_fichier "$partie_dir/tour-$nn.md" "$agent_mj" "$agent_joueur" "$agent_mj" "mj" "$nn" \
      "$modele" "$effort_mj" "$go_texte_mj"; r=$?
    if [ "$r" -eq 3 ]; then fermer_et_verifier_agents "$partie_dir" "$nn" "$agent_mj" "$agent_joueur"; enregistrer_interruption_partie "$partie_dir" "$pnn" "$modele" "$tours_joues" "$paire" "$save_dest" "arret-demande" "$t0" "${craquements[@]}"; arreter_toute_la_nuit 130 "arrêt demandé (fichier STOP/PAUSE, partie $pnn, tour $nn)"; fi
    if [ "$r" -eq 8 ]; then fermer_et_verifier_agents "$partie_dir" "$nn" "$agent_mj" "$agent_joueur"; enregistrer_interruption_partie "$partie_dir" "$pnn" "$modele" "$tours_joues" "$paire" "$save_dest" "fin-a-atteinte" "$t0" "${craquements[@]}"; arreter_toute_la_nuit 130 "heure de fin atteinte ($FIN_A) (partie $pnn, tour $nn)"; fi
    if [ "$r" -eq 5 ]; then fermer_panes "$agent_mj" "$agent_joueur"; arreter_toute_la_nuit 5 "limite de session (partie $pnn, tour $nn)" "oui"; fi
    if [ "$r" -eq 9 ]; then
      raison="craquement-processus-sorti"
      ecrire_craquement "$partie_dir" "$nn" "processus-sorti" "$(printf \
        'agent : mj (%s)\nfichier attendu : %s\nid_session : %s\nrelance tentée : %s\n\n--- 30 dernières lignes de `herdr pane read` (détection) ---\n%s\n\n--- 30 dernières lignes de la sonde d'"'"'écran (partie-%s/ecran-mj.log, #305) ---\n%s\n' \
        "$agent_mj" "$partie_dir/tour-$nn.md" "$ID_SESSION_PROCESSUS" "$RELANCE_PROCESSUS_ENVOYEE" "$PANE_LOG_PROCESSUS" \
        "$pnn" "$(journal_ecran_role "$partie_dir" "mj")")"
      craquements+=("craquement-processus-sorti-$nn.md")
      detecter_fin_partie "$save_dest"
      break
    fi
    if [ "$r" -ne 0 ]; then
      raison="craquement-timeout"
      ecrire_craquement "$partie_dir" "$nn" "timeout" "$(printf \
        'agent : mj (%s)\nfichier attendu : %s\nrelance envoyée : %s\n\n--- 30 dernières lignes de `herdr agent read %s` ---\n%s\n' \
        "$agent_mj" "$partie_dir/tour-$nn.md" "$RELANCE_ENVOYEE" "$agent_mj" "$TRANSCRIPTION_TIMEOUT")"
      craquements+=("craquement-timeout-$nn.md")
      detecter_fin_partie "$save_dest"
      break
    fi

    # Arbitrage MÉCANIQUE de prose-NN.md entre les deux voies du gabarit
    # (Issue #295) : voie extraction (PRIMAIRE, section « Prose du
    # Narrateur » inline imposée par le gabarit dans tour-NN.md, #269),
    # sinon voie fichier (REPLI TOLÉRANT, le MJ a malgré tout écrit
    # prose-NN.md lui-même) — craquement `prose-absente` seulement si
    # aucune des deux n'aboutit, `prose-polluee` si le fichier écrit par le
    # MJ fuite du matériau zéro-spoiler (D-219). Voir
    # tools/banc/arbitrer_prose.py.
    prose_msg="$(python "$ARBITRER_PROSE_PY" "$partie_dir/tour-$nn.md" "$partie_dir/prose-$nn.md" "$go_ts" 2>&1)"
    prose_rc=$?
    if [ "$prose_rc" -eq 2 ]; then
      raison="craquement-prose-polluee"
      ecrire_craquement "$partie_dir" "$nn" "prose-polluee" "$prose_msg"
      craquements+=("craquement-prose-polluee-$nn.md")
      detecter_fin_partie "$save_dest"
      break
    fi
    if [ "$prose_rc" -ne 0 ]; then
      raison="craquement-prose-absente"
      ecrire_craquement "$partie_dir" "$nn" "prose-absente" "$prose_msg"
      craquements+=("craquement-prose-absente-$nn.md")
      detecter_fin_partie "$save_dest"
      break
    fi
    echo "=== partie $pnn tour $nn — prose via $prose_msg $(date '+%H:%M:%S')"

    tours_joues=$tour
    echo "=== partie $pnn tour $nn joué $(date '+%H:%M:%S')"

    # Détection MÉCANIQUE de fin (#306) : mort du joueur OU nœud terminal de
    # la partition (liens: [] + charniere_sortie, id != avant-propos) — voir
    # detecter_fin_partie ci-dessus. NOEUD_ATTEINT_COURANT est relu même
    # quand FIN_COURANTE reste "non" (mesure de progression, écrite dans
    # resume-run.md à toute sortie, pas seulement fin atteinte).
    detecter_fin_partie "$save_dest"
    if [ "$FIN_COURANTE" = "mort" ] || [ "$FIN_COURANTE" = "fin_module" ]; then
      fin_atteinte="O"
      raison="$FIN_COURANTE"
      break
    fi
    tour=$((tour + 1))
  done

  if [ -z "$raison" ]; then
    raison="tours_max"
  fi

  echo "=== partie $pnn : fermeture des agents ==="
  fermer_et_verifier_agents "$partie_dir" "$pnn" "$agent_mj" "$agent_joueur"

  ecrire_resume_run "$partie_dir" "$pnn" "$modele" "$tours_joues" "$fin_atteinte" "$raison" \
    $(( $(date +%s) - t0 )) "$paire" "$NOEUD_ATTEINT_COURANT" "${craquements[@]}"
}

# --- 6. Boucle des parties ----------------------------------------------------

if [ "$PAIRES" -eq 1 ]; then
  # Chemin séquentiel historique (INCHANGÉ depuis #276) — une seule paire,
  # noms d'agent nus "banc-mj"/"banc-joueur", finaliser_nuit appelée
  # directement dans ce process (jamais un subshell). -Parties optionnel
  # (Souhel #279) : sans elle, boucle sans plafond de parties, bornée par
  # -FinA seule (fin_a_atteinte ci-dessous).
  i=1
  while [ -z "$PARTIES" ] || [ "$i" -le "$PARTIES" ]; do
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
    jouer_partie "$i" "banc-mj" "banc-joueur" "01"
    i=$((i + 1))
  done

  finaliser_nuit
  echo "=== nuit $DATE_JOUR terminée : $NUIT_MD ==="
  exit 0
fi

# --- 6bis. Boucle des parties en PARALLÈLE (#282) ----------------------------
#
# N paires (slots 1..PAIRES) tournent SIMULTANÉMENT, chacune dans son propre
# subshell bash (`&`, un vrai process forké — pas une coroutine) : agents
# "banc-mj-<slot>"/"banc-joueur-<slot>" (jamais de collision de nom, #271),
# copie de save et .turn/ étanche de la partie qu'elle joue (Issue #287,
# `.turn/` dérive de la save chargée). Chaque slot reprend la partie suivante du budget
# -Parties dès qu'il se libère — jusqu'à épuisement du budget ou -FinA.
#
# Le budget des rangs (1..PARTIES, comme la boucle séquentielle ci-dessus)
# est distribué par `mkdir` atomique (prochain_rang) : un `mkdir` ne réussit
# qu'à UN SEUL appelant même entre process concurrents sur le même système
# de fichiers — aucun verrou externe (flock) n'est nécessaire ni disponible
# de façon portable sous Git Bash/Windows.
#
# Nettoyage : STOP/PAUSE/-FinA/limite de session sont déclarés une seule
# fois dans $ARRET_DIR (déclarer_arret_nuit) par la première paire qui les
# détecte ; finaliser_nuit ne tourne qu'ICI, une fois TOUS les `wait`
# revenus (jamais dans un subshell de paire — voir arreter_toute_la_nuit).
# fermer_toutes_paires_en_vol est un FILET après coup (agent qu'une paire
# n'aurait pas réussi à fermer elle-même) — la fermeture normale reste
# fermer_et_verifier_agents, appelée par CHAQUE paire pour ELLE-MÊME.
PAIRES_MODE=1
rm -rf "$ARRET_DIR" "$RUN_DIR"/.claim-*   # jamais un résidu d'un appel précédent sur ce -RunDir

prochain_rang() {
  # -Parties optionnel (Souhel #279) : quand elle n'est pas donnée, aucun
  # plafond de rang ici -- le budget en parallèle reste alors borné par
  # -FinA seule (contrôlée par slot_boucle avant chaque appel), jamais par
  # ce compteur.
  local n=1
  while [ -z "$PARTIES" ] || [ "$n" -le "$PARTIES" ]; do
    if mkdir "$RUN_DIR/.claim-$n" 2>/dev/null; then
      echo "$n"
      return 0
    fi
    n=$((n + 1))
  done
  return 1
}

# Ferme au mieux tout agent banc-mj*/banc-joueur* encore listé par herdr en
# fin de nuit parallèle (#282) — filet de sécurité, jamais le chemin normal
# (fermer_et_verifier_agents, appelé par chaque paire pour elle-même avant
# de rendre la main).
fermer_toutes_paires_en_vol() {
  local json noms nom pane
  json="$(herdr agent list 2>/dev/null)"
  [ -n "$json" ] || return 0
  noms="$(printf '%s' "$json" | tr '{' '\n' \
    | grep -oE '"name":"banc-(mj|joueur)(-[0-9]+)?"' \
    | sed -E 's/.*"([^"]+)"$/\1/' | sort -u)"
  [ -n "$noms" ] || return 0
  echo "AVERTISSEMENT : agent(s) du banc encore en vol en fin de nuit parallèle (#282) — fermeture :$(printf ' %s' $noms)" >&2
  while IFS= read -r nom; do
    [ -n "$nom" ] || continue
    pane="$(printf '%s' "$json" | tr '{' '\n' | grep "\"name\":\"$nom\"" \
      | grep -oE '"pane_id":"[^"]+"' | head -1 | sed -E 's/.*:"([^"]+)"/\1/')"
    [ -n "$pane" ] && herdr pane close "$pane" >/dev/null 2>&1
    [ -n "$(agent_existe "$nom")" ] && envoyer_exit_agent "$nom"
  done <<< "$noms"
}

# Un slot joue, en boucle, la partie suivante du budget jusqu'à épuisement
# ou arrêt de toute la nuit déclaré par une AUTRE paire.
slot_boucle() {
  local slot="$1" rang
  local agent_mj="banc-mj-$slot" agent_joueur="banc-joueur-$slot"
  local paire; paire=$(printf '%02d' "$slot")
  while true; do
    if [ -d "$ARRET_DIR" ] || arret_demande || fin_a_atteinte; then
      return 0
    fi
    rang="$(prochain_rang)" || return 0   # budget -Parties épuisé
    jouer_partie "$rang" "$agent_mj" "$agent_joueur" "$paire"
  done
}

N_SLOTS="$PAIRES"
# -Parties optionnel (Souhel #279) : sans elle, aucun plafond de rangs à
# comparer -- tous les slots demandés tournent (bornés par -FinA seule).
if [ -n "$PARTIES" ] && [ "$N_SLOTS" -gt "$PARTIES" ]; then
  N_SLOTS="$PARTIES"
fi

PIDS=()
for (( s = 1; s <= N_SLOTS; s++ )); do
  ( slot_boucle "$s" ) &
  PIDS+=("$!")
done

for pid in "${PIDS[@]}"; do
  wait "$pid"
done

fermer_toutes_paires_en_vol

if [ -d "$ARRET_DIR" ]; then
  RAISON_ARRET_NUIT="$(cat "$ARRET_DIR/raison" 2>/dev/null)"
  LIMITE_SESSION_TOUCHEE="$(cat "$ARRET_DIR/limite_session" 2>/dev/null)"
  [ -n "$LIMITE_SESSION_TOUCHEE" ] || LIMITE_SESSION_TOUCHEE="non"
  CODE_SORTIE="$(cat "$ARRET_DIR/code" 2>/dev/null)"
  [ -n "$CODE_SORTIE" ] || CODE_SORTIE=1
else
  CODE_SORTIE=0
fi

finaliser_nuit
echo "=== nuit $DATE_JOUR terminée ($PAIRES paires) : $NUIT_MD ==="
exit "$CODE_SORTIE"
