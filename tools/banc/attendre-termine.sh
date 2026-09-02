#!/bin/bash
# Alias de compatibilité (I-250) : attendre-termine.sh <ISSUE> <PR> == circuit.sh
# veiller <ISSUE>. Le cycle "attend un TERMINÉ posté après un REFUS" est
# maintenant une phase de circuit.sh veiller (rejoué automatiquement, au
# plus 2 cycles) — ce script ne fait plus que déléguer ; le second argument
# <PR> n'est plus nécessaire (veiller le redécouvre lui-même) mais reste
# accepté pour compatibilité d'appel.
exec bash "$(dirname "$0")/circuit.sh" veiller "$1"
