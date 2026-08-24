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
    [switch]$SessionsIllimitees,
    # I-277 : procedure OFFICIELLE de deban - chemin d'une fiche a sortir de 'fichesBannies'
    # (compteur d'echecs et marque du deja-lance retires). Remplace l'edition manuelle du
    # state, qui a efface des bans de tiers par lost update le 2026-08-23.
    [string]$Deban
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
# I-277 : verrou d'ecriture du STATE, partage par toute voie qui touche veilleur-state.json
# (boucle du veilleur ET outil officiel -Deban). Voir Enter-StateLock.
$STATE_MUTEX        = 'Global\MRPG-Veilleur-State'

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
# Fiche fenetres visibles / TUI permanent (D-191 v1 amendee) : drapeau pose par le TUI meta
# permanent (tache-meta-permanente.ps1) autour de sa fenetre opencode interactive.
$MetaVivantPath = Join-Path $PostRoot 'META-VIVANT.flag'
$EveilTemplate = Join-Path $PostRoot 'eveil-meta.md'
if (-not $RepoMoteur) { $RepoMoteur = Join-Path $env:USERPROFILE 'coderain' }

function Write-VeilLog {
    param([string]$Message, [string]$Niveau = 'INFO')
    $ligne = "{0} [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Niveau, $Message
    Write-Host $ligne
    if (-not $DryRun) { Write-Tolerant ({ Add-Content -LiteralPath $LogPath -Value $ligne -Encoding UTF8 }) "journal ($Niveau)" }
}

