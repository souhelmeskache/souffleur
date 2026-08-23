[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Once,
    [switch]$Install,
    [int]$IntervalleSecondes = 300,
    [string]$RepoMoteur,
    [string]$VaultRoot,
    # I-275 livrable 15 (D-192 amendee) : regime permanent CONDITIONNEL. Defaut OFF =
    # comportement 6/jour inchangé ; ON = le plafond de CONCURRENCE (3 lanes) devient le
    # seul garde de volume, le compteur sessionsJour reste tenu au journal mais ne refuse plus rien.
    [switch]$SessionsIllimitees
)

$ErrorActionPreference = 'Stop'

# ---- Constantes des gardes (D-191 palier v1)
$MAX_SESSIONS_JOUR  = 6
$MAX_LANES_ACTIVES  = 3
$LOCK_STALE_HEURES  = 6
# I-275 livrable 3 : borne anti-boucle — apres N echecs consecutifs d'une meme fiche,
# elle sort de la file jusqu'a intervention.
$MAX_ECHECS_CONSECUTIFS = 2
$CI_REPO            = 'souhelmeskache/ttrpg-mvp'

# ---- Chemins (declares, jamais supposes)
$PostRoot = [System.IO.Path]::GetDirectoryName($PSCommandPath)
if (-not $VaultRoot) { $VaultRoot = [System.IO.Path]::GetDirectoryName($PostRoot) }
$MetaDir   = Join-Path $VaultRoot 'meta-rpg'
$E3E2Path  = Join-Path $MetaDir 'E3-E2-cycle-et-chantiers.md'
$StatePath = Join-Path $PostRoot 'veilleur-state.json'
$LogPath   = Join-Path $PostRoot 'veilleur.log'
$LockPath  = Join-Path $PostRoot 'veilleur-meta.lock'
# I-275 livrable 10 : verrou d'instance par PID (le mutex seul a laisse passer des doublons
# lors des cycles mort/relance de la tache planifiee du 2026-08-23).
$PidLockPath = Join-Path $PostRoot 'veilleur-instance.lock'
$EveilTemplate = Join-Path $PostRoot 'eveil-meta.md'
if (-not $RepoMoteur) { $RepoMoteur = Join-Path $env:USERPROFILE 'coderain' }

function Write-VeilLog {
    param([string]$Message, [string]$Niveau = 'INFO')
    $ligne = "{0} [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Niveau, $Message
    Write-Host $ligne
    if (-not $DryRun) { Write-Tolerant ({ Add-Content -LiteralPath $LogPath -Value $ligne -Encoding UTF8 }) "journal ($Niveau)" }
}

function Fail {
    param([string]$Message)
    Write-Host "[veilleur] ECHEC : $Message" -ForegroundColor Red
    exit 1
}

