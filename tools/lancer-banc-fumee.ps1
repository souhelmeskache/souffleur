<#
.SYNOPSIS
    Lanceur du banc de fumée (D-264) : deux panes herdr, une session-MJ et un
    joueur-banc, tenus au tempo d'une session de tour externe.

.DESCRIPTION
    Calqué sur tools/lancer-lane.ps1 (panes herdr, automode, gabarits de
    prompt) mais sans les gestes propres à une lane d'exécution : pas
    d'Issue GitHub, pas de branche/PR, pas de jeton `gh` — ce script ouvre
    deux panes dans le worktree courant et leur envoie chacun un
    prompt-gabarit (tools/prompts/banc-mj.md, tools/prompts/banc-joueur.md).

    Le tempo (« go »/« pause ») est tenu par une session de tour externe, pas
    par ce script : une fois les deux panes lancés, ce script rend la main —
    c'est la session `-SessionTour` qui envoie les « go » aux deux panes via
    `herdr agent prompt`.

.PARAMETER SessionTour
    Nom de la session de tour de contrôle qui tiendra le tempo go/pause des
    deux panes (obligatoire : les deux panes doivent savoir qui leur donne
    le go — sans ce nom, aucun protocole go/pause n'est identifiable dans
    les gabarits envoyés).

.PARAMETER Save
    Slug de la save de banc à jouer (obligatoire). Préparée à la main avant
    le premier lancement (hors périmètre de ce script) — voir spec Issue
    #151, § Hors périmètre.

.PARAMETER Tours
    Nombre de tours maximum du banc. Défaut : 12.

.PARAMETER Reprise
    Horodatage d'un run déjà journalisé (`bench/banc-fumee/<horodatage>/`) à
    reprendre plutôt que d'en ouvrir un neuf (Issue #212). Exclusif avec la
    création d'un journal neuf : quand ce paramètre est fourni, ce script
    n'ouvre AUCUN dossier — il pointe les deux agents vers le journal
    existant, déduit le prochain numéro de tour du dernier `prose-NN.md`
    présent, et leur transmet la liste des fichiers déjà présents pour ce
    numéro (`action-NN`/`tour-NN`/`prose-NN`) pour qu'un Director ne rejoue
    pas un jet déjà appliqué (cas vécu au tour 21, voir #212). Refuse de
    démarrer (code de sortie non nul) si le dossier du run nommé n'existe
    pas — y compris en `-DryRun`.

.PARAMETER ModeleMj
    Modèle de l'agent MJ ($AgentMj). Défaut : sonnet (comportement historique
    inchangé). Ajouté pour le banc de nuit (#260, A/B Director haiku/sonnet).

.PARAMETER ModeleJoueur
    Modèle de l'agent joueur-banc. Défaut : sonnet (comportement historique
    inchangé).

.PARAMETER SavesDirOverride
    Dossier à imposer comme SAVES_DIR aux DEUX panes (`herdr pane split
    --env`), pour qu'une save copiée hors de saves/ (#260, banc de nuit —
    isolation par partie) soit résolue par `-Save <slug>` comme si elle y
    était. Vide par défaut : aucun `--env` posé, comportement historique
    inchangé (résolution SAVES_DIR normale de coderain/config.py).

.PARAMETER DryRun
    Affiche le montage complet (panes, gabarits remplis, chemin du journal)
    sans rien créer ni lancer.