# ---- I-277 : VERROU D'ECRITURE DU STATE.
# Le 2026-08-23 (~17:43/~17:50), une lane a reecrit le fichier ENTIER depuis une lecture
# perimee en appliquant la procedure de deban documentee : les bans poses entre-temps par
# le veilleur ont disparu (lost update), y compris ceux de TIERS - I-277 addendum 5 :
# une garde dont la procedure de contournement est documentee n'est pas une garde.
# Desormais toute ecriture (et toute lecture des listes de garde) passe par ce mutex nomme ;
# l'edition manuelle du JSON est remplacee par l'outil officiel -Deban, qui relit le state
# FRAIS sous verrou (plus jamais d'ecriture depuis une base perimee). Un .bak du state est
# garde a chaque ecriture pour recuperer un clobber externe eventuel.
function Enter-StateLock {
    param([int]$DelaiMs = 5000)
    $m = New-Object System.Threading.Mutex($false, $STATE_MUTEX)
    $tenu = $false
    try { $tenu = $m.WaitOne($DelaiMs) }
    catch [System.Threading.AbandonedMutexException] {
        # detenteur mort sans relacher : le runtime nous remet le mutex (meme ecole que le
        # mutex principal) - on le tient.
        $tenu = $true
    }
    if (-not $tenu) { $m.Dispose(); return $null }
    return $m
}
function Exit-StateLock {
    param($Mutex)
    if ($null -eq $Mutex) { return }
    try { $null = $Mutex.ReleaseMutex() } catch { }
    $Mutex.Dispose()
}
function Backup-State {
    # Copie .bak avant chaque ecriture - non fatale en cas d'echec.
    try {
        if (Test-Path -LiteralPath $StatePath) {
            Copy-Item -LiteralPath $StatePath -Destination ($StatePath + '.bak') -Force
        }
    } catch { Write-VeilLog ("backup du state impossible (non fatal) : {0}" -f $_.Exception.Message) 'WARN' }
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

# ---- -Deban : procedure OFFICIELLE de sortie de file (remplace l'edition manuelle).
# Relit le state FRAIS sous verrou, retire la fiche de fichesBannies, son compteur
# d'echecs et sa marque du deja-lance, puis reecrit. Jamais depuis une copie perimee.
if ($Deban) {
    $resolveDeban = Resolve-Path -LiteralPath $Deban -ErrorAction SilentlyContinue
    if (-not $resolveDeban) { Fail "fiche introuvable pour deban : $Deban" }
    $cibleDeban = $resolveDeban.Path
    $mutexDeban = Enter-StateLock -DelaiMs 5000
    if ($null -eq $mutexDeban) { Fail "verrou d'etat non acquis en 5 s - une ecriture est en cours, retenter" }
    try {
        $brut = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8
        if (-not $brut) { Fail "state illisible ou vide : $StatePath" }
        $etat = $brut | ConvertFrom-Json
        if (-not $etat.PSObject.Properties['fichesBannies'])  { $etat | Add-Member -NotePropertyName 'fichesBannies'  -NotePropertyValue @() -Force }
        if (-not $etat.PSObject.Properties['echecsParFiche']) { $etat | Add-Member -NotePropertyName 'echecsParFiche' -NotePropertyValue ([pscustomobject]@{}) -Force }
        if (-not $etat.PSObject.Properties['lanesLancees'])   { $etat | Add-Member -NotePropertyName 'lanesLancees'   -NotePropertyValue @() -Force }
        $avantBans = @($etat.fichesBannies).Count
        $etat.fichesBannies = @($etat.fichesBannies | Where-Object { $_ -ne $cibleDeban })
        if ($etat.echecsParFiche.PSObject.Properties[$cibleDeban]) {
            $etat.echecsParFiche.PSObject.Properties.Remove($cibleDeban)
        }
        $etat.lanesLancees = @($etat.lanesLancees | Where-Object { $_ -ne $cibleDeban })
        Backup-State
        Write-Tolerant ({ $etat | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $StatePath -Encoding UTF8 }) 'state (deban)'
    } finally {
        Exit-StateLock $mutexDeban
    }
    Write-Host "[veilleur] deban OFFICIEL effectue : $cibleDeban" -ForegroundColor Green
    Write-Host ("[veilleur] fichesBannies : {0} -> {1} entree(s) ; compteur d'echecs et marque du deja-lance retires." -f $avantBans, @($etat.fichesBannies).Count) -ForegroundColor Green
    Write-Host "[veilleur] pris en compte au prochain tour du veilleur. Ne jamais editer veilleur-state.json a la main." -ForegroundColor Green
    exit 0
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
# I-278 : recus provisoires - rapports deja livres dont la stabilite du mtime n'est pas
# encore confirmee (voir section 1 du tour). Tolerant un state anterieur qui ne le porte pas.
if (-not $state.PSObject.Properties['rapportsAttente']) { $state | Add-Member -NotePropertyName 'rapportsAttente' -NotePropertyValue ([pscustomobject]@{}) -Force }
# I-282 : un state FRAIS (reconstruction apres corruption + .bak perdu, poste neuf, bac a
# sable) sans baselineFait/lanesEmpreinte faisait crasher CHAQUE tour - affectation par
# point sur une propriete absente d'un PSCustomObject (« La propriete ... est introuvable »),
# la baseline ne se posait jamais et l'erreur se repetait au tour suivant. Meme ecole et
# meme emplacement que les champs I-275/I-278 ci-dessus : poses DES LA lecture s'ils manquent,
# pour que les affectations ulterieures (baseline, empreinte) trouvent toujours la propriete.
if (-not $state.PSObject.Properties['baselineFait'])  { $state | Add-Member -NotePropertyName 'baselineFait'  -NotePropertyValue $false -Force }
if (-not $state.PSObject.Properties['lanesEmpreinte']) { $state | Add-Member -NotePropertyName 'lanesEmpreinte' -NotePropertyValue '' -Force }

function Save-State {
    # I-275 livrable 3 : une fiche que l'appelant VIENT DE RETIRER (echec constate de
    # nouvelle-lane) ne doit pas etre ressuscitee par la fusion ci-dessous — le disque
    # porte encore la marque posee AVANT lancement. D'ou le parametre -Exclure.
    param([string[]]$Exclure = @())
    if ($DryRun) { return }
    $mutexState = Enter-StateLock -DelaiMs 5000
    if ($null -eq $mutexState) {
        Write-VeilLog "verrou d'etat non acquis en 5 s - ecriture sans verrou (comportement ancien)" 'WARN'
    }
    try {
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
        Backup-State
        Write-Tolerant ({ $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $StatePath -Encoding UTF8 }) 'state'
    } finally {
        Exit-StateLock $mutexState
    }
}

function Update-Jour {
    $today = Get-Date -Format 'yyyy-MM-dd'
    if ($state.jour -ne $today) {
        $state.jour = $today
        $state.sessionsJour = 0
        Write-VeilLog ("nouveau jour {0} - compteur quotidien remis a zero" -f $today)
    }
}

function Sync-GardesDepuisDisque {
    # I-277 (suite) : fichesBannies/echecsParFiche sont relus DU DISQUE au DEBUT de chaque
    # tour, sous verrou (le disque fait foi pour les listes de garde).
    # I-280 : le disque fait foi AUSSI pour lanesLancees. Mesure en reel le 2026-08-23
    # (20:04/20:09) : un -Deban pendant que l'instance vivante tourne corrigeait le disque
    # mais pas sa RAM ; pire, son prochain Save-State RESSUSCITAIT la marque retiree (la
    # fusion anti-ecrasement ne fait qu'ajouter, elle ne sait pas retirer) et la decision
    # « fiche deja lancee » restait prise sur une memoire perimee - la relance exigeait
    # l'arret de l'instance (sequence stop -> deban -> start). Desormais lanesLancees est
    # REMPLACEE par sa valeur disque SOUS VERROU a chaque tour, AVANT toute decision de
    # lancement : ce que -Deban retire du disque sort de la RAM au tour suivant, sans
    # redemarrage. Sans risque pour les marques en vol mid-tour : Invoke-LaunchLane ecrit
    # sa marque au disque immediatement (Save-State AVANT lancement), donc entre deux tours
    # le disque n'est jamais en retard sur la RAM.
    if ($DryRun) { return }
    $mutexSync = Enter-StateLock -DelaiMs 2000
    if ($null -eq $mutexSync) { return }   # ne jamais bloquer un tour pour ca ; reessaie au suivant
    try {
        $brut = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8
        if ($brut) {
            $disque = $brut | ConvertFrom-Json
            if ($disque.jour -eq $state.jour) {
                # I-280 : marques du deja-lance = valeur disque INTEGRALE (pas une fusion :
                # la fusion ne sait qu'ajouter et ressusciterait exactement ce que -Deban
                # vient de retirer).
                if ($disque.PSObject.Properties['lanesLancees'] -and $null -ne $disque.lanesLancees) {
                    $state.lanesLancees = @($disque.lanesLancees)
                } else {
                    $state.lanesLancees = @()
                }
                $state.fichesBannies = @($disque.fichesBannies)
                if (-not $disque.PSObject.Properties['echecsParFiche'] -or $null -eq $disque.echecsParFiche) {
                    $state.echecsParFiche = [pscustomobject]@{}
                } else {
                    $state.echecsParFiche = $disque.echecsParFiche
                }
            }
        }
    } catch { Write-VeilLog ("sync gardes depuis disque impossible (non fatal) : {0}" -f $_.Exception.Message) 'WARN' }
    finally { Exit-StateLock $mutexSync }
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

function Test-MetaVivant {
    # Fiche fenetres visibles / TUI permanent : drapeau pose par le wrapper du TUI meta
    # (tache-meta-permanente.ps1) tant que la fenetre opencode interactive de Souhel vit.
    # CONSERVATEUR, meme ecole que Test-LockMeta : tout drapeau PRESENT signale un TUI vivant,
    # quel que soit son contenu ; un format inconnu est RESPECTE. Seule exception : un drapeau
    # au format du wrapper ("<PID> <horodatage ISO>") dont le PID est MORT est repute obsolete
    # (fermeture brutale de la fenetre, crash : le finally du wrapper n'a pas pu tomber le
    # drapeau) - il est ignore pour ne pas condamner les reveils a jamais. Le drapeau n'est
    # PAS supprime ici : le veilleur n'efface pas l'etat d'un autre composant ; le prochain
    # demarrage du TUI l'ecrase de lui-meme.
    if (-not (Test-Path -LiteralPath $MetaVivantPath)) { return $false }
    $contenu = (Get-Content -LiteralPath $MetaVivantPath -Raw -ErrorAction SilentlyContinue)
    if ($contenu -match '^\s*(\d+)\s') {
        $pidTui = [int]$Matches[1]
        if ($pidTui -ne $PID -and (-not (Get-Process -Id $pidTui -ErrorAction SilentlyContinue))) {
            Write-VeilLog ("drapeau META-VIVANT obsolete (pid {0} mort) - ignore" -f $pidTui) 'GARDE'
            return $false
        }
    } else {
        Write-VeilLog "drapeau META-VIVANT au format inconnu - RESPECTE par precaution : aucune session fantome" 'WARN'
    }
    return $true
}

function Invoke-EvenementMeta {
    # Routage unique des evenements meta (nouveau rapport, CI rouge), fiche fenetres visibles :
    #   - drapeau META-VIVANT present => AUCUNE session fantome. L'evenement va au digest avec
    #     la mention « a traiter dans ta fenetre meta » : Souhel regarde sa fenetre permanente
    #     et y demande la lecture en direct. Aucun budget consomme, aucun verrou touche.
    #   - drapeau absent => reveil classique d'une session meta VISIBLE (fenetre normale).
    param([string]$Motif, [string]$Rapport)
    if (Test-MetaVivant) {
        Write-VeilLog "TUI meta vivant (drapeau present) - aucune session fantome : evenement consigne au digest" 'INFO'
        Add-Digest ("reveil META ({0}) - {1} - A TRAITER DANS TA FENETRE META (TUI vivant, aucune session fantome lancee)" -f $Motif, $Rapport)
        return $true
    }
    return (Invoke-WakeMeta -Motif $Motif -Rapport $Rapport)
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
        Write-Host "[veilleur][DRYRUN] lancerais une session meta VISIBLE (motif : $Motif) avec le prompt :" -ForegroundColor Magenta
        Write-Host "--- debut prompt ---"
        Write-Host $prompt
        Write-Host "--- fin prompt ---"
        Write-Host "[veilleur][DRYRUN] commande equivalente : prompt instancie dans un fichier VISIBLE du poste, puis 'opencode run' depuis $MetaDir avec le contenu du fichier en message (fenetre normale non cachee, verrou $LockPath)" -ForegroundColor Magenta
        return $true
    }
    # Le prompt voyage par FICHIER, jamais par la ligne de commande : le premier
    # positionnel d'opencode est un CHEMIN DE PROJET ('opencode [project]') - coller
    # le prompt en argument faisait echouer le changement de repertoire (bug du
    # 2026-08-23). L'appel passe par -EncodedCommand (base64) : insensible aux
    # espaces et guillemets que Start-Process sinon deformait.
    # Fiche fenetres visibles : l'instance du prompt est ecrite dans le POSTE (visible,
    # a cote des preuves de session), et plus dans %TEMP% ou personne ne la voit.
    $horodatage = Get-Date -Format 'yyyyMMdd-HHmmss'
    $promptFile = Join-Path $PostRoot ("eveil-meta-{0}.md" -f $horodatage)
    $proofLog   = Join-Path $PostRoot ("preuve-session-meta-{0}.log" -f $horodatage)
    Set-Content -LiteralPath $promptFile -Value $prompt -Encoding UTF8
    Write-Tolerant ({ Set-Content -LiteralPath $LockPath -Value ("{0} {1}" -f $PID, (Get-Date -Format o)) -Encoding ASCII }) 'verrou meta'
    # Fenetre VISIBLE (fenetre normale, jamais cachee) et titree : Souhel voit la session
    # travailler et peut la fermer sans dommage - tout vit sur disque.
    $inner = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; chcp 65001 | Out-Null; " +
             "`$host.UI.RawUI.WindowTitle = 'META - reveil du veilleur'; " +
             "Set-Location -LiteralPath '$MetaDir'; " +
             "`$p = Get-Content -LiteralPath '$promptFile' -Raw -Encoding UTF8; " +
             "opencode.cmd run `$p 2>&1 | Tee-Object -FilePath '$proofLog' -Append; " +
             "Remove-Item -LiteralPath '$promptFile' -ErrorAction SilentlyContinue; " +
             "Remove-Item -LiteralPath '$LockPath' -ErrorAction SilentlyContinue"
    $b64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Normal', '-EncodedCommand', $b64)
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
    # I-277 (diagnostic lane Q) : le -RepoMoteur doit etre PROPAGE - sans lui, nouvelle-lane
    # retombe sur son defaut (~\coderain) et peut viser un AUTRE depot que celui surveille
    # (constate en bac a sable le 2026-08-23 : worktree cree dans le depot reel).
    & (Join-Path $PostRoot 'nouvelle-lane.ps1') -Nom $Nom -Fiche $Fiche -RepoRoot $RepoMoteur
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
            Write-VeilLog ("lane '{0}' : {1} echecs consecutifs - FICHE SORTIE DE FILE jusqu'a intervention (deban officiel : powershell -File veilleur.ps1 -Deban <chemin-de-fiche> ; ne JAMAIS editer veilleur-state.json a la main : lost update, I-277)" -f $Nom, $MAX_ECHECS_CONSECUTIFS) 'WARN'
            Add-Digest ("[WARN] lane '{0}' bannie apres {1} echecs consecutifs - sortie de file jusqu'a intervention (deban officiel : veilleur.ps1 -Deban)" -f $Nom, $MAX_ECHECS_CONSECUTIFS)
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
        # Defaut 4a (signalement lane P, cas reel 15:57) : l'ancien motif 'livr|ferm|merg'
        # matchait des SOUS-CHAINES ('15 livrables' ecartait une fiche lanable). Desormais :
        # marqueurs de cloture EXACTS (livre/livree/livrees..., ferme(e)(s), merge(e)(s),
        # accents inclus), bornes de mot des deux cotes - 'livrables', 'fermeture',
        # 'en-cours-de-relecture' ne matchent plus ; 'livre', 'FERMEE', 'merge' oui.
        if ($celluleEtat -match '(?i)\b(livr[\u00E9]e?s?|ferm[\u00E9]e?s?|merg[\u00E9]e?s?)\b') {
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
    Sync-GardesDepuisDisque
    # Le drapeau se lit UNE FOIS au debut du tour : sinon la section rapports le retourne
    # avant que la section lanes ne le lise, et la baseline ne protege plus.
    $premiereFois = (-not $state.baselineFait)

    # ---- 1. Nouveaux rapports (definition declaree : LastWriteTimeUtc different de celui consigne)
    # I-278 (double reveil differe) - chaque rapport surveille a TROIS etats :
    #   inconnu          => evenement neuf, candidat au reveil ($nouveaux) ;
    #   recu PROVISOIRE  => evenement DEJA livre une fois ($state.rapportsAttente) ; tant que
    #                       son mtime bouge entre deux tours, c'est le MEME depot relu (le
    #                       depositant finissait d'ecrire) : recu mis a jour, AUCUNE seconde
    #                       session ; des qu'il tient un tour complet, recu finalise dans
    #                       $state.rapports ;
    #   recu FINAL       => $state.rapports, rien a signaler.
    # Avant I-278, l'accuse de reception etait snapshotte AU MOMENT DU REVEIL : toute ecriture
    # du depositant posterieure au tour rejouait l'evenement a chacun des tours suivants (cas
    # reel 18:17 -> 18:33 du 2026-08-23 : rapport deja instruit par H-075, reveille une seconde
    # fois des que le verrou meta est tombe - une session et une unite de budget perdues).
    # Le recu differe ferme cette course SANS rien perdre d'un evenement vraiment nouveau
    # (ecole I-276) : un refus de reveil (verrou meta, budget) ne consigne TOUJOURS rien,
    # donc l'evenement non livre repart au tour suivant, inchange.
    $rapports = @(Get-ChildItem -LiteralPath $PostRoot -Filter 'rapport-*.md' -File |
                  Sort-Object LastWriteTimeUtc)
    $nouveaux = @()
    foreach ($r in $rapports) {
        $cle = $r.Name
        $val = $r.LastWriteTimeUtc.ToString('o')
        $connu = $state.rapports.PSObject.Properties[$cle]
        if ($connu -and $connu.Value -eq $val) { continue }
        $attente = $state.rapportsAttente.PSObject.Properties[$cle]
        if (-not $attente) { $nouveaux += $r ; continue }
        if ($attente.Value -ne $val) {
            # meme depot relu pendant la fenetre d'attente : recu provisoire mis a jour,
            # JAMAIS de second reveil (c'est exactement ce rejouement que I-278 supprime).
            $state.rapportsAttente.PSObject.Properties[$cle].Value = $val
            if (-not $DryRun) { Save-State }
            Write-VeilLog ("[I-278] '{0}' relu pendant la fenetre d'attente (deja reveille) - recu mis a jour SANS nouvelle session" -f $cle)
        } else {
            # mtime identique d'un tour au suivant : le depositant a fini d'ecrire - recu finalise.
            $state.rapportsAttente.PSObject.Properties.Remove($cle)
            $state.rapports | Add-Member -NotePropertyName $cle -NotePropertyValue $val -Force
            if (-not $DryRun) { Save-State }
            Write-VeilLog ("[I-278] recu stabilise pour '{0}' (mtime stable un tour complet) - clos sans session" -f $cle)
        }
    }
    # entretien : recus provisoires dont le fichier a disparu (rapport supprime apres livraison)
    foreach ($p in @($state.rapportsAttente.PSObject.Properties)) {
        if (-not (Test-Path -LiteralPath (Join-Path $PostRoot $p.Name))) {
            $state.rapportsAttente.PSObject.Properties.Remove($p.Name)
            if (-not $DryRun) { Save-State }
            Write-VeilLog ("[I-278] recu provisoire abandonne (rapport disparu) : {0}" -f $p.Name)
        }
    }

    if ($premiereFois) {
        # Premier tour reel : l'etat existant est enregistre comme baseline - AUCUN reveil retroactif.
        foreach ($r in $rapports) { $state.rapports | Add-Member -NotePropertyName $r.Name -NotePropertyValue $r.LastWriteTimeUtc.ToString('o') -Force }
        $state.rapportsAttente = [pscustomobject]@{}
        $state.baselineFait = $true
        Save-State
        Write-VeilLog ("baseline etablie : {0} rapports existants consignes, aucun reveil retroactif" -f $rapports.Count)
    } else {
        foreach ($r in $nouveaux) {
            # Fiche fenetres visibles : routage unique (TUI vivant => digest sans session
            # fantome ; TUI ferme => reveil d'une session meta visible). $issue est vrai
            # pour les DEUX issues positives : dans les deux cas l'evenement est consomme.
            $issue = Invoke-EvenementMeta -Motif 'nouveau rapport' -Rapport $r.FullName
            if ($issue -and -not $DryRun) {
                # I-278 : recu PROVISOIRE (et non plus direct dans $state.rapports) - voir
                # l'entete de cette section. Un refus ci-dessus ne consigne toujours rien.
                $state.rapportsAttente | Add-Member -NotePropertyName $r.Name -NotePropertyValue $r.LastWriteTimeUtc.ToString('o') -Force
                Save-State
            }
            if (-not $issue) { break }
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
                        # Fiche fenetres visibles : meme routage que les rapports (le TUI
                        # vivant capte l'evenement vers le digest, sans session fantome).
                        $null = Invoke-EvenementMeta -Motif 'CI rouge - triage requis (D-189 etage 3)' -Rapport '(voir gh run list)'
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
