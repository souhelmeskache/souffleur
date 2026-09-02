#!/bin/bash
# tools/banc/verifier-liste-blanche-nuit.sh — garde extraite de
# verifier-avant-nuit.sh (Issue #267) : REFUSE si le settings.local.json
# donné existe et ne porte pas les deux entrées `allow` requises pour le
# banc (Bash(*), mcp__coderain-engine__*), ou n'est pas du JSON valide.
# Fichier absent : rien à vérifier, OK (tools/lancer-banc-fumee.ps1 le
# posera complet au lancement).
#
# Extraite en script indépendant pour être testable sans dépendre de
# herdr/gh/claude (prérequis du reste de verifier-avant-nuit.sh) — voir
# tests/verifier_liste_blanche_nuit_test.py.
#
# Usage : tools/banc/verifier-liste-blanche-nuit.sh <chemin-settings.local.json>
# Sortie : "OK" et code 0 si absent ou complet ; message REFUS sur stderr et
# code non nul sinon.
set -u

SETTINGS_LOCAL="${1:?usage : verifier-liste-blanche-nuit.sh <chemin-settings.local.json>}"

refus() {
  echo "REFUS : $1" >&2
  exit 1
}

if [ ! -f "$SETTINGS_LOCAL" ]; then
  echo "OK : $SETTINGS_LOCAL absent (sera posé complet au lancement)."
  exit 0
fi

MANQUANTS="$(python -c "
import json, sys
try:
    with open(r'$SETTINGS_LOCAL', encoding='utf-8-sig') as f:
        data = json.load(f)
except Exception as e:
    print('JSON_INVALIDE: ' + str(e))
    sys.exit(0)
allow = data.get('permissions', {}).get('allow', [])
requis = ['Bash(*)', 'mcp__coderain-engine__*']
manquants = [r for r in requis if r not in allow]
if manquants:
    print(', '.join(manquants))
" 2>&1)"

if [ -n "$MANQUANTS" ]; then
  if [ "${MANQUANTS#JSON_INVALIDE: }" != "$MANQUANTS" ]; then
    refus "$SETTINGS_LOCAL n'est pas un JSON valide (${MANQUANTS#JSON_INVALIDE: }) — corrige-le à la main avant de relancer une nuit."
  fi
  refus "$SETTINGS_LOCAL n'a pas la liste blanche complète du banc — entrée(s) manquante(s) dans permissions.allow : $MANQUANTS (relance tools/lancer-banc-fumee.ps1, qui la complète désormais — #267)."
fi

echo "OK : $SETTINGS_LOCAL porte la liste blanche complète du banc."
exit 0