# ---- I-275 livrable 6 : ECRITURE TOLERANTE AUX VERROUS.
# La cause de mort capturee en direct le 2026-08-23 a 15:43 : Add-Content vers le digest en
# IOException (« fichier en cours d'utilisation par un autre processus ») avec
# $ErrorActionPreference='Stop' => le processus mourait ENTRE lancement de lane et ecritures,
# sans jamais atteindre sa ligne « tour termine » (compteurs jamais sauvegardes, relances).
# Desormais : toute ecriture digest/log/state passe en retry borne (3 x 500 ms) puis, si
# l'echec persiste, JOURNALISE [ERROR] sans tuer le processus.
# NB : cette fonction N'EMET RIEN vers le pipeline — les fonctions qui l'appellent et qui
# retournent une valeur (Test-LockMeta, Test-InstanceLock) ne doivent pas etre polluees.
function Write-Tolerant {
    param([scriptblock]$Action, [string]$Quoi)
    for ($essai = 1; $essai -le 3; $essai++) {
        try { & $Action; return }
        catch {
            if ($essai -lt 3) { Start-Sleep -Milliseconds 500 }
            else {
                $msg = $_.Exception.Message
                Write-Host ("[ERROR] ecriture '{0}' abandonnee apres 3 essais (retry 3x500ms) : {1}" -f $Quoi, $msg) -ForegroundColor Red
                try {
                    Add-Content -LiteralPath $LogPath -Value ("{0} [ERROR] ecriture '{1}' abandonnee apres 3 essais (retry 3x500ms) : {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Quoi, $msg) -Encoding UTF8
                } catch { Write-Host "[ERROR] journal inaccessible lui aussi - ecriture perdue pour ce tour" -ForegroundColor Red }
            }
        }
    }
    return
}

# ---- -Install : enregistre la tache planifiee Windows (geste de Souhel, ses autorisations)
if ($Install) {
    $taskName = 'MRPG-Veilleur'
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "[veilleur] la tache '$taskName' existe deja - rien fait. Pour la retirer : schtasks /Delete /TN $taskName" -ForegroundColor Yellow
        exit 0
    }
    $action   = New-ScheduledTaskAction -Execute 'powershell.exe' `
                -Argument ("-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"{0}`"" -f $PSCommandPath)
    $trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable `
                -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    # I-275 livrable 10 : StopOnIdleEnd=false — sans lui, le veilleur cache mourait chaque
    # fois que Souhel reprenait la main (morts de ~14:28, 15:32, 15:40 du 2026-08-23).
    $settings.IdleSettings.StopOnIdleEnd = $false
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
        -Description 'Veilleur de la boucle (D-191 palier v1) - surveille rapports/fiches/CI et reveille les sessions.' | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Write-Host "[veilleur] tache '$taskName' enregistree et demarree (declenchement a l'ouverture de session, boucle toutes les $IntervalleSecondes s)." -ForegroundColor Green
    exit 0
}

foreach ($f in @($StatePath, $EveilTemplate)) {
    if (-not (Test-Path -LiteralPath $f)) { Fail "fichier requis introuvable : $f" }
}
$hasGh = $null -ne (Get-Command gh -ErrorAction SilentlyContinue)

# ---- Garde anti-instance multiple (mutex nomme, portee machine) + verrou PID (livrable 10)
# Deux couches : le mutex exclut deux boucles vivantes ; le fichier a PID retient l'identite
# du detenteur — si un processus traine malgre un mutex rendu (cycle abandonne/relance de la
# tache), le second demarrage refuse avec [WARN] au lieu de doubler la premiere instance.
$mutex = New-Object System.Threading.Mutex($false, 'Global\MRPG-Veilleur')
$acquis = $false
try {
    $acquis = $mutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    # Le detenteur precedent est MORT sans relacher : le mutex nous est remis par le
    # runtime. C'est exactement le cas qui faisait echouer (ou doubler) les redemarrages.
    $acquis = $true
    Write-VeilLog "mutex abandonne par une instance morte - repris par cette instance" 'WARN'
}
if (-not $acquis) {
    Write-Host "[WARN] instance deja active (mutex Global\MRPG-Veilleur tenu) - sortie." -ForegroundColor Yellow
    exit 0
}
function Test-InstanceLock {
    if (-not (Test-Path -LiteralPath $PidLockPath)) { return $null }
    $contenu = (Get-Content -LiteralPath $PidLockPath -Raw -ErrorAction SilentlyContinue)
    if ($contenu -match '^\s*(\d+)\s') {
        $pidAvant = [int]$Matches[1]
        if ($pidAvant -ne $PID -and (Get-Process -Id $pidAvant -ErrorAction SilentlyContinue)) {
            return $pidAvant
        }
    }
    Write-VeilLog "verrou d'instance obsolete (pid mort ou illisible) - ecrase" 'WARN'
    return $null
}
$pidVivant = Test-InstanceLock
if ($null -ne $pidVivant) {
    Write-Host ("[WARN] instance deja active (pid {0}) - sortie." -f $pidVivant) -ForegroundColor Yellow
    $null = $mutex.ReleaseMutex(); $mutex.Dispose()
    exit 0
}
if (-not $DryRun) { Write-Tolerant ({ Set-Content -LiteralPath $PidLockPath -Value ("{0} {1}" -f $PID, (Get-Date -Format o)) -Encoding ASCII }) "verrou d'instance" }

# ---- Etat
$state = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json

# Champs ajoutes par I-275 : tolerer un state anterieur qui ne les porte pas encore.
if (-not $state.PSObject.Properties['lanesLancees'])  { $state | Add-Member -NotePropertyName 'lanesLancees'  -NotePropertyValue @() -Force }
if (-not $state.PSObject.Properties['fichesBannies']) { $state | Add-Member -NotePropertyName 'fichesBannies' -NotePropertyValue @() -Force }
if (-not $state.PSObject.Properties['echecsParFiche']){ $state | Add-Member -NotePropertyName 'echecsParFiche'-NotePropertyValue ([pscustomobject]@{}) -Force }

function Save-State {
    # I-275 livrable 3 : une fiche que l'appelant VIENT DE RETIRER (echec constate de
    # nouvelle-lane) ne doit pas etre ressuscitee par la fusion ci-dessous — le disque
    # porte encore la marque posee AVANT lancement. D'ou le parametre -Exclure.
    param([string[]]$Exclure = @())
    if ($DryRun) { return }
    # ---- I-275 livrable 5 : FUSION ANTI-ECRASEMENT avant ecriture.
    # Les deux remises a zero du 2026-08-23 (~13:15 et entre 14:00 et 14:16) sont le fait
    # d'instances successives a memoire perimee : Save-State serialise L'ETAT ENTIER de
    # l'instance courante, donc une instance demarree avant les dernieres mutations efface
    # tout ce qu'une autre a consigne entre-temps. Desormais on RELIT le fichier et on
    # fusionne ce qui ne doit jamais retrograder : fiches lancees, fiches bannies, compteur
    # d'echecs (max), sessionsJour du jour (max). Le reste suit la memoire de l'instance.
    try {
        $brut = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8
        if ($brut) {
            $auDisque = $brut | ConvertFrom-Json
            if ($auDisque -and $auDisque.jour -eq $state.jour -and `
                ([int]$auDisque.sessionsJour -gt [int]$state.sessionsJour)) {
                $state.sessionsJour = [int]$auDisque.sessionsJour
            }
            foreach ($f in @($auDisque.lanesLancees)) {
                if ($f -and (@($state.lanesLancees) -notcontains $f) -and (@($Exclure) -notcontains $f)) { $state.lanesLancees = @($state.lanesLancees) + $f }
            }
            # apres fusion, honorer quand meme les exclusions demandees
            if ($Exclure.Count -gt 0) { $state.lanesLancees = @($state.lanesLancees | Where-Object { @($Exclure) -notcontains $_ }) }
            foreach ($f in @($auDisque.fichesBannies)) {
                if ($f -and (@($state.fichesBannies) -notcontains $f)) { $state.fichesBannies = @($state.fichesBannies) + $f }
            }
            if ($auDisque.echecsParFiche) {
                foreach ($p in $auDisque.echecsParFiche.PSObject.Properties) {
                    $actuel = $state.echecsParFiche.PSObject.Properties[$p.Name]
                    if (-not $actuel) {
                        $state.echecsParFiche | Add-Member -NotePropertyName $p.Name -NotePropertyValue ([int]$p.Value) -Force
                    } elseif (([int]$p.Value) -gt ([int]$actuel.Value)) {
                        $state.echecsParFiche.PSObject.Properties[$p.Name].Value = [int]$p.Value
                    }
                }
            }
        }
    } catch { Write-VeilLog ("fusion anti-ecrasement impossible (state illisible ?) - ecriture directe : {0}" -f $_.Exception.Message) 'WARN' }
    Write-Tolerant ({ $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $StatePath -Encoding UTF8 }) 'state'
}

