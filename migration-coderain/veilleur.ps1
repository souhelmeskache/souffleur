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
    [string]$Deban,
    # CANAL DE DEPLOIEMENT FIDELE (fiche canal-deploiement-fidele du 24/08) : deploie les
    # copies DEPOT des DEUX scripts attestes vers le poste (.bak date AVANT ecrasement, hash
    # avant/apres journalises), puis SORT volontairement (code 0) APRES journalisation - le
    # gardien MRPG-Veilleur-Gardien relance l'instance sur le nouveau code en <= 5 min
    # (I-284 : l'instance ne se redemarre JAMAIS elle-meme).
    [switch]$Deployer
)

$ErrorActionPreference = 'Stop'

# ---- Constantes des gardes (D-191 palier v1)
$MAX_SESSIONS_JOUR  = 6
$MAX_LANES_ACTIVES  = 3
$LOCK_STALE_HEURES  = 6
# I-275 livrable 3 : borne anti-boucle — apres N echecs consecutifs d'une meme fiche,
# elle sort de la file jusqu'a intervention.
$MAX_ECHECS_CONSECUTIFS = 2
# FICHE reveils-surveilles (I-276/I-305) : seuil de MORT d'un reveil trace - une entree de
# reveilsLances agee de plus de 30 minutes sans aucune suite visible est declaree morte
# probable ([WARN] UNE fois, pour re-examen humain ; jamais de re-feu automatique).
$REVEIL_MORT_MINUTES = 30
# ... et TOLERANCE separant la LIGNE DE LANCEMENT d'une vraie suite : le digest recoit
# « reveil META (...) » quelques secondes APRES la trace I-291 (meme fonction) - sans cette
# fenetre, chaque entree se prouverait sa propre activite et aucun mort ne serait jamais vu.
$REVEIL_TRACE_TOLERANCESEC = 120
# D-203 (production pilotee par le besoin) : le declencheur du reveil PRODUCTEUR devient un
# declencheur d'ETAT evalue a chaque tour (section 2bis) : file sans rien de lanzable + travail
# restant a router + slot libre. Fin de la borne 1/jour (producteurJour), de la fenetre 9 h
# ($PRODUCTEUR_HEURE) et du seuil $PRODUCTEUR_N_TOIRS - toursSansLancable redevient un simple
# signal de famine journalise, sans valeur-seuil declenchante. Gardes INTACTES (slots, volume,
# N=2, verrous) : c'est un changement de DECLENCHEMENT, pas de gardes.
# $FAMILLES_TECHNIQUES : familles d'items de registre-items reconnues comme « piste de routage
# technique » pour la condition « travail restant » (constat du 24/08 : la totalite des items
# deja routes au poste par un champ fiche: sont de la famille boucle ; convertisseur est
# l'autre famille du projet de migration).
$FAMILLES_TECHNIQUES = @('boucle', 'convertisseur')
$CI_REPO            = 'souhelmeskache/ttrpg-mvp'
# I-277 : verrou d'ecriture du STATE, partage par toute voie qui touche veilleur-state.json
# (boucle du veilleur ET outil officiel -Deban). Voir Enter-StateLock.
$STATE_MUTEX        = 'Global\MRPG-Veilleur-State'
# CANAL DE DEPLOIEMENT FIDELE : les DEUX seuls scripts du canal. La detection de derive
# (chaque tour) et le mode -Deployer ne connaissent JAMAIS un troisieme chemin.
$SCRIPTS_FIDELES    = @('veilleur.ps1', 'nouvelle-lane.ps1')

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