.EXAMPLE
    .\tools\lancer-banc-fumee.ps1 -SessionTour meta-rpg-ce -Save dks-banc -DryRun
    .\tools\lancer-banc-fumee.ps1 -SessionTour meta-rpg-ce -Save dks-banc
    .\tools\lancer-banc-fumee.ps1 -SessionTour meta-rpg-ce -Save dks-banc -Tours 20
    .\tools\lancer-banc-fumee.ps1 -SessionTour meta-rpg-ce -Save dks-banc -Reprise 20260831-202617
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SessionTour,

    [Parameter(Mandatory = $true)]
    [string]$Save,

    [int]$Tours = 12,

    [string]$Reprise = '',

    # Modèle des deux agents (Issue #260, banc de nuit — A/B Director) :
    # défauts inchangés (sonnet/sonnet) pour ne rien changer au banc de
    # fumée historique quand ces paramètres ne sont pas fournis.
    [string]$ModeleMj = 'sonnet',
    [string]$ModeleJoueur = 'sonnet',

    # Dossier SAVES_DIR à imposer aux DEUX panes (Issue #260) : une copie de
    # save isolée par partie de banc de nuit vit hors de saves/ (D-109/D-178,
    # jamais de matériau réel gitté) — ce paramètre pointe les deux agents
    # dessus via `herdr pane split --env`, sans toucher au moteur ni à
    # config.py (résolution SAVES_DIR déjà dynamique, cf. coderain/config.py).
    [string]$SavesDirOverride = '',

    # Dossier de journal imposé (Issue #260, banc de nuit) : au lieu du
    # bench\banc-fumee\<horodate> auto-daté, écrit tour-NN/prose-NN/
    # action-NN directement dans ce dossier — nuit.sh y pointe une partie
    # (bench/nuit-AAAAMMJJ/partie-NN/), pour que le journal ET la save
    # isolée (-SavesDirOverride) vivent sous le même dossier de partie.
    # Exclusif avec -Reprise (les deux pilotent $JournalDir autrement).
    [string]$JournalDirOverride = '',

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# --- 0. Résolution herdr (D-228, même repli que lancer-lane.ps1) ----------

function Resolve-ExternalCommand {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string[]]$FallbackPaths
    )

    $found = Get-Command $Name -ErrorAction SilentlyContinue
    if ($found) {
        return $found.Source
    }
    foreach ($path in $FallbackPaths) {
        if (Test-Path $path) {
            return $path
        }
    }
    Write-Error "Commande '$Name' introuvable : ni dans le PATH, ni aux chemins de repli connus ($($FallbackPaths -join ', ')). Installe-la ou ajoute son chemin réel aux chemins de repli de ce script."
    exit 1
}

$HerdrExe = Resolve-ExternalCommand -Name 'herdr' -FallbackPaths @("$env:LOCALAPPDATA\Programs\Herdr\bin\herdr.exe")

$RepoRoot = (git -C $PSScriptRoot rev-parse --show-toplevel).Trim()

# --- 1. Horodate + arborescence du journal ---------------------------------
#
# bench/banc-fumee/<horodate>/ — gitignoré (voir .gitignore, D-109/D-178) :
# le journal peut citer la fiction du banc DKS sans jamais verser cette
# fiction au dépôt. Créé par CE script (critère d'acceptation #3), pas par
# les panes eux-mêmes, pour que le chemin soit connu et stable avant même
# l'envoi des prompts.
#
# Mode -Reprise (#212) : pas de nouveau dossier — le run nommé doit déjà
# exister, et le prochain numéro de tour se déduit du dernier `prose-NN.md`
# présent. Cette déduction tourne AUSSI en -DryRun (la validation « le run
# existe » ne dépend pas de savoir si on lance pour de vrai).

$FichiersExistantsProchainTour = @()

if ($Reprise -and $JournalDirOverride) {
    Write-Error "-Reprise et -JournalDirOverride sont exclusifs."
    exit 1
}

if ($JournalDirOverride) {
    $Horodate = ''
    $JournalDir = $JournalDirOverride
    $ProchainTour = 1
    $ProchainTourStr = '01'
} elseif ($Reprise) {
    $Horodate = $Reprise
    $JournalDir = Join-Path $RepoRoot "bench\banc-fumee\$Horodate"
    if (-not (Test-Path $JournalDir)) {
        Write-Error "Reprise impossible : dossier de journal introuvable ($JournalDir) — le run '$Reprise' n'existe pas."
        exit 1
    }

    $derniereProseNum = 0
    $proseFiles = Get-ChildItem -Path $JournalDir -Filter 'prose-*.md' -File -ErrorAction SilentlyContinue
    foreach ($f in $proseFiles) {
        if ($f.BaseName -match '^prose-(\d+)$') {
            $n = [int]$Matches[1]
            if ($n -gt $derniereProseNum) { $derniereProseNum = $n }
        }
    }
    $ProchainTour = $derniereProseNum + 1
    $ProchainTourStr = '{0:D2}' -f $ProchainTour

    foreach ($prefixe in @('action', 'tour', 'prose')) {
        $nomFichier = "$prefixe-$ProchainTourStr.md"
        if (Test-Path (Join-Path $JournalDir $nomFichier)) {
            $FichiersExistantsProchainTour += $nomFichier
        }
    }
} else {
    $Horodate = Get-Date -Format 'yyyyMMdd-HHmmss'
    $JournalDir = Join-Path $RepoRoot "bench\banc-fumee\$Horodate"
    $ProchainTour = 1
    $ProchainTourStr = '01'
}

