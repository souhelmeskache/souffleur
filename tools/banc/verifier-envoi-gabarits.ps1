<#
.SYNOPSIS
    Envoi à blanc des deux gabarits rendus (banc-mj.md / banc-joueur.md) vers
    un agent herdr inexistant — garde du point d'envoi (#263, complément
    verifier-avant-nuit.sh).

.DESCRIPTION
    Exerce EXACTEMENT le même point d'envoi que tools/lancer-banc-fumee.ps1
    (rendu des gabarits avec Get-Content -Raw + Invoke-NativeCommand, I-385) :
    si un `"` interne à l'un des deux gabarits casse l'échappement Win32, le
    parsing `herdr agent prompt` échoue AVANT même de chercher l'agent
    (`unknown option`, rc 2). Contre un agent qu'on sait inexistant, le seul
    échec attendu est `agent_not_found` (rc 1) — tout rc 2 est un signal
    d'échappement cassé, pas d'agent manquant.

    N'ouvre aucun pane, ne lance aucun agent, n'écrit aucun fichier. Rend un
    JSON en sortie standard : { "ok": bool, "rc_mj": int, "rc_joueur": int,
    "stderr_mj": str, "stderr_joueur": str }. `ok` est vrai seulement si les
    DEUX envois rendent rc=1 (agent_not_found).

.EXAMPLE
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\banc\verifier-envoi-gabarits.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function Resolve-ExternalCommand {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string[]]$FallbackPaths
    )
    $found = Get-Command $Name -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    foreach ($path in $FallbackPaths) {
        if (Test-Path $path) { return $path }
    }
    Write-Error "Commande '$Name' introuvable : ni dans le PATH, ni aux chemins de repli connus ($($FallbackPaths -join ', '))."
    exit 1
}

$HerdrExe = Resolve-ExternalCommand -Name 'herdr' -FallbackPaths @("$env:LOCALAPPDATA\Programs\Herdr\bin\herdr.exe")
$RepoRoot = (git -C $PSScriptRoot rev-parse --show-toplevel).Trim()

# --- Même échappement que lancer-banc-fumee.ps1 (I-385, #263) --------------

function ConvertTo-Win32Arg {
    param([Parameter(Mandatory)] [AllowEmptyString()] [string]$Value)
    if ($Value -eq '') { return '""' }
    if ($Value -notmatch '[\s"]') { return $Value }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $len = $Value.Length
    for ($i = 0; $i -lt $len; $i++) {
        $numBackslashes = 0
        while ($i -lt $len -and $Value[$i] -eq '\') { $numBackslashes++; $i++ }
        if ($i -eq $len) {
            [void]$sb.Append('\' * ($numBackslashes * 2))
        } elseif ($Value[$i] -eq '"') {
            [void]$sb.Append('\' * ($numBackslashes * 2 + 1))
            [void]$sb.Append('"')
        } else {
            [void]$sb.Append('\' * $numBackslashes)
            [void]$sb.Append($Value[$i])
        }
    }
    [void]$sb.Append('"')
    return $sb.ToString()
}

function Invoke-NativeCommandCaptureStderr {
    param(
        [Parameter(Mandatory)] [string]$FilePath,
        [Parameter(Mandatory)] [string[]]$Arguments
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = ($Arguments | ForEach-Object { ConvertTo-Win32Arg $_ }) -join ' '
    $psi.UseShellExecute = $false
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardOutput = $true
    $p = [System.Diagnostics.Process]::Start($psi)
    $stderrText = $p.StandardError.ReadToEnd()
    $stdoutText = $p.StandardOutput.ReadToEnd()
    $p.WaitForExit()
    return @{ rc = $p.ExitCode; stderr = $stderrText; stdout = $stdoutText }
}

# --- Rendu des deux gabarits, valeurs factices --------------------------

function Get-GabaritRempli {
    param([Parameter(Mandatory)] [string]$CheminGabarit)
    $texte = Get-Content -Path $CheminGabarit -Raw -Encoding utf8
    $texte = $texte.Replace('{{SAVE}}', 'garde-envoi-a-blanc')
    $texte = $texte.Replace('{{TOURS}}', '1')
    $texte = $texte.Replace('{{SESSION_TOUR}}', 'garde-envoi-a-blanc')
    $texte = $texte.Replace('{{JOURNAL_DIR}}', 'garde-envoi-a-blanc')
    return $texte
}

$PromptMj = Get-GabaritRempli -CheminGabarit (Join-Path $RepoRoot 'tools\prompts\banc-mj.md')
$PromptJoueur = Get-GabaritRempli -CheminGabarit (Join-Path $RepoRoot 'tools\prompts\banc-joueur.md')

$AgentInexistant = 'garde-envoi-agent-inexistant-263'

$resMj = Invoke-NativeCommandCaptureStderr -FilePath $HerdrExe -Arguments @('agent', 'prompt', $AgentInexistant, $PromptMj)
$resJoueur = Invoke-NativeCommandCaptureStderr -FilePath $HerdrExe -Arguments @('agent', 'prompt', $AgentInexistant, $PromptJoueur)

$ok = ($resMj.rc -eq 1) -and ($resJoueur.rc -eq 1)

$out = [ordered]@{
    ok            = $ok
    rc_mj         = $resMj.rc
    rc_joueur     = $resJoueur.rc
    stderr_mj     = $resMj.stderr.Trim()
    stderr_joueur = $resJoueur.stderr.Trim()
}
($out | ConvertTo-Json -Depth 3)
if (-not $ok) { exit 1 }
exit 0