function Update-Jour {
    $today = Get-Date -Format 'yyyy-MM-dd'
    if ($state.jour -ne $today) {
        $state.jour = $today
        $state.sessionsJour = 0
        Write-VeilLog ("nouveau jour {0} - compteur quotidien remis a zero" -f $today)
    }
}

function Get-BudgetRestant {
    # I-275 livrable 15 : regime -SessionsIllimitees => le budget ne refuse plus rien ;
    # le plafond de concurrence ($MAX_LANES_ACTIVES) reste le seul garde de volume.
    if ($SessionsIllimitees) { return [int]::MaxValue }
    return ($MAX_SESSIONS_JOUR - [int]$state.sessionsJour)
}

function Test-LockMeta {
    # CONSERVATEUR (lecon du double reveil de 11:55/12:00) : tout verrou PRESENT
    # bloque, quel que soit son contenu. Un seul format est ecrit - par Invoke-WakeMeta,
    # "<PID> <horodatage ISO>" - et relu par ce meme code ; un format inconnu est
    # RESPECTE comme signal d'activite (jamais traite comme etranger/inerte).
    if (-not (Test-Path -LiteralPath $LockPath)) { return $false }
    $contenu = (Get-Content -LiteralPath $LockPath -Raw -ErrorAction SilentlyContinue)
    if ($contenu -notmatch '^\d+\s+\d{4}-\d{2}-\d{2}T') {
        Write-VeilLog "verrou meta au format inconnu - RESPECTE par precaution : reveil refuse" 'WARN'
        return $true
    }
    $ageH = ((Get-Date) - (Get-Item -LiteralPath $LockPath).LastWriteTime).TotalHours
    if ($ageH -gt $LOCK_STALE_HEURES) {
        Write-VeilLog ("verrou meta obsolete ({0:N1} h) - ignore" -f $ageH) 'GARDE'
        return $false
    }
    return $true
}