# --- 2. Gabarits de prompt : lecture + substitution ------------------------
#
# Les fichiers sous tools/prompts/ portent le texte figé du protocole
# (go/pause, contrat MJ, sobriété joueur) — vérifié par un test de forme
# indépendant de ce script (tests/*.py, pas d'appel LLM). Ce script se
# contente d'y injecter les valeurs de ce run (save, tours, session tour,
# dossier du journal).

function Get-GabaritRempli {
    param(
        [Parameter(Mandatory)] [string]$CheminGabarit,
        [Parameter(Mandatory)] [string]$Save,
        [Parameter(Mandatory)] [int]$Tours,
        [Parameter(Mandatory)] [string]$SessionTour,
        [Parameter(Mandatory)] [string]$JournalDir
    )

    if (-not (Test-Path $CheminGabarit)) {
        Write-Error "Gabarit introuvable : $CheminGabarit"
        exit 1
    }

    $texte = Get-Content -Path $CheminGabarit -Raw -Encoding utf8
    $texte = $texte.Replace('{{SAVE}}', $Save)
    $texte = $texte.Replace('{{TOURS}}', [string]$Tours)
    $texte = $texte.Replace('{{SESSION_TOUR}}', $SessionTour)
    $texte = $texte.Replace('{{JOURNAL_DIR}}', $JournalDir)
    return $texte
}

# Bloc -Reprise (#212) : ajouté APRÈS le gabarit figé (hors périmètre #209,
# tools/prompts/banc-mj.md et banc-joueur.md n'ont pas de placeholder dédié)
# — transmet aux deux agents le journal existant, le prochain numéro de tour
# et les fichiers déjà présents pour ce numéro, pour qu'un Director ne
# rejoue pas un jet déjà appliqué (cas vécu au tour 21, voir #212).

function Get-BlocReprise {
    param(
        [Parameter(Mandatory)] [string]$JournalDir,
        [Parameter(Mandatory)] [int]$ProchainTour,
        [Parameter(Mandatory)] [AllowEmptyCollection()] [string[]]$FichiersExistants
    )

    $listeFichiers = if ($FichiersExistants.Count -gt 0) { $FichiersExistants -join ', ' } else { 'aucun' }

    @"

## Reprise (paramètre -Reprise, hors gabarit — Issue #212)

Ce lancement REPREND un journal existant, il n'en ouvre pas un neuf :

- Journal existant : $JournalDir
- Prochain numéro de tour à jouer : $ProchainTour
- Fichiers déjà présents pour ce numéro de tour : $listeFichiers

Si un fichier ci-dessus existe déjà pour ce numéro (ex. un jet déjà résolu et
appliqué au moteur mais dont la prose ou `record_turn` n'a pas encore eu
lieu), NE LE REJOUE PAS : lis son contenu et continue le tour depuis où il
s'est arrêté, plutôt que de refaire un geste déjà appliqué.
"@
}

$GabaritMjPath = Join-Path $RepoRoot 'tools\prompts\banc-mj.md'
$GabaritJoueurPath = Join-Path $RepoRoot 'tools\prompts\banc-joueur.md'

$PromptMj = Get-GabaritRempli -CheminGabarit $GabaritMjPath -Save $Save -Tours $Tours -SessionTour $SessionTour -JournalDir $JournalDir
$PromptJoueur = Get-GabaritRempli -CheminGabarit $GabaritJoueurPath -Save $Save -Tours $Tours -SessionTour $SessionTour -JournalDir $JournalDir

if ($Reprise) {
    $BlocReprise = Get-BlocReprise -JournalDir $JournalDir -ProchainTour $ProchainTour -FichiersExistants $FichiersExistantsProchainTour
    $PromptMj += $BlocReprise
    $PromptJoueur += $BlocReprise
}

# Correctif scratchpad (issue #196) : 32 chars max pour un nom d'agent herdr —
# le slug de save faisait déborder ("banc-mj-beyond-the-vale-of-madness" = 33+).
$AgentMj = "banc-mj"
$AgentJoueur = "banc-joueur"

# --- 3. Dry-run : affiche le montage complet sans rien lancer --------------

