# tools/refus-haiku-auto.ps1 — refus nommé du couple Haiku + mode `auto`
# (Issue #276, cadrage complémentaire 03/09).
#
# `--permission-mode auto` n'existe pas pour Haiku : Claude Code retombe
# ALORS EN SILENCE en mode manuel, et un agent de nuit gèle à la première
# question posée à personne (aucun humain ne répond jamais, #260/#261 —
# c'est le même risque de gel que la liste blanche du banc, tools/banc/liste-blanche.ps1,
# mais côté choix du modèle plutôt que côté outils). Fonction PARTAGÉE entre
# tools/lancer-banc-fumee.ps1 et tools/lancer-lane.ps1 : appelée avant TOUT
# `herdr agent start`, dans les deux scripts.
#
# `$Modele` est comparé insensible à la casse, alias ou identifiant complet
# (« haiku », « claude-haiku-4-5-20251001 ») — toute occurrence du mot
# « haiku » suffit à qualifier le modèle.
function Assure-ModeAutoCompatibleAvecModele {
    param(
        [Parameter(Mandatory)] [string]$Modele,
        [Parameter(Mandatory)] [string]$PermissionMode
    )
    $estHaiku = $Modele -imatch 'haiku'
    $estModeAuto = $PermissionMode -eq 'auto'
    if ($estHaiku -and $estModeAuto) {
        Write-Error ("REFUS : le mode auto n'existe pas pour Haiku (repli silencieux en manuel, " +
            "un agent de nuit gèlerait à la première question posée à personne) — " +
            "utiliser acceptEdits + liste blanche (banc) ou un modèle sonnet/opus (lanes).")
        exit 1
    }
}
