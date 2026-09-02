#!/bin/bash
# tools/banc/chemin-windows.sh — frontière bash ⊥ Windows (Issue #270).
#
# Un chemin produit sous Git Bash (`pwd`, `$REPO_ROOT`, `$partie_dir`, tout
# dérivé de `cd ... && pwd`) est en forme `/c/Users/...` — valide pour bash,
# INVALIDE pour tout binaire Windows natif (python.exe, powershell.exe) qui
# le reçoit en argument, en variable d'environnement, ou dans un chemin
# littéral côté script : `/c/Users/x` y est lu comme un chemin RACINE DE LA
# LECTEUR COURANT (`C:\c\Users\x`), silencieusement faux — jamais une
# erreur bruyante (#270 : la garde de #267 refusait toute nuit pour cette
# raison, message trompeur ; nuit.sh l'a aussi, côté SAVES_DIR/JournalDir —
# constat identique, même script).
#
# Règle : jamais un chemin `pwd` brut vers Python/PowerShell — le convertir
# d'abord avec `chemin_windows_depuis_bash`. Voir tools/banc/README.md.
#
# À sourcer, pas à exécuter : `source "$(dirname "${BASH_SOURCE[0]}")/chemin-windows.sh"`.

# chemin_windows_depuis_bash <chemin> — imprime la conversion Windows sur
# stdout. Idempotent : un chemin déjà en forme Windows (`C:/...`, `C:\...`)
# ou un chemin bash sans lettre de lecteur (`/home/x`, `/tmp/x`, relatif)
# ressort inchangé. Préfère `cygpath -w` (Git Bash le fournit toujours) ;
# repli par normalisation regex si `cygpath` est absent (ex. Bash non-Git).
chemin_windows_depuis_bash() {
  local chemin="$1"
  case "$chemin" in
    [A-Za-z]:/*|[A-Za-z]:\\*)
      # Déjà en forme Windows (lettre de lecteur) — rien à faire.
      printf '%s\n' "$chemin"
      return 0
      ;;
  esac
  case "$chemin" in
    /[a-zA-Z]/*)
      # Forme Git Bash reconnue (lettre de lecteur en premier segment) —
      # seul cas à traduire. `cygpath -w` d'abord (Git Bash le fournit
      # toujours) ; repli par normalisation regex sinon (ex. Bash non-Git).
      if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$chemin"
        return 0
      fi
      local lettre="${chemin:1:1}"
      local reste="${chemin:2}"
      printf '%s%s\n' "${lettre^^}:" "$reste"
      ;;
    *)
      # /home/x, /tmp/x, chemin relatif — inchangé : pas de lettre de
      # lecteur en tête, donc pas un chemin traversant la frontière Windows
      # (et `cygpath -w` le résoudrait via un mount MSYS, ce qui n'est PAS
      # "inchangé" — hors contrat de cette fonction).
      printf '%s\n' "$chemin"
      ;;
  esac
}