function Invoke-WakeMeta {
    param([string]$Motif, [string]$Rapport)
    if (Test-LockMeta) {
        Write-VeilLog "garde verrou meta : une session meta est deja active - reveil refuse" 'GARDE'
        return $false
    }
    if ((Get-BudgetRestant) -le 0) {
        Write-VeilLog ("garde volume : plafond {0} sessions/jour atteint - reveil refuse ({1})" -f $MAX_SESSIONS_JOUR, $Motif) 'GARDE'
        return $false
    }
    $template = Get-Content -LiteralPath $EveilTemplate -Raw -Encoding UTF8
    $prompt = $template.Replace('{{MOTIF}}', $Motif).Replace('{{RAPPORT}}', $Rapport)
    if ($DryRun) {
        Write-Host "[veilleur][DRYRUN] lancerais une session meta (motif : $Motif) avec le prompt :" -ForegroundColor Magenta
        Write-Host "--- debut prompt ---"
        Write-Host $prompt
        Write-Host "--- fin prompt ---"
        Write-Host "[veilleur][DRYRUN] commande equivalente : prompt ecrit dans un fichier temporaire, puis 'opencode run' depuis $MetaDir avec le contenu du fichier en message (fenetre dediee, verrou $LockPath)" -ForegroundColor Magenta
        return $true
    }
    # Le prompt voyage par FICHIER, jamais par la ligne de commande : le premier
    # positionnel d'opencode est un CHEMIN DE PROJET ('opencode [project]') - coller
    # le prompt en argument faisait echouer le changement de repertoire (bug du
    # 2026-08-23). L'appel passe par -EncodedCommand (base64) : insensible aux
    # espaces et guillemets que Start-Process sinon deformait.
    $horodatage = Get-Date -Format 'yyyyMMdd-HHmmss'
    $promptFile = Join-Path ([System.IO.Path]::GetTempPath()) ("eveil-meta-{0}.md" -f $horodatage)
    $proofLog   = Join-Path $PostRoot ("preuve-session-meta-{0}.log" -f $horodatage)
    Set-Content -LiteralPath $promptFile -Value $prompt -Encoding UTF8
    Write-Tolerant ({ Set-Content -LiteralPath $LockPath -Value ("{0} {1}" -f $PID, (Get-Date -Format o)) -Encoding ASCII }) 'verrou meta'
    $inner = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; chcp 65001 | Out-Null; " +
             "Set-Location -LiteralPath '$MetaDir'; " +
             "`$p = Get-Content -LiteralPath '$promptFile' -Raw -Encoding UTF8; " +
             "opencode.cmd run `$p 2>&1 | Tee-Object -FilePath '$proofLog' -Append; " +
             "Remove-Item -LiteralPath '$promptFile' -ErrorAction SilentlyContinue; " +
             "Remove-Item -LiteralPath '$LockPath' -ErrorAction SilentlyContinue"
    $b64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $b64)
    $state.sessionsJour = [int]$state.sessionsJour + 1
    Write-VeilLog ("session meta lancee - motif : {0} - budget journalier : {1}/{2}" -f $Motif, $state.sessionsJour, $MAX_SESSIONS_JOUR)
    Add-Digest ("reveil META ({0}) - rapport : {1}" -f $Motif, $Rapport)
    return $true
}

function Add-Digest {
    param([string]$Ligne)
    if ($DryRun) { return }
    $digestPath = Join-Path $PostRoot ("digest-{0}.md" -f (Get-Date -Format 'yyyy-MM-dd'))
    if (-not (Test-Path -LiteralPath $digestPath)) {
        Write-Tolerant ({ Set-Content -LiteralPath $digestPath -Value ("# Digest du veilleur - {0}`n" -f (Get-Date -Format 'yyyy-MM-dd')) -Encoding UTF8 }) 'digest (creation)'
    }
    # I-275 livrable 6 : c'est ICI que le processus est mort en direct le 2026-08-23 a 15:43
    # (IOException, fichier tenu par un autre processus). Desormais retry borne + [ERROR]
    # journalise, jamais mortel : le tour atteint toujours sa ligne « tour termine ».
    Write-Tolerant ({ Add-Content -LiteralPath $digestPath -Value ("- {0} - {1}" -f (Get-Date -Format 'HH:mm:ss'), $Ligne) -Encoding UTF8 }) "digest ($Ligne)"
}

