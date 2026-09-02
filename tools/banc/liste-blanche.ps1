<#
.SYNOPSIS
    Gabarit de liste blanche du banc (Issue #267) : fonction extraite,
    partagée entre tools/lancer-banc-fumee.ps1 (pose réelle) et les tests
    (fonction appelée directement sur des fichiers synthétiques).

.DESCRIPTION
    Constat #267 (nuit N0, 02/09) : tools/lancer-banc-fumee.ps1 (#210, #224)
    posait la liste blanche `Bash(*)` + `mcp__coderain-engine__*` dans
    .claude\settings.local.json UNIQUEMENT si le fichier était absent. Sur un
    poste où ce fichier existait déjà -- plus ancien, plus étroit (cinq
    outils moteur, pas de Bash) -- rien n'était complété : le lanceur
    journalisait « déjà présent, non modifié » alors que la liste blanche
    réelle était incomplète, et les agents du banc redemandaient des
    autorisations à la main toute la nuit.

    Assure-ListeBlancheBanc GARANTIT la liste blanche plutôt que de se
    contenter de poser le fichier s'il est absent :
    - fichier absent : comportement historique inchangé (création complète).
    - fichier présent, JSON valide : ajoute les entrées `allow` du gabarit
      manquantes et les `deny` du gabarit manquants, SANS retirer quoi que ce
      soit que l'opérateur y a mis (autres entrées allow/deny, autres clés du
      fichier) ; réécrit en UTF-8 seulement si quelque chose a été ajouté.
    - fichier présent, JSON invalide : REFUS explicite (Status 'refus'),
      jamais un écrasement -- l'appelant décide quoi faire du refus (le
      lanceur s'arrête, la garde avant-nuit affiche le message).
#>

# Gabarit de liste blanche du banc -- même contenu que l'ancien bloc figé de
# lancer-banc-fumee.ps1 (issu de #210, complété #224) : Bash(*) et l'accès
# complet aux outils MCP du moteur (les deux agents jouent leurs tours via
# `coderain-engine`, jamais via Bash seul -- revue PR #224), plus les cinq
# refus explicites (jamais de --no-verify/--force en automode, cf. règle
# fixe CLAUDE.md).
$script:AllowGabaritBanc = @('Bash(*)', 'mcp__coderain-engine__*')
$script:DenyGabaritBanc = @(
    'Bash(git commit --no-verify*)',
    'Bash(git commit -n*)',
    'Bash(git push --no-verify*)',
    'Bash(git push --force*)',
    'Bash(git push -f*)'
)

function Assure-ListeBlancheBanc {
    <#
    .PARAMETER SettingsLocalPath
        Chemin du .claude\settings.local.json à garantir.

    .OUTPUTS
        Objet [pscustomobject] :
        - Status : 'cree' (fichier neuf posé), 'complete' (entrées
          manquantes ajoutées à un fichier existant), 'deja_complet'
          (rien à ajouter), 'refus' (JSON invalide, rien écrit).
        - Ajouts : liste des entrées allow/deny ajoutées (vide sauf
          'cree'/'complete').
        - Message : phrase de journal prête à afficher (Write-Output côté
          appelant).
    #>
    param(
        [Parameter(Mandatory)] [string]$SettingsLocalPath
    )

    if (-not (Test-Path $SettingsLocalPath)) {
        $claudeDir = Split-Path -Parent $SettingsLocalPath
        New-Item -ItemType Directory -Force -Path $claudeDir | Out-Null
        $settingsLocal = [ordered]@{
            permissions = [ordered]@{
                allow = @($script:AllowGabaritBanc)
                deny  = @($script:DenyGabaritBanc)
            }
        }
        ($settingsLocal | ConvertTo-Json -Depth 5) | Set-Content -Path $SettingsLocalPath -Encoding utf8
        return [pscustomobject]@{
            Status  = 'cree'
            Ajouts  = @($script:AllowGabaritBanc + $script:DenyGabaritBanc)
            Message = "Automode posé : $SettingsLocalPath"
        }
    }

    $raw = Get-Content -Path $SettingsLocalPath -Raw -Encoding utf8
    try {
        $json = $raw | ConvertFrom-Json -ErrorAction Stop
    } catch {
        return [pscustomobject]@{
            Status  = 'refus'
            Ajouts  = @()
            Message = "REFUS : $SettingsLocalPath existe mais n'est pas un JSON valide ($($_.Exception.Message)) -- jamais d'écrasement, corrige-le à la main."
        }
    }

    # Le fichier peut être n'importe quel JSON valide dépourvu de
    # `permissions`, ou de `permissions.allow`/`permissions.deny` -- on les
    # crée au besoin, sans toucher aux autres clés déjà présentes.
    if (-not ($json.PSObject.Properties.Name -contains 'permissions')) {
        $json | Add-Member -MemberType NoteProperty -Name 'permissions' -Value ([pscustomobject]@{ allow = @(); deny = @() })
    }
    if (-not ($json.permissions.PSObject.Properties.Name -contains 'allow')) {
        $json.permissions | Add-Member -MemberType NoteProperty -Name 'allow' -Value @()
    }
    if (-not ($json.permissions.PSObject.Properties.Name -contains 'deny')) {
        $json.permissions | Add-Member -MemberType NoteProperty -Name 'deny' -Value @()
    }

    $allowActuel = @($json.permissions.allow)
    $denyActuel = @($json.permissions.deny)

    $allowManquants = @($script:AllowGabaritBanc | Where-Object { $allowActuel -notcontains $_ })
    $denyManquants = @($script:DenyGabaritBanc | Where-Object { $denyActuel -notcontains $_ })

    if ($allowManquants.Count -eq 0 -and $denyManquants.Count -eq 0) {
        return [pscustomobject]@{
            Status  = 'deja_complet'
            Ajouts  = @()
            Message = "Automode déjà complet, non modifié : $SettingsLocalPath"
        }
    }

    $json.permissions.allow = @($allowActuel + $allowManquants)
    $json.permissions.deny = @($denyActuel + $denyManquants)
    ($json | ConvertTo-Json -Depth 10) | Set-Content -Path $SettingsLocalPath -Encoding utf8

    $ajouts = @($allowManquants + $denyManquants)
    return [pscustomobject]@{
        Status  = 'complete'
        Ajouts  = $ajouts
        Message = "Automode complété ($SettingsLocalPath) : " + ($ajouts -join ', ')
    }
}