if ($DryRun) {
    Write-Output "=== DryRun — rien n'est lancé ==="
    Write-Output "Session tour   : $SessionTour"
    Write-Output "Save           : $Save"
    Write-Output "Tours (max)    : $Tours"
    if ($Reprise) {
        Write-Output "Reprise        : $Reprise (journal existant, aucun dossier créé)"
        Write-Output "Prochain tour  : $ProchainTourStr"
    }
    Write-Output "Journal        : $JournalDir"
    Write-Output "Pane MJ        : agent $AgentMj (claude, $ModeleMj, effort medium)"
    Write-Output "Pane joueur    : agent $AgentJoueur (claude, $ModeleJoueur, effort low)"
    if ($SavesDirOverride) {
        Write-Output "SAVES_DIR      : $SavesDirOverride (imposé aux deux panes)"
    }
    Write-Output ""
    Write-Output "Commandes qui seraient exécutées :"
    Write-Output "  (herdr résolu : $HerdrExe)"
    if ($Reprise) {
        Write-Output "  (mode reprise : pas de New-Item, journal déjà présent)"
    } else {
        Write-Output "  New-Item -ItemType Directory -Force -Path `"$JournalDir`""
    }
    Write-Output "  `$paneCur = $HerdrExe pane current"
    $envArgAffiche = if ($SavesDirOverride) { " --env `"SAVES_DIR=$SavesDirOverride`"" } else { "" }
    Write-Output "  `$paneMj = $HerdrExe pane split <paneCur> --direction right --cwd `"$RepoRoot`"$envArgAffiche"
    Write-Output "  `$paneJoueur = $HerdrExe pane split <paneMj> --direction down --cwd `"$RepoRoot`"$envArgAffiche"
    Write-Output "  (automode : pose .claude\settings.local.json dans $RepoRoot, sans écraser s'il existe déjà — Issue #210)"
    Write-Output "  $HerdrExe agent start $AgentMj --kind claude --pane <paneMj> -- --model $ModeleMj --effort medium --permission-mode acceptEdits"
    Write-Output "  $HerdrExe agent start $AgentJoueur --kind claude --pane <paneJoueur> -- --model $ModeleJoueur --effort low --permission-mode acceptEdits"
    Write-Output "  $HerdrExe agent prompt $AgentMj <prompt-gabarit MJ ci-dessous> --wait --until working --timeout 15000"
    Write-Output "  $HerdrExe agent prompt $AgentJoueur <prompt-gabarit joueur ci-dessous> --wait --until working --timeout 15000"
    Write-Output ""
    Write-Output "--- Prompt-gabarit MJ (rempli) ---"
    Write-Output $PromptMj
    Write-Output ""
    Write-Output "--- Prompt-gabarit joueur-banc (rempli) ---"
    Write-Output $PromptJoueur
    exit 0
}

# --- 4. Exécution réelle ----------------------------------------------------

if ($Reprise) {
    Write-Output "Reprise du journal existant ($JournalDir) — aucun dossier créé."
} else {
    Write-Output "Création de l'arborescence du journal ($JournalDir)..."
    New-Item -ItemType Directory -Force -Path $JournalDir | Out-Null
}

Write-Output "Ouverture des deux panes (MJ + joueur-banc)..."
$paneCurJson = & $HerdrExe pane current
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr pane current' — impossible de localiser le pane courant."
    exit 1
}
$paneCurData = $paneCurJson | ConvertFrom-Json
$paneCurId = $paneCurData.result.pane.pane_id
if (-not $paneCurId) { $paneCurId = $paneCurData.result.pane_id }
if (-not $paneCurId) { Write-Error "pane courant illisible"; exit 1 }

# Correctif scratchpad (issue #196) : le MJ prend un pane NEUF (split), jamais
# le pane courant — et le chemin JSON est result.pane.pane_id.
#
# $SavesDirOverride (#260) : --env SAVES_DIR=... posé sur les DEUX panes, pas
# seulement au niveau du process courant — la résolution SAVES_DIR
# (coderain/config.py::_resolve_dir) est dynamique par process, chaque agent
# lit son propre environnement de pane.
$envSplitArgs = @()
if ($SavesDirOverride) { $envSplitArgs = @('--env', "SAVES_DIR=$SavesDirOverride") }

$paneMjJson = & $HerdrExe pane split $paneCurId --direction right --cwd $RepoRoot @envSplitArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr pane split' pour ouvrir le pane MJ."
    exit 1
}
$paneMjData = $paneMjJson | ConvertFrom-Json
$paneMjId = $paneMjData.result.pane.pane_id
if (-not $paneMjId) { $paneMjId = $paneMjData.result.pane_id }
if (-not $paneMjId) { Write-Error "pane MJ illisible"; exit 1 }

$paneJoueurJson = & $HerdrExe pane split $paneMjId --direction down --cwd $RepoRoot @envSplitArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr pane split' pour ouvrir le pane joueur-banc."
    exit 1
}
$paneJoueurData = $paneJoueurJson | ConvertFrom-Json
$paneJoueurId = $paneJoueurData.result.pane.pane_id
if (-not $paneJoueurId) { $paneJoueurId = $paneJoueurData.result.pane_id }
if (-not $paneJoueurId) { Write-Error "pane joueur-banc illisible"; exit 1 }

Write-Output "Pane MJ         : $paneMjId"
Write-Output "Pane joueur-banc: $paneJoueurId"

# --- Automode local (Issue #210), même mécanisme que lancer-lane.ps1 -------
#
# lancer-lane.ps1 (lignes ~608-624) pose ce fichier dans un worktree NEUF à
# chaque lane ; ce script tourne, lui, dans le worktree courant, relancé
# plusieurs fois d'un run à l'autre (reprise) — on ne l'écrase donc PAS s'il
# existe déjà, pour ne pas effacer un réglage local voulu par l'opérateur.
#
# Correctif revue PR #224 (REFUS) : Bash(*) seul ne couvre PAS le blocage
# constaté dans #210 — les deux agents du banc jouent leurs tours via les
# outils MCP `coderain-engine` (`module_get_node`, etc.), jamais via Bash.
# `mcp__coderain-engine__*` en allow, en plus de Bash(*), pour que le
# premier appel MCP du MJ ne se bloque plus sur une demande de permission.
$claudeDir = Join-Path $RepoRoot '.claude'
$settingsLocalPath = Join-Path $claudeDir 'settings.local.json'
if (-not (Test-Path $settingsLocalPath)) {
    New-Item -ItemType Directory -Force -Path $claudeDir | Out-Null
    $settingsLocal = [ordered]@{
        permissions = [ordered]@{
            allow = @('Bash(*)', 'mcp__coderain-engine__*')
            deny  = @(
                'Bash(git commit --no-verify*)',
                'Bash(git commit -n*)',
                'Bash(git push --no-verify*)',
                'Bash(git push --force*)',
                'Bash(git push -f*)'
            )
        }
    }
    ($settingsLocal | ConvertTo-Json -Depth 5) | Set-Content -Path $settingsLocalPath -Encoding utf8
    Write-Output "Automode posé : $settingsLocalPath"
} else {
    Write-Output "Automode déjà présent, non modifié : $settingsLocalPath"
}

Write-Output "Démarrage de l'agent MJ ($AgentMj, $ModeleMj, effort medium)..."
& $HerdrExe agent start $AgentMj --kind claude --pane $paneMjId -- --model $ModeleMj --effort medium --permission-mode acceptEdits
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr agent start' pour $AgentMj sur le pane $paneMjId."
    exit 1
}

Write-Output "Démarrage de l'agent joueur-banc ($AgentJoueur, $ModeleJoueur, effort low)..."
& $HerdrExe agent start $AgentJoueur --kind claude --pane $paneJoueurId -- --model $ModeleJoueur --effort low --permission-mode acceptEdits
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr agent start' pour $AgentJoueur sur le pane $paneJoueurId."
    exit 1
}

Write-Output "Envoi du prompt-gabarit MJ..."
& $HerdrExe agent prompt $AgentMj $PromptMj --wait --until working --timeout 15000
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de l'envoi du prompt à $AgentMj (ou l'agent n'est pas passé en 'working' sous 15s)."
    exit 1
}

Write-Output "Envoi du prompt-gabarit joueur-banc..."
& $HerdrExe agent prompt $AgentJoueur $PromptJoueur --wait --until working --timeout 15000
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de l'envoi du prompt à $AgentJoueur (ou l'agent n'est pas passé en 'working' sous 15s)."
    exit 1
}

Write-Output "Banc de fumée lancé (save $Save, $Tours tours max, session tour $SessionTour) — le script rend la main, le tempo go/pause est tenu par la session tour dans les panes $paneMjId (MJ) et $paneJoueurId (joueur-banc)."
Write-Output "Journal : $JournalDir"