function Invoke-LaunchLane {
    param([string]$Nom, [string]$Fiche)
    if ((Get-BudgetRestant) -le 0) {
        Write-VeilLog ("garde volume : plafond {0} sessions/jour atteint - lane '{1}' non lancee" -f $MAX_SESSIONS_JOUR, $Nom) 'GARDE'
        return $false
    }
    $etatLanes = Get-LanesActives
    if (-not $etatLanes.Disponible) { return $false }
    if (@($etatLanes.Lanes).Count -ge $MAX_LANES_ACTIVES) {
        Write-VeilLog ("garde slots : {0}/{1} slots occupes - lane '{2}' non lancee" -f @($etatLanes.Lanes).Count, $MAX_LANES_ACTIVES, $Nom) 'GARDE'
        return $false
    }
    if ($DryRun) {
        Write-Host "[veilleur][DRYRUN] lancerais : .\nouvelle-lane.ps1 -Nom $Nom -Fiche `"$Fiche`"" -ForegroundColor Magenta
        return $true
    }
    # ---- I-275 livrable 1 : MEMOIRE DU DEJA-LANCE — la fiche est marquee AVANT le lancement
    # et l'etat sauvegarde IMMEDIATEMENT. Si le processus meurt entre lancement et ecriture
    # (classe de crash du burst 13:56 -> relances 14:16/14:23), la fiche reste consignee :
    # elle ne repart JAMAIS au tour suivant, session morte ou pas. Le declencheur « lanable »
    # est ainsi consomme par son lancement ou neutralise par cette memoire.
    if (@($state.lanesLancees) -notcontains $Fiche) { $state.lanesLancees = @($state.lanesLancees) + $Fiche }
    Save-State
    Write-VeilLog "lane '${Nom}' : lancement via nouvelle-lane.ps1 (fiche : $Fiche)"
    & (Join-Path $PostRoot 'nouvelle-lane.ps1') -Nom $Nom -Fiche $Fiche
    if ($LASTEXITCODE -ne 0) {
        # Verification du code sortie (v1.1) : un echec enfant ne tue pas le parent. La marque
        # du deja-lance est RETIREE (v1.1 : retentee au prochain tour si la cause disparait)
        # MAIS l'echec coute desormais (livrable 3) : compteur d'echecs consecutifs PAR fiche ;
        # apres N echecs, la fiche sort de la file jusqu'a intervention.
        $state.lanesLancees = @($state.lanesLancees | Where-Object { $_ -ne $Fiche })
        $n = 0
        $prop = $state.echecsParFiche.PSObject.Properties[$Fiche]
        if ($prop) { $n = [int]$prop.Value }
        $n = $n + 1
        if ($prop) { $prop.Value = $n } else { $state.echecsParFiche | Add-Member -NotePropertyName $Fiche -NotePropertyValue $n -Force }
        Write-VeilLog ("lane '{0}' : nouvelle-lane.ps1 en echec (code sortie {1}) - echec no {2}/{3} pour cette fiche ; sessionsJour intact ; retee au prochain tour si la cause disparait" -f $Nom, $LASTEXITCODE, $n, $MAX_ECHECS_CONSECUTIFS) 'WARN'
        Add-Digest ("lane '{0}' : ECHEC de nouvelle-lane.ps1 (code sortie {1}) - compteurs intacts" -f $Nom, $LASTEXITCODE)
        if ($n -ge $MAX_ECHECS_CONSECUTIFS) {
            $state.fichesBannies = @($state.fichesBannies) + $Fiche
            # le compteur RESTE a N : apres deban manuel, un nouvel echec re-bannit aussitot
            Write-VeilLog ("lane '{0}' : {1} echecs consecutifs - FICHE SORTIE DE FILE jusqu'a intervention (retirer son chemin de 'fichesBannies' dans veilleur-state.json)" -f $Nom, $MAX_ECHECS_CONSECUTIFS) 'WARN'
            Add-Digest ("[WARN] lane '{0}' bannie apres {1} echecs consecutifs - sortie de file jusqu'a intervention" -f $Nom, $MAX_ECHECS_CONSECUTIFS)
        }
        Save-State -Exclure @($Fiche)
        return $false
    }
    $state.sessionsJour = [int]$state.sessionsJour + 1
    Add-Digest ("lane '{0}' lancee - fiche : {1}" -f $Nom, $Fiche)
    Save-State
    return $true
}

function Get-LanesActives {
    # Definition DECLAREE (correction du 2026-08-23) : un worktree compte comme ACTIF si
    #   (a) sa branche n'est PAS fusionnee dans main, OU
    #   (b) il porte des modifications non enregistrees (= travaille en ce moment).
    # Un worktree fini (fusionne, propre) ne bloque plus aucun slot - meme si son dernier
    # commit est recent : mesure du 2026-08-23, les trois lanes finies l'etaient CE MATIN
    # (09:33-10:11), un critere sur la date de commit les aurait re-bloquees.
    # Contrat v1.1 : renvoie TOUJOURS un objet - Disponible=$false si le depot est
    # illisible (surveillance coupee ce tour), sinon Lanes=@(...) meme VIDE. Avant cette
    # correction, un tableau vide etait deroule en $null par le retour de fonction et le
    # garde appelant le confondait avec l'echec : zero lane active => refus SILENCIEUX de
    # lancer (decouvert par le DryRun de preuve du 2026-08-23).
    if (-not (Test-Path -LiteralPath (Join-Path $RepoMoteur '.git'))) {
        Write-VeilLog "depot moteur introuvable ($RepoMoteur) - surveillance lanes desactivee ce tour" 'WARN'
        return [pscustomobject]@{ Disponible = $false; Lanes = @() }
    }
    $wt = @(& git -C $RepoMoteur worktree list --porcelain 2>$null)
    if ($LASTEXITCODE -ne 0) {
        Write-VeilLog "git worktree list a echoue sur $RepoMoteur - surveillance lanes desactivee ce tour" 'WARN'
        return [pscustomobject]@{ Disponible = $false; Lanes = @() }
    }
    $entries = @()
    $courant = $null
    foreach ($l in $wt) {
        if ($l -like 'worktree *') {
            if ($courant) { $entries += $courant }
            $courant = [pscustomobject]@{ Chemin = $l.Substring('worktree '.Length); Branche = '' }
        } elseif ($l -like 'branch *' -and $courant) {
            $courant.Branche = ($l.Substring('branch '.Length)) -replace '^refs/heads/', ''
        }
    }
    if ($courant) { $entries += $courant }

    # git rend les chemins en slash avant ; normaliser pour exclure le depot racine,
    # qui n'est pas une lane (c'est lui qui gonflait le comptage a 5).
    $racineNorm = $RepoMoteur -replace '/', '\'

    $nonFusionnees = @()
    $nf = & git -C $RepoMoteur branch --no-merged main --format '%(refname:short)' 2>$null
    if ($LASTEXITCODE -eq 0) { $nonFusionnees = @($nf | Where-Object { $_ }) }

    $actives = @()
    foreach ($e in ($entries | Where-Object { ($_.Chemin -replace '/', '\') -ne $racineNorm })) {
        if (-not $e.Branche) { $actives += $e.Chemin; continue }  # HEAD detache : conservateur => actif
        if ($nonFusionnees -contains $e.Branche) { $actives += $e.Chemin; continue }
        $dirty = @(& git -C $e.Chemin status --porcelain 2>$null | Where-Object { $_ -ne '' })
        if ($LASTEXITCODE -eq 0 -and $dirty.Count -gt 0) { $actives += $e.Chemin }
    }
    return [pscustomobject]@{ Disponible = $true; Lanes = @($actives) }
}

function Get-Lancables {
    # Definition (declaree) : ligne du tableau §lanes de E3-E2 contenant 'lanable',
    # sans marqueur de cloture (livre/ferme/merge). Le chemin de fiche est le lien markdown.
    if (-not (Test-Path -LiteralPath $E3E2Path)) {
        Write-VeilLog "file E3-E2 introuvable : $E3E2Path" 'WARN'
        return @()
    }
    $lignes = Get-Content -LiteralPath $E3E2Path -Encoding UTF8
    $resultats = @()
    foreach ($l in $lignes) {
        if ($l -notmatch '^\|') { continue }
        # v1.1 : les cellules sont examinees INDIVIDUELLEMENT. L'ancienne exclusion
        # frappait TOUTE la ligne ('livr|ferm|merg' n'importe ou) : un mot de cloture
        # dans une cellule quelconque rendait une fiche « lanable » invisible SANS
        # AUCUN log (cas reel du 2026-08-23 ~13:16). Desormais le marqueur de cloture
        # ne compte que dans la cellule d'etat (derniere colonne), et toute fiche
        # ecartee malgre le mot « lanable » produit un [WARN] citant la cause.
        $cells = @($l.Trim().Trim('|').Split('|') | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
        if (($cells -join ' ') -notmatch 'lan[\u00E7]able') { continue }
        $celluleEtat = $cells[$cells.Count - 1]
        if ($celluleEtat -match 'livr|ferm|merg') {
            Write-VeilLog ("fiche lanable ECARTEE : marqueur de cloture dans la cellule d'etat ('{0}') - ligne ignoree du tableau lanes" -f $celluleEtat) 'WARN'
            continue
        }
        # Plusieurs liens possibles par ligne (decision, fiche...) : prendre le lien FICHE en priorite.
        $cibles = @([regex]::Matches($l, '\]\(([^)]+)\)') |
                    ForEach-Object { [uri]::UnescapeDataString($_.Groups[1].Value) })
        $fiches = @($cibles | Where-Object { [System.IO.Path]::GetFileName($_) -like 'FICHE-*' })
        if ($fiches.Count -gt 0)      { $cible = $fiches[0] }
        elseif ($cibles.Count -gt 0)  { $cible = $cibles[0] }
        else                          { continue }
        if (-not [System.IO.Path]::IsPathRooted($cible)) { $cible = Join-Path $MetaDir $cible }
        $resolve = Resolve-Path -LiteralPath $cible -ErrorAction SilentlyContinue
        if (-not $resolve) {
            Write-VeilLog "fiche lanable introuvable sur disque : $cible - ignoree" 'WARN'
            continue
        }
        $leaf = [System.IO.Path]::GetFileNameWithoutExtension($resolve.Path)
        $nom = ($leaf -replace '^FICHE-', '' -replace '-\d{4}-\d{2}-\d{2}$', '').ToLower()
        $nom = ($nom -replace '[^a-z0-9]+', '-').Trim('-')
        if ($nom -notmatch '^[a-z0-9][a-z0-9-]*$') {
            Write-VeilLog "nom de lane invalide deriverait de '$leaf' - fiche ignoree : $($resolve.Path)" 'WARN'
            continue
        }
        $resultats += [pscustomobject]@{ Nom = $nom; Fiche = $resolve.Path }
    }
    return $resultats
}

function Invoke-Tour {
    try {
        Invoke-TourCorps
    } finally {
        # I-275 livrable 6 : la ligne « tour termine » est atteinte QUEL QUE SOIT le sort
        # du corps du tour (finally). Add-Digest est elle-meme tolerante aux verrous.
        if (-not $DryRun) {
            $budget = if ($SessionsIllimitees) { "{0}/illimite" -f $state.sessionsJour } else { "{0}/{1}" -f $state.sessionsJour, $MAX_SESSIONS_JOUR }
            Add-Digest ("tour termine - budget {0}" -f $budget)
        }
    }
}

function Invoke-TourCorps {
    Update-Jour
    # Le drapeau se lit UNE FOIS au debut du tour : sinon la section rapports le retourne
    # avant que la section lanes ne le lise, et la baseline ne protege plus.
    $premiereFois = (-not $state.baselineFait)

    # ---- 1. Nouveaux rapports (definition declaree : LastWriteTimeUtc different de celui consigne)
    $rapports = @(Get-ChildItem -LiteralPath $PostRoot -Filter 'rapport-*.md' -File |
                  Sort-Object LastWriteTimeUtc)
    $nouveaux = @()
    foreach ($r in $rapports) {
        $cle = $r.Name
        $val = $r.LastWriteTimeUtc.ToString('o')
        $connu = $state.rapports.PSObject.Properties[$cle]
        if (-not $connu -or $connu.Value -ne $val) { $nouveaux += $r }
    }

    if ($premiereFois) {
        # Premier tour reel : l'etat existant est enregistre comme baseline - AUCUN reveil retroactif.
        foreach ($r in $rapports) { $state.rapports | Add-Member -NotePropertyName $r.Name -NotePropertyValue $r.LastWriteTimeUtc.ToString('o') -Force }
        $state.baselineFait = $true
        Save-State
        Write-VeilLog ("baseline etablie : {0} rapports existants consignes, aucun reveil retroactif" -f $rapports.Count)
    } else {
        foreach ($r in $nouveaux) {
            $ok = Invoke-WakeMeta -Motif 'nouveau rapport' -Rapport $r.FullName
            if ($ok -and -not $DryRun) {
                $state.rapports | Add-Member -NotePropertyName $r.Name -NotePropertyValue $r.LastWriteTimeUtc.ToString('o') -Force
                Save-State
            }
            if (-not $ok) { break }
        }
        if ($nouveaux.Count -eq 0) { Write-VeilLog ("tour : rien a signaler ({0} rapports surveilles)" -f $rapports.Count) }
    }

    # ---- 2. Fiches lanables : DECLENCHEMENT PAR DISPONIBILITE (v1.1)
    # Le CHANGEMENT de l'ensemble des fiches ne sert plus de declencheur : chaque fiche
    # lanable non lancee est examinee INDEPENDAMMENT a chaque tour - slot libre (< 3
    # actives) ET budget > 0 => lancement ; sinon elle reste en file et repart au tour
    # suivant, sans aucune retouche de l'empreinte (defaut du cycle 13:02 du 2026-08-23 :
    # un changement consomme SANS lancer figeait l'empreinte, fiches jamais lancees).
    if (Test-Path -LiteralPath (Join-Path $RepoMoteur '.git')) {
        $lancables = @(Get-Lancables)
        $empreinte = ($lancables | ForEach-Object { $_.Fiche } | Sort-Object) -join '|'
        if ($premiereFois) {
            if (-not $DryRun) { $state.lanesEmpreinte = $empreinte; Save-State }
            Write-VeilLog ("baseline lanes : empreinte consignee ({0} fiches lanables observees)" -f $lancables.Count)
        } else {
            if ($empreinte -ne $state.lanesEmpreinte) {
                # L'empreinte ne sert plus qu'au JOURNAL (digest de l'ensemble observe).
                Write-VeilLog ("ensemble des fiches lanables change ({0} fiches observees) - journal seulement, pas une condition de declenchement" -f $lancables.Count)
                if (-not $DryRun) { $state.lanesEmpreinte = $empreinte; Save-State }
            }
            $dispo = Get-LanesActives
            if (-not $dispo.Disponible) {
                # Indisponibilite GLOBALE (depot illisible) : rien de specifique a une fiche,
                # la file entiere est suspendue ce tour.
                Write-VeilLog "file lanes suspendue ce tour : depot moteur illisible" 'WARN'
            } else {
                foreach ($c in $lancables) {
                    if (@($state.fichesBannies) -contains $c.Fiche) {
                        Write-VeilLog ("fiche bannie (echecs consecutifs), ignoree jusqu'a intervention : {0}" -f $c.Fiche) 'WARN'
                        continue
                    }
                    if (@($state.lanesLancees) -contains $c.Fiche) {
                        # I-275 livrable 1 : la memoire du deja-lance rend le refus VISIBLE
                        # (avant : continue silencieux, l'incident n'a pu etre compris qu'en
                        # reconstruisant l'historique).
                        Write-VeilLog ("fiche deja lancee, ignoree : {0}" -f $c.Fiche) 'WARN'
                        continue
                    }
                    $ok = Invoke-LaunchLane -Nom $c.Nom -Fiche $c.Fiche
                    # I-275 livrable 9 : PAS de break. Un echec est SPECIFIQUE a une fiche ;
                    # la file CONTINUE (l'echec de 'veille-srd-relance' de 15:40-15:41 empechait
                    # 'catalogue-relance' de partir a deux tours successifs). La fiche en echec
                    # est retee au tour suivant, ou bannie apres N echecs consecutifs (livrable 3).
                }
            }
        }
    }

    # ---- 3. CI rouge (gh requis ; ignore sinon - declare au README)
    if ($hasGh) {
        $runs = @(& gh run list -R $CI_REPO --limit 5 --json status,conclusion 2>$null | ConvertFrom-Json)
        if ($LASTEXITCODE -eq 0 -and $runs.Count -gt 0) {
            $derniere = $runs[0]
            $etat = if ($derniere.status -eq 'completed') { $derniere.conclusion } else { 'en-cours' }
            if ($etat -eq 'failure' -and $state.ciEtat -ne 'echec-signale') {
                if (-not $DryRun) {
                    if ($premiereFois) {
                        $state.ciEtat = 'echec-signale'; Save-State
                        Write-VeilLog "baseline CI : echec deja present au premier tour, consigne sans reveil"
                    } else {
                        $null = Invoke-WakeMeta -Motif 'CI rouge - triage requis (D-189 etage 3)' -Rapport '(voir gh run list)'
                        $state.ciEtat = 'echec-signale'; Save-State
                    }
                } else {
                    Write-VeilLog "[DRYRUN] detecterait un echec CI - reveil meta affiche seulement" 'DRYRUN'
                }
            } elseif ($etat -in @('success','skipped','neutral')) {
                if ($state.ciEtat -ne '') { Write-VeilLog "CI revenue verte - garde CI rearmee" }
                if (-not $DryRun) { if ($state.ciEtat -ne '') { $state.ciEtat = ''; Save-State } }
            }
        }
    }
}

# ---- Boucle principale
# I-275 livrable 6 : une erreur dans un tour est JOURNALISEE [ERROR] et le processus
# SURVIT au tour suivant — un tour ne tue plus jamais la boucle (morts silencieuses du
# 13:56/15:15/15:32/15:40 du 2026-08-23).
try {
    do {
        try {
            Invoke-Tour
        } catch {
            $msgTour = $_.Exception.Message
            Write-Host ("[ERROR] tour interrompu mais processus conserve : {0}" -f $msgTour) -ForegroundColor Red
            Write-Tolerant ({ Add-Content -LiteralPath $LogPath -Value ("{0} [ERROR] tour interrompu mais processus conserve : {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msgTour) -Encoding UTF8 }) "journal (ERROR de tour)"
        }
        if ($Once) { break }
        Start-Sleep -Seconds $IntervalleSecondes
    } while ($true)
} finally {
    if (Test-Path -LiteralPath $PidLockPath) { Remove-Item -LiteralPath $PidLockPath -ErrorAction SilentlyContinue }
    try { $null = $mutex.ReleaseMutex() } catch { }
    $mutex.Dispose()
}
