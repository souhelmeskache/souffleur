#!/bin/bash
# Alias de compatibilité (I-250) : solder-issue.sh <ISSUE> == circuit.sh
# veiller <ISSUE>. La veille toutes phases (attente PR, CI, revue, merge,
# renvoi automatique sur REFUS) vit désormais dans circuit.sh — ce script ne
# fait plus que déléguer, gardé pour l'habitude d'appel du poste META.
exec bash "$(dirname "$0")/circuit.sh" veiller "$1"