function Get-Sha256Fidele {
    # Hash SHA256 tolerant : renvoie $null si le fichier manque ou est illisible - les
    # appelants (detection de derive au tour, mode -Deployer) traitent ce cas NOMMEMENT.
    param([string]$Chemin)
    try {
        if (-not (Test-Path -LiteralPath $Chemin)) { return $null }
        return (Get-FileHash -LiteralPath $Chemin -Algorithm SHA256 -ErrorAction Stop).Hash
    } catch { return $null }
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

# ---- CANAL DE DEPLOIEMENT FIDELE : mode -Deployer (fiche canal-deploiement-fidele 24/08).
# Deploie les copies DEPOT -> POSTE des deux scripts attestes, octet-fidele par nature
# (Copy-Item), avec .bak date de chaque fichier remplace AVANT ecrasement et hash avant/apres
# journalises. Refus NOMME si : depot sale (status --porcelain non vide), hash illisible, ou
# chemin hors des DEUX attestes - jamais un troisieme chemin. Termine par une SORTIE
# VOLONTAIRE (code 0) APRES journalisation : le gardien (MRPG-Veilleur-Gardien) relance
# l'instance sur le nouveau code en <= 5 min ; l'instance ne se redemarre JAMAIS elle-meme
# (I-284). Chaine complete : merge -> derive detectee au tour -> -Deployer explicite ->
# sortie -> gardien. Ce mode s'execute AVANT tout verrou d'instance : il n'ouvre pas de slot,
# il ne touche ni state ni PID lock - seulement les deux scripts, leur .bak et le journal.
if ($Deployer) {
    if (-not (Test-Path -LiteralPath (Join-Path $RepoMoteur '.git'))) { Fail "depot moteur introuvable : $RepoMoteur" }
    $statusCanal = @(& git -C $RepoMoteur status --porcelain | Where-Object { $_ -ne '' })
    if ($LASTEXITCODE -ne 0) { Fail "git status a echoue sur $RepoMoteur - depot illisible, deploiement refuse" }
    if ($statusCanal.Count -gt 0) {
        Fail ("depot SALE (git status --porcelain non vide : {0} entree(s), premiere : '{1}') - deploiement refuse : ne jamais deployer du travail non commite" -f $statusCanal.Count, ($statusCanal[0]).Trim())
    }
    # Les DEUX chemins attestes, construits ici une fois. Aucun autre chemin n'est jamais ni
    # iterate ni tolere ; l'attestation ci-dessous juge chaque couple source/destination
    # AVANT toute action (garde contre une future extension accidentelle de la file).
    $attestesDepot = @($SCRIPTS_FIDELES | ForEach-Object { Join-Path (Join-Path $RepoMoteur 'migration-coderain') $_ })
    $attestesPoste = @($SCRIPTS_FIDELES | ForEach-Object { Join-Path $PostRoot $_ })
    $horodatageCanal = Get-Date -Format 'yyyyMMdd-HHmmss'
    $deploys = @()
    foreach ($nomCanal in $SCRIPTS_FIDELES) {
        $srcCanal = Join-Path (Join-Path $RepoMoteur 'migration-coderain') $nomCanal
        $dstCanal = Join-Path $PostRoot $nomCanal
        if (($attestesDepot -notcontains $srcCanal) -or ($attestesPoste -notcontains $dstCanal)) {
            Fail "chemin hors des deux attestes - deploiement refuse, jamais un troisieme chemin : $srcCanal -> $dstCanal"
        }
        $deploys += [pscustomobject]@{ Nom = $nomCanal; Source = $srcCanal; Destination = $dstCanal }
    }
    foreach ($d in $deploys) {
        $hSource = Get-Sha256Fidele $d.Source
        if (-not $hSource) { Fail "hash illisible (source depot) : $($d.Source) - deploiement refuse" }
        $hAvant = $null
        $bakPose = ''
        if (Test-Path -LiteralPath $d.Destination) {
            $hAvant = Get-Sha256Fidele $d.Destination
            if (-not $hAvant) { Fail "hash illisible (copie poste existante) : $($d.Destination) - deploiement refuse" }
            $bakPose = "$($d.Destination).bak-$horodatageCanal"
            Copy-Item -LiteralPath $d.Destination -Destination $bakPose -Force   # .bk pose AVANT ecrasement
        }
        Copy-Item -LiteralPath $d.Source -Destination $d.Destination -Force
        $hApres = Get-Sha256Fidele $d.Destination
        if (-not $hApres) { Fail "hash illisible (copie poste apres copie) : $($d.Destination)" }
        if ($hApres -ne $hSource) { Fail "deploiement NON octet-fidele pour $($d.Nom) (sha256 poste apres=$hApres, depot=$hSource) - verifier le disque" }
        Write-VeilLog ("-Deployer '{0}' : copie octet-fidele depot->poste verifiee ; sha256 depot={1} poste avant={2} poste apres={3}{4}" -f `
            $d.Nom, $hSource, $(if ($hAvant) { $hAvant } else { '(absent)' }), $hApres, `
            $(if ($bakPose) { " ; .bak pose avant ecrasement : $bakPose" } else { ' ; aucune copie anterieure, pas de .bak' })) 'INFO'
    }
    Write-Host ("[veilleur] deploiement fidele termine : {0} fichier(s) - sortie VOLONTAIRE (code 0) ; le gardien relance l'instance sur le nouveau code en <= 5 min (I-284)." -f $deploys.Count) -ForegroundColor Green
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
# D-203 : compteur de tours consecutifs sans fiche lanable observee - SIGNAL de famine
# journalise, sans valeur-seuil declenchante. La borne producteurJour (1 reveil/jour, D-197)
# disparaît : le declencheur est l'ETAT de la file (section 2bis), plus calendaire. Un state
# ancien peut encore porter producteurJour - il y reste, jamais lu, sans effet.
if (-not $state.PSObject.Properties['toursSansLancable']) { $state | Add-Member -NotePropertyName 'toursSansLancable' -NotePropertyValue 0  -Force }
# I-289 : memoire des annonces « fiche deja lancee » - l'etat n'est logge qu'AU CHANGEMENT
# (premiere observation, perte de marque, livraison) ; entre deux changements, muet.
# Tolerant un state anterieur qui ne le porte pas encore.
if (-not $state.PSObject.Properties['dejaLanceesConsignees']) { $state | Add-Member -NotePropertyName 'dejaLanceesConsignees' -NotePropertyValue @() -Force }
# I-291 : trace des reveils meta reellement lances (« horodatage|motif|mode », meme ecole
# que lanesLancees) - un reveil mort SANS historisation devient detectable au tour suivant.
if (-not $state.PSObject.Properties['reveilsLances']) { $state | Add-Member -NotePropertyName 'reveilsLances' -NotePropertyValue @() -Force }
# CANAL DE DEPLOIEMENT FIDELE : memoire des derives DEJA consignees ([WARN] emis UNE seule
# fois jusqu'a correction, ecole I-289) - liste de noms de fichiers. Tolerant un state
# anterieur qui ne le porte pas encore.
if (-not $state.PSObject.Properties['derivesConsignees']) { $state | Add-Member -NotePropertyName 'derivesConsignees' -NotePropertyValue @() -Force }
# D-204 : memoire des fiches dont l'ecart « bloquee » a DEJA ete consigne ([INFO] emis UNE
# seule fois au changement, meme ecole que dejaLanceesConsignees/I-289). Jetee silencieusement
# au deblocage (retrait du mot de la cellule) ou quand la ligne quitte le tableau. Tolerant un
# state anterieur qui ne le porte pas encore.
if (-not $state.PSObject.Properties['bloqueesConsignees']) { $state | Add-Member -NotePropertyName 'bloqueesConsignees' -NotePropertyValue @() -Force }
# FICHE reveils-surveilles (I-276/I-305) : memoire des entrees de reveilsLances dont le
# [WARN] « reveil mort probable » a DEJA ete consigne ([WARN] emis UNE seule fois par
# entree, ecole I-289). Jetee silencieusement si l'entree quitte reveilsLances (entretien
# en section 1bis, meme ecole que bloqueesConsignees) : un state reconstruit re-arme la
# detection, une entree toujours presente n'est jamais re-consignee.
if (-not $state.PSObject.Properties['reveilsMortsConsignees']) { $state | Add-Member -NotePropertyName 'reveilsMortsConsignees' -NotePropertyValue @() -Force }

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
                # I-291 : la trace des reveils lances ne retrograde jamais non plus (meme ecole
                # que lanesLancees ci-dessus) - une instance demarree avant un reveil d'une autre
                # voie ne doit pas l'effacer en reecrivant.
                foreach ($r in @($auDisque.reveilsLances)) {
                    if ($r -and (@($state.reveilsLances) -notcontains $r)) { $state.reveilsLances = @($state.reveilsLances) + $r }
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
    # D-197 : le mode (instruction | producteur) voyage avec l'evenement jusqu'au template.
    # I-292 : il voyage JUSQU'AU BOUT du tuyau - transmis a Invoke-WakeMeta (qui retombait
    # sur son defaut 'instruction', preuve : eveil-meta-20260824-113132.md) et consigne au
    # digest sur le chemin TUI vivant, pour que la fenetre permanente sache aussi quel fil.
    param([string]$Motif, [string]$Rapport, [string]$Mode = 'instruction')
    if (Test-MetaVivant) {
        Write-VeilLog "TUI meta vivant (drapeau present) - aucune session fantome : evenement consigne au digest" 'INFO'
        Add-Digest ("reveil META ({0}) - {1} - Mode du fil : {2} - A TRAITER DANS TA FENETRE META (TUI vivant, aucune session fantome lancee)" -f $Motif, $Rapport, $Mode)
        return $true
    }
    return (Invoke-WakeMeta -Motif $Motif -Rapport $Rapport -Mode $Mode)
}

function Invoke-WakeMeta {
    param([string]$Motif, [string]$Rapport, [string]$Mode = 'instruction')
    if (Test-LockMeta) {
        Write-VeilLog "garde verrou meta : une session meta est deja active - reveil refuse" 'GARDE'
        return $false
    }
    if ((Get-BudgetRestant) -le 0) {
        Write-VeilLog ("garde volume : plafond {0} sessions/jour atteint - reveil refuse ({1})" -f $MAX_SESSIONS_JOUR, $Motif) 'GARDE'
        return $false
    }
    # D-197 : le MODE du fil (instruction | producteur) est grave dans le prompt instancie -
    # il voyage par FICHIER comme le reste du prompt, jamais par la ligne de commande.
    $template = Get-Content -LiteralPath $EveilTemplate -Raw -Encoding UTF8
    $prompt = $template.Replace('{{MOTIF}}', $Motif).Replace('{{RAPPORT}}', $Rapport).Replace('{{MODE}}', $Mode)
    if ($DryRun) {
        Write-Host "[veilleur][DRYRUN] lancerais une session meta VISIBLE (motif : $Motif ; mode : $Mode) avec le prompt :" -ForegroundColor Magenta
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
    # I-291 : le reveil parti est TRACE dans le state IMMEDIATEMENT (meme ecole que la marque
    # du deja-lance ecrite avant lancement, I-275 livrable 1 : si le processus meurt entre
    # lancement et prochaine sauvegarde, la trace survit). Format « horodatage|motif|mode » :
    # un reveil mort SANS historisation devient detectable au tour suivant au lieu d'etre
    # invisible (plus jamais un trou noir comme eveil-meta-20260824-113132.md). Un REFUS ne
    # consigne rien (verrou/budget : les retours $false ci-dessus sortent avant cette ligne).
    $state.reveilsLances = @($state.reveilsLances) + ("{0}|{1}|{2}" -f (Get-Date -Format o), $Motif, $Mode)
    Save-State
    $state.sessionsJour = [int]$state.sessionsJour + 1
    # I-286 : l'affichage respecte le regime -SessionsIllimitees (meme format conditionnel que
    # la ligne « tour termine » d'Invoke-Tour) - plus jamais un « n/6 » menteur en mode illimite.
    $budget = if ($SessionsIllimitees) { "{0}/illimite" -f $state.sessionsJour } else { "{0}/{1}" -f $state.sessionsJour, $MAX_SESSIONS_JOUR }
    Write-VeilLog ("session meta lancee - motif : {0} - budget journalier : {1}" -f $Motif, $budget)
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

# ---- I-287 livrable 2 : marques d'ECHEC EXTERNE posees par la fenetre d'une lane morte sur
# erreur fournisseur (finish_reason: network_error). Format : fiche=<chemin>|horodatage=<iso>|
# preuve=<log>. Une marque de PLUS de 24 h est une preuve perimee : ignoree ici (jetee par
# l'entretien du tour) pour ne jamais masquer un echec qui ne doit plus rien a la panne.
# NB : retour PLAT (pas de virgule protective) - chaque appelant emballe deja dans @() ; un
# emballage double ferait iterer les boucles sur un tableau vide (FullName=null, crash I-287).
function Get-MarquesEchecExterne {
    param([string]$FicheCible)
    $trouvees = @()
    if (-not $FicheCible) { return $trouvees }
    foreach ($m in @(Get-ChildItem -LiteralPath $PostRoot -Filter 'echec-externe-*.flag' -File -ErrorAction SilentlyContinue)) {
        if (((Get-Date) - $m.LastWriteTime).TotalHours -gt 24) { continue }
        $contenu = ''
        try { $contenu = Get-Content -LiteralPath $m.FullName -Raw -Encoding UTF8 } catch { }
        if ($contenu -and $contenu.Contains($FicheCible)) { $trouvees += $m }
    }
    return $trouvees
}

function Test-DeriveScriptsFideles {
    # CANAL DE DEPLOIEMENT FIDELE (livrables 1+4) : a CHAQUE tour, SHA256 des copies POSTE
    # des deux scripts compares aux copies DEPOT ($RepoMoteur). Egal => silence total (zero
    # bruit de log, ecole I-289). Differ (ou hash illisible) => [WARN] nommant le fichier et
    # les DEUX hash, UNE seule fois jusqu'a correction (memoire derivesConsignees persistee,
    # meme ecole que dejaLanceesConsignees). Le tour NE deploie JAMAIS seul : il detecte et
    # consigne ; le deploiement reste le geste explicite 'veilleur.ps1 -Deployer' (livrable 4).
    foreach ($nom in $SCRIPTS_FIDELES) {
        $hPoste = Get-Sha256Fidele (Join-Path $PostRoot $nom)
        $hDepot = Get-Sha256Fidele (Join-Path (Join-Path $RepoMoteur 'migration-coderain') $nom)
        if ($hPoste -and $hDepot -and ($hPoste -eq $hDepot)) {
            if (@($state.derivesConsignees) -contains $nom) {
                # correction observee : retour au silence SANS log - la memoire est jetee et
                # une REderive sera reconsignee normalement (le WARN est « jusqu'a correction »).
                $state.derivesConsignees = @($state.derivesConsignees | Where-Object { $_ -ne $nom })
                Save-State
            }
            continue
        }
        if (@($state.derivesConsignees) -contains $nom) { continue }
        Write-VeilLog ("[WARN] derive detectee '{0}' : sha256 poste={1} depot={2} - corriger par 'veilleur.ps1 -Deployer' (le tour ne deploie jamais seul)" -f `
            $nom, $(if ($hPoste) { $hPoste } else { 'ILLISIBLE' }), $(if ($hDepot) { $hDepot } else { 'ILLISIBLE' })) 'WARN'
        $state.derivesConsignees = @($state.derivesConsignees) + $nom
        Save-State
    }
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
    # ---- I-298 : MEMOIRE LOCALE DU TOUR — le hash SHA256 de la fiche est capture AVANT le
    # lancement. Le vault est cloud-backed (ARCH-F-021) : une fiche corrigee peut n'arriver
    # SUR DISQUE qu'apres coup, et le controle d'armement juge alors la version MORTE (cas
    # reel du 24/08 a 15:43 : FICHE-relance-mcp corrigee ~15:41, relance de 15:43:22 exit 1
    # sur controle 1b, echec no 2/2 + sortie de file enregistres sur la version perimee).
    # L'echec sera rattache a CETTE version jugee, pas au nom du fichier.
    $hashFicheAuLancement = Get-Sha256Fidele $Fiche
    # I-277 (diagnostic lane Q) : le -RepoMoteur doit etre PROPAGE - sans lui, nouvelle-lane
    # retombe sur son defaut (~\coderain) et peut viser un AUTRE depot que celui surveille
    # (constate en bac a sable le 2026-08-23 : worktree cree dans le depot reel).
    & (Join-Path $PostRoot 'nouvelle-lane.ps1') -Nom $Nom -Fiche $Fiche -RepoRoot $RepoMoteur
    if ($LASTEXITCODE -ne 0) {
        # ---- I-287 livrable 2 : ERREUR EXTERNE, PAS UNE FAUTE DE FICHE. Une marque d'echec externe
        # FRAICHE (< 24 h) portant cette fiche prouve que le run precedent est mort reseau
        # (finish_reason: network_error, fourni par la fenetre) : l'echec de relance observe
        # ici herite de cette panne exterieure. La borne N=2 ne juge que des FAUTES PROPRES :
        # compteur INTACT, pas de ban ; la marque est consommee et la fiche repart au tour
        # suivant (cas reel I-287 du 24/08 : inventaire-saves morte reseau a 08:50, relance
        # 08:56 comptee 1/2 - une seconde panne eut BANNI la fiche).
        $marquesExterne = @(Get-MarquesEchecExterne -FicheCible $Fiche)
        if ($marquesExterne.Count -gt 0) {
            foreach ($m in $marquesExterne) { Remove-Item -LiteralPath $m.FullName -ErrorAction SilentlyContinue }
            $state.lanesLancees = @($state.lanesLancees | Where-Object { $_ -ne $Fiche })
            Save-State -Exclure @($Fiche)
            Write-VeilLog ("echec externe, compteur intact - lane '{0}' (code sortie {1}) : mort reseau precedente (finish_reason: network_error) prouvee par {2} ; borne N=2 jugee sur fautes propres seulement (I-287) - retee au prochain tour" -f $Nom, $LASTEXITCODE, ($marquesExterne | ForEach-Object { $_.Name }) -join ', ') 'INFO'
            Add-Digest ("lane '{0}' : echec EXTERNE (reseau fournisseur, I-287) - compteur intact, fiche retee" -f $Nom)
            return $false
        }
        # ---- I-298 (suite) : l'echec vient-il d'etre JUGE SUR UNE VERSION PERIMEE ? La fiche
        # est RELUE et son hash recalcule : different => la version que le controle d'armement
        # vient de juger n'est plus la version courante du disque => cet echec ne dit rien
        # d'elle => NON COMPTE (compteur intact, pas de ban), marque retiree comme pour un
        # echec externe (I-287), fiche retee au tour suivant sur sa version courante.
        # Hash illisible (fiche disparue/illisible) ou identique => comportement actuel :
        # l'echec est PROPRE et coute (compteur ++, ban a N=2).
        $hashFicheCourante = Get-Sha256Fidele $Fiche
        if ($hashFicheAuLancement -and $hashFicheCourante -and ($hashFicheAuLancement -ne $hashFicheCourante)) {
            $state.lanesLancees = @($state.lanesLancees | Where-Object { $_ -ne $Fiche })
            Save-State -Exclure @($Fiche)
            Write-VeilLog ("echec juge sur version perimee - non compte : lane '{0}' (code sortie {1}) - sha256 juge={2}, sha256 courant={3} ; marque retiree, fiche retee au prochain tour (I-298)" -f $Nom, $LASTEXITCODE, $hashFicheAuLancement, $hashFicheCourante) 'INFO'
            Add-Digest ("lane '{0}' : echec juge sur VERSION PERIMEE de la fiche (I-298) - non compte, retee" -f $Nom)
            return $false
        }
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
    # I-287 : un relancement parti solde les marques d'echec externe anterieures de cette
    # fiche - la preuve a servi ou n'a plus lieu d'etre, elle ne traine pas dans le poste.
    foreach ($m in @(Get-MarquesEchecExterne -FicheCible $Fiche)) {
        Remove-Item -LiteralPath $m.FullName -ErrorAction SilentlyContinue
        Write-VeilLog ("marque d'echec externe anterieure soldee par le relancement de '{0}' : {1}" -f $Nom, $m.Name) 'INFO'
    }
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
    # D-204 : fiches vues et resolues CE tour, tout statut confondu (y compris ecartees) -
    # sert a l'entretien de bloqueesConsignees en fin de fonction.
    $pathsVus = @()
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
        $pathsVus += $resolve.Path
        $leaf = [System.IO.Path]::GetFileNameWithoutExtension($resolve.Path)
        $nom = ($leaf -replace '^FICHE-', '' -replace '-\d{4}-\d{2}-\d{2}$', '').ToLower()
        $nom = ($nom -replace '[^a-z0-9]+', '-').Trim('-')
        if ($nom -notmatch '^[a-z0-9][a-z0-9-]*$') {
            Write-VeilLog "nom de lane invalide deriverait de '$leaf' - fiche ignoree : $($resolve.Path)" 'WARN'
            continue
        }
        # ---- D-204 : le sequencement devient un MARQUEUR MACHINE. Apres le test des marqueurs
        # de cloture (leur priorite est inchangee) : une cellule d'etat contenant « bloquee »
        # ecarte la ligne de la file. Insensible a la casse ET aux accents ('bloquee' doit
        # matcher aussi : ne pas reproduire I-296 ou le filtre des marqueurs n'entendait que
        # les formes accentuees) ; bornes de mot des deux cotes (« debloquee » ne matche pas).
        # L'ecart est journalise [INFO] UNE SEULE FOIS au changement (memoire
        # bloqueesConsignees, meme ecole que dejaLanceesConsignees du merge 99b95d2), citant la
        # lane et la cellule. Place APRES la resolution de la fiche : c'est son chemin resolu
        # qui sert de cle et son nom de lane qui est cite au journal. Le motif couvre les deux
        # graphies du feminin : accent+e (« bloquee » accorde) ET e-double non accentue.
        if ($celluleEtat -match '(?i)\bbloqu[\u00E9]?e{1,2}s?\b') {
            if (@($state.bloqueesConsignees) -notcontains $resolve.Path) {
                $state.bloqueesConsignees = @($state.bloqueesConsignees) + $resolve.Path
                Save-State
                Write-VeilLog ("fiche lanable ECARTEE : statut bloquee dans la cellule d'etat ('{0}') - lane '{1}' sortie de file jusqu'a deblocage (D-204)" -f $celluleEtat, $nom) 'INFO'
            }
            continue
        }
        # D-204 (suite) : DEBLOCAGE = retrait du mot. La memoire d'annonce est jetee
        # SILENCIEUSEMENT (aucun log : le changement a deja ete dit a l'annonce, le retour a
        # l'etat normal se voit au lancement) et la ligne redevient lanzable ci-dessous.
        if (@($state.bloqueesConsignees) -contains $resolve.Path) {
            $state.bloqueesConsignees = @($state.bloqueesConsignees | Where-Object { $_ -ne $resolve.Path })
            Save-State
        }
        $resultats += [pscustomobject]@{ Nom = $nom; Fiche = $resolve.Path }
    }
    # ---- D-204 (entretien, meme ecole que la detection de livraison I-289) : une memoire
    # d'ecart dont la fiche n'a plus ETE VUE ce tour (ligne livree/fermee/retiree du tableau)
    # est jetee silencieusement, pour qu'un retour ulterieur du marqueur sur cette fiche soit
    # reconsigne comme un NOUVEAU changement. Une fiche bloquee, justement, n'apparait jamais
    # dans les lanzables : le critere est « vue resolue ce tour », pas « presente en file ».
    foreach ($b in @($state.bloqueesConsignees)) {
        if (-not (@($pathsVus) -contains $b)) {
            $state.bloqueesConsignees = @($state.bloqueesConsignees | Where-Object { $_ -ne $b })
            Save-State
        }
    }
    return $resultats
}

function Test-TravailRestant {
    # ---- D-203 condition 2 : « il existe au moins un sujet a router ». Detection MECANIQUE
    # et declarative des deux sources nommees par la decision :
    #   (a) ITEM OUVERT A FICHISER : item de registre-items au statut « ouvert », portant une
    #       piste de routage technique (famille declaree dans $FAMILLES_TECHNIQUES), SANS
    #       champ fiche: pointant un fichier EXISTANT - meme definition que l'etape 1 du
    #       MANDAT PRODUCTEUR d'eveil-meta.md (« sans champ fiche: pointant un fichier
    #       existant ») ; un champ fiche: perime (fichier introuvable) ne route rien.
    #   (b) RAPPORT LIVRE NON INSTRUIT : rapport-*.md present au poste SANS recu, ni final
    #       ($state.rapports) ni provisoire ($state.rapportsAttente). Frontiere honnete : le
    #       veilleur sait LIVRER (recu pose quand le reveil part), il ne juge pas la
    #       profondeur de l'instruction d'une session deja reveillee.
    # Lecture pure, sure (try par fichier), arret au premier sujet trouve. Ne jette jamais :
    # registre-items absent/illisible => « pas de travail constate », conservateur.
    $trouve = [pscustomobject]@{ Restant = $false; Detail = '' }
    $itemsDir = Join-Path $MetaDir 'registre-items'
    foreach ($f in @(Get-ChildItem -LiteralPath $itemsDir -Filter '*.md' -File -ErrorAction SilentlyContinue)) {
        try { $lignes = @(Get-Content -LiteralPath $f.FullName -TotalCount 20 -Encoding UTF8) } catch { continue }
        $dansFrontiere = $false
        $statut = ''; $famille = ''; $champFiche = ''
        foreach ($l in $lignes) {
            if ($l -match '^---\s*$') { if ($dansFrontiere) { break } else { $dansFrontiere = $true; continue } }
            if (-not $dansFrontiere) { continue }
            if     ($l -match '^statut:\s*(.+?)\s*$') { $statut = $Matches[1].ToLower() }
            elseif ($l -match '^famille:\s*(.+?)\s*$') { $famille = $Matches[1].Trim().ToLower() }
            elseif ($l -match '^fiche:\s*(.+?)\s*$')   { $champFiche = $Matches[1].Trim().Trim('"').Trim("'") }
        }
        if ($statut -ne 'ouvert') { continue }
        if (@($FAMILLES_TECHNIQUES) -notcontains $famille) { continue }
        if ($champFiche -and (Test-Path -LiteralPath $champFiche)) { continue }   # deja route
        $trouve.Restant = $true
        $trouve.Detail  = "item a fichiser : $($f.Name)"
        return $trouve
    }
    foreach ($r in @(Get-ChildItem -LiteralPath $PostRoot -Filter 'rapport-*.md' -File -ErrorAction SilentlyContinue)) {
        if ($state.rapports.PSObject.Properties[$r.Name]) { continue }
        if ($state.rapportsAttente.PSObject.Properties[$r.Name]) { continue }
        $trouve.Restant = $true
        $trouve.Detail  = "rapport livre sans recu : $($r.Name)"
        return $trouve
    }
    return $trouve
}

function Get-HorodatagesMetaDigest {
    # FICHE reveils-surveilles (I-276/I-305) : horodatages des lignes [META] du digest
    # (« - HH:mm:ss - reveil META ... » posee par Invoke-WakeMeta/Invoke-EvenementMeta,
    # « eveil PRODUCTEUR » par la section 2bis) sous forme de DateTimeOffset, pour
    # confrontation aux traces de reveilsLances. Couvre les digests du jour de la trace a
    # aujourd'hui (un mort peut enjamber minuit) ; ligne/date illisible => sautee, jamais
    # fatal. LECTURE PURE : aucun effet de bord, aucun log.
    param([DateTimeOffset]$Depuis)
    $trouve = @()
    $prefixeMin = "digest-{0}" -f $Depuis.ToString('yyyy-MM-dd')
    foreach ($d in @(Get-ChildItem -LiteralPath $PostRoot -Filter 'digest-*.md' -File -ErrorAction SilentlyContinue |
                     Where-Object { $_.BaseName -ge $prefixeMin })) {
        foreach ($l in @(Get-Content -LiteralPath $d.FullName -Encoding UTF8 -ErrorAction SilentlyContinue)) {
            if ($l -notmatch '^\s*-\s*\d{2}:\d{2}:\d{2}\s*-\s*(reveil META|eveil PRODUCTEUR)(\s|\()') { continue }
            if ($l -notmatch '^\s*-\s*(\d{2}:\d{2}:\d{2})\s*-') { continue }
            try {
                $trouve += [DateTimeOffset]::ParseExact(
                    ("{0} {1}" -f $d.BaseName.Substring('digest-'.Length), $Matches[1]),
                    'yyyy-MM-dd HH:mm:ss',
                    [System.Globalization.CultureInfo]::InvariantCulture)
            } catch { }
        }
    }
    # NB : retour PLAT (pas de virgule protective) - l'appelant emballe deja dans @() ; un
    # emballage double ferait iterer la boucle sur un TABLEAU (crash op_Subtraction).
    return $trouve
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
    # ---- I-287 : entretien des marques d'echec externe - une preuve de plus de 48 h est
    # perimee : jetee (journalisee), pour que le poste ne conserve jamais qu'une preuve fraiche.
    if (-not $DryRun) {
        foreach ($m in @(Get-ChildItem -LiteralPath $PostRoot -Filter 'echec-externe-*.flag' -File -ErrorAction SilentlyContinue)) {
            if (((Get-Date) - $m.LastWriteTime).TotalHours -gt 48) {
                Remove-Item -LiteralPath $m.FullName -ErrorAction SilentlyContinue
                Write-VeilLog ("marque d'echec externe perimee (> 48 h) jetee : {0}" -f $m.Name) 'INFO'
            }
        }
    }
    # ---- CANAL DE DEPLOIEMENT FIDELE (livrables 1+4) : detection de derive a chaque tour.
    # Silence total si egalite (I-289), [WARN] unique nommant fichier et deux hash sinon.
    # Ne deploie JAMAIS seule : le deploiement reste le geste explicite -Deployer.
    Test-DeriveScriptsFideles
    # D-197 : observe ce tour-ci ? $null = depot moteur illisible (file lanes non lue)
    # => le declencheur producteur ne compte aucun tour sans observation reelle.
    $lancables = $null
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

    # ---- 1bis. REVEILS MORTS PROBABLES (fiche reveils-surveilles du 24/08 ; I-276/I-305).
    # Chaque entree de reveilsLances (« horodatage|motif|mode », posee par I-291 au moment
    # du lancement) agee de plus de $REVEIL_MORT_MINUTES est confrontee a ses suites
    # VISIBLES :
    #   - une ligne [META] du digest POSTERIEURE au lancement AU-DELA de la tolerance
    #     (l'activite meta a continue apres ce reveil - la ligne du lancement lui-meme,
    #     ecrite quelques secondes apres la trace, est exclue par la tolerance) ;
    #   - une historisation nouvelle dans registre-historisation posterieure au lancement
    #     (le travail reveille a abouti quelque part).
    # Les DEUX absentes => le reveil est parti dans le vide : [WARN] nommant le motif et
    # l'horodatage de la trace, consigne UNE SEULE FOIS par entree (memoire
    # reveilsMortsConsignees persistee, ecole I-289). AUCUN re-feu ici (anti-tempete) : le
    # rapport concerne reste soumis a la detection normale I-278 (section 1 ci-dessus), qui
    # pourra le reveiller quand le verrou meta tombera. L'horodatage du WARN sert de trace
    # de l'evenement pour Souhel.
    $histDirReveils = Join-Path $MetaDir 'registre-historisation'
    foreach ($entree in @($state.reveilsLances)) {
        if (-not $entree) { continue }
        if (@($state.reveilsMortsConsignees) -contains $entree) { continue }
        $partsReveil = @($entree -split '\|', 3)
        if ($partsReveil.Count -lt 3) { continue }
        try { $tTrace = [DateTimeOffset]::Parse($partsReveil[0]) } catch { continue }
        if ((([DateTimeOffset]::Now) - $tTrace).TotalMinutes -lt $REVEIL_MORT_MINUTES) { continue }
        $suiteVisible = $false
        foreach ($h in @(Get-HorodatagesMetaDigest -Depuis $tTrace)) {
            if (($h - $tTrace).TotalSeconds -gt $REVEIL_TRACE_TOLERANCESEC) { $suiteVisible = $true; break }
        }
        if (-not $suiteVisible) {
            foreach ($hf in @(Get-ChildItem -LiteralPath $histDirReveils -Filter '*.md' -File -ErrorAction SilentlyContinue)) {
                if ($hf.LastWriteTimeUtc -gt $tTrace.UtcDateTime) { $suiteVisible = $true; break }
            }
        }
        if ($suiteVisible) { continue }
        Write-VeilLog ("reveil mort probable : {0} ({1}) - rapport/event a re-examiner" -f $partsReveil[1], $partsReveil[0]) 'WARN'
        $state.reveilsMortsConsignees = @($state.reveilsMortsConsignees) + $entree
        if (-not $DryRun) { Save-State }
    }
    # entretien : memoires dont l'entree a quitte reveilsLances jetees silencieusement
    # (meme ecole que bloqueesConsignees) - jamais re-consignee tant que l'entree vit,
    # re-armee si le state a ete reconstruit sans elle.
    foreach ($m in @($state.reveilsMortsConsignees)) {
        if (@($state.reveilsLances) -notcontains $m) {
            $state.reveilsMortsConsignees = @($state.reveilsMortsConsignees | Where-Object { $_ -ne $m })
            if (-not $DryRun) { Save-State }
        }
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
                    # ---- I-299 : consommation des marques d'echec externe AU SCAN, AVANT de
                    # sauter une fiche « deja lancee ». Une lane morte reseau laisse parfois sa
                    # marque fraiche (< 24 h) pendant que la fiche porte encore la marque du
                    # deja-lance : sans ce passage elle restait « ignoree » en boucle pour
                    # toujours - la consultation I-287 ne s'y retrouve jamais, elle vit dans
                    # Invoke-LaunchLane et n'est atteinte qu'APRES une relance echouee. On
                    # consomme la marque, on retire la fiche du deja-lance (Save-State
                    # -Exclure, meme ecole que I-287 : la fusion anti-ecrasement ressusciterait
                    # sinon la marque retiree), et le flux NORMAL ci-dessous la relance CE tour.
                    # DryRun : rien n'est consomme ni supprime.
                    if (-not $DryRun) {
                        $marquesScan = @(Get-MarquesEchecExterne -FicheCible $c.Fiche)
                        if ($marquesScan.Count -gt 0) {
                            foreach ($m in $marquesScan) { Remove-Item -LiteralPath $m.FullName -ErrorAction SilentlyContinue }
                            $retireeDuDejaLance = $false
                            if (@($state.lanesLancees) -contains $c.Fiche) {
                                $state.lanesLancees = @($state.lanesLancees | Where-Object { $_ -ne $c.Fiche })
                                $retireeDuDejaLance = $true
                            }
                            # La memoire d'annonce I-289 eventuelle part avec : c'est CE log qui
                            # annonce le changement - le bloc deja-lancee n'a plus rien a dire
                            # (sinon consigner un etat obsolete au tour suivant).
                            $state.dejaLanceesConsignees = @($state.dejaLanceesConsignees | Where-Object { $_ -ne $c.Fiche })
                            Save-State -Exclure @($c.Fiche)
                            Write-VeilLog ("[I-299] marque d'echec externe fraiche CONSOMMEE au scan - lane '{0}'{1} - fiche reexaminee ce tour ({2})" -f `
                                $c.Nom, $(if ($retireeDuDejaLance) { ', retiree du deja-lance' } else { ', fiche non marquee lancee' }), (($marquesScan | ForEach-Object { $_.Name }) -join ', ')) 'INFO'
                        }
                    }
                    if (@($state.lanesLancees) -contains $c.Fiche) {
                        # I-275 livrable 1 : la memoire du deja-lance rend le refus VISIBLE
                        # (avant : continue silencieux, l'incident n'a pu etre compris qu'en
                        # reconstruisant l'historique).
                        # I-289 : VISIBLE ne veut pas dire REPETE - le [WARN] par tour decrivait
                        # l'etat NORMAL (fiche lancee, session en cours) et noyait les vrais
                        # signaux. Desormais INFO, consigne seulement AU CHANGEMENT : premiere
                        # observation de la fiche lancee ici ; la perte de sa marque et sa
                        # livraison (sortie de file) sont consignees aux deux blocs suivants.
                        if (@($state.dejaLanceesConsignees) -notcontains $c.Fiche) {
                            Write-VeilLog ("fiche deja lancee, ignoree (premiere observation - muet aux tours suivants tant que l'etat ne change pas) : {0}" -f $c.Fiche) 'INFO'
                            $state.dejaLanceesConsignees = @($state.dejaLanceesConsignees) + $c.Fiche
                            if (-not $DryRun) { Save-State }
                        }
                        continue
                    }
                    # I-289 (suite) : CHANGEMENT symetrique - la marque du deja-lance a disparu
                    # (deban officiel I-277 ou retrait apres echec) alors que l'etat « ignoree »
                    # avait ete annonce : on le dit UNE fois, puis la fiche est reexaminee
                    # normalement ci-dessous.
                    if (@($state.dejaLanceesConsignees) -contains $c.Fiche) {
                        $state.dejaLanceesConsignees = @($state.dejaLanceesConsignees | Where-Object { $_ -ne $c.Fiche })
                        if (-not $DryRun) { Save-State }
                        Write-VeilLog ("changement pour '{0}' : marque du deja-lance disparue - fiche de nouveau examinable" -f $c.Nom) 'INFO'
                    }
                    $ok = Invoke-LaunchLane -Nom $c.Nom -Fiche $c.Fiche
                    # I-275 livrable 9 : PAS de break. Un echec est SPECIFIQUE a une fiche ;
                    # la file CONTINUE (l'echec de 'veille-srd-relance' de 15:40-15:41 empechait
                    # 'catalogue-relance' de partir a deux tours successifs). La fiche en echec
                    # est retee au tour suivant, ou bannie apres N echecs consecutifs (livrable 3).
                }
                # ---- I-289 (entretien) : LIVRAISON DETECTEE. Une fiche annoncee « deja lancee »
                # qui quitte la file des lanables est livree/classee : changement consigne UNE
                # fois, memoire d'annonce nettoyee. Garde E3-E2 present : un tableau illisible
                # ou absent ne fait pas une livraison (Get-Lancables n'a peut-etre rien vu).
                if (Test-Path -LiteralPath $E3E2Path) {
                    foreach ($d in @($state.dejaLanceesConsignees)) {
                        if (-not (@($lancables | ForEach-Object { $_.Fiche }) -contains $d)) {
                            $state.dejaLanceesConsignees = @($state.dejaLanceesConsignees | Where-Object { $_ -ne $d })
                            if (-not $DryRun) { Save-State }
                            Write-VeilLog ("fiche lancee livree ou sortie de file : {0} - memoire d'annonce nettoyee" -f $d) 'INFO'
                        }
                    }
                }
            }
        }
    }

    # ---- 2bis. Reveil PRODUCTEUR (D-203, production pilotee par le besoin ; amende D-197)
    # Declencheur d'ETAT, plus calendaire (fin de la borne producteurJour 1/jour et de la
    # fenetre 9 h) : file vide ET travail restant ET slot libre => production. L'anti-tempete
    # EST le critere : du travail lanzable => pas de producteur (il ne doublonne pas la file) ;
    # « autant que necessaire » reste borne par les gardes INTACTES : verrou meta, volume
    # journalier, slots < D-192. toursSansLancable reste tenu comme signal de FAMINE
    # journalise, sans valeur-seuil declenchante ; le champ producteurJour n'est plus ni lu
    # ni ecrit. TUI vivant : meme routage que les autres evenements (digest, session fantome).
    if ($null -ne $lancables) {
        if (@($lancables).Count -gt 0) { $state.toursSansLancable = 0 }
        else                           { $state.toursSansLancable = [int]$state.toursSansLancable + 1 }
        # Le compteur vit ENTRE les processus : sauvegarde a chaque changement, sinon une
        # instance relancee repartirait de zero et l'etat idle ne serait jamais atteint.
        Save-State
        $dispoProd = Get-LanesActives
        $slotLibre = ($dispoProd.Disponible -and (@($dispoProd.Lanes).Count -lt $MAX_LANES_ACTIVES))
        # Condition 1 (file vide) : aucune fiche lanzable non marquee du deja-lance et non
        # bannie au tour courant - une fiche bannie est sortie de file jusqu'a intervention,
        # elle n'occupe pas plus la file qu'une fiche deja lancee.
        $enFile = @($lancables | Where-Object {
                        (@($state.fichesBannies) -notcontains $_.Fiche) -and
                        (@($state.lanesLancees) -notcontains $_.Fiche) })
        $fileVide = ($enFile.Count -eq 0)
        # Condition 2 (travail restant a router) : detection mecanique declarative (D-203).
        $travail = Test-TravailRestant
        Write-VeilLog ("producteur : fileVide={0} travailRestant={1}{2} slotLibre={3} toursSansLancable={4} (signal de famine, sans seuil declenchant)" -f `
            $fileVide, $travail.Restant, $(if ($travail.Restant) { " ({0})" -f $travail.Detail } else { '' }), $slotLibre, $state.toursSansLancable) 'INFO'
        if ($fileVide -and $travail.Restant -and $slotLibre) {
            $issue = Invoke-EvenementMeta -Motif 'reveil producteur (D-203)' `
                                          -Rapport '(pas de rapport : balayage registre-items / registre-decisions, voir MANDAT PRODUCTEUR dans ce prompt)' `
                                          -Mode 'producteur'
            if ($issue) {
                Write-VeilLog "eveil PRODUCTEUR parti - declencheur d'etat D-203 (file vide + travail restant + slot libre)"
            } else {
                Write-VeilLog "eveil producteur refuse ce tour (verrou/budget) - retente au tour suivant, rien consomme" 'WARN'
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
