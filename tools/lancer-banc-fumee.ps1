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

.PARAMETER DryRun
    Affiche le montage complet (panes, gabarits remplis, chemin du journal)
    sans rien créer ni lancer.

.EXAMPLE
    .\tools\lancer-banc-fumee.ps1 -SessionTour meta-rpg-ce -Save dks-banc -DryRun
    .\tools\lancer-banc-fumee.ps1 -SessionTour meta-rpg-ce -Save dks-banc
    .\tools\lancer-banc-fumee.ps1 -SessionTour meta-rpg-ce -Save dks-banc -Tours 20
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SessionTour,

    [Parameter(Mandatory = $true)]
    [string]$Save,

    [int]$Tours = 12,

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

$Horodate = Get-Date -Format 'yyyyMMdd-HHmmss'
$JournalDir = Join-Path $RepoRoot "bench\banc-fumee\$Horodate"

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

$GabaritMjPath = Join-Path $RepoRoot 'tools\prompts\banc-mj.md'
$GabaritJoueurPath = Join-Path $RepoRoot 'tools\prompts\banc-joueur.md'

$PromptMj = Get-GabaritRempli -CheminGabarit $GabaritMjPath -Save $Save -Tours $Tours -SessionTour $SessionTour -JournalDir $JournalDir
$PromptJoueur = Get-GabaritRempli -CheminGabarit $GabaritJoueurPath -Save $Save -Tours $Tours -SessionTour $SessionTour -JournalDir $JournalDir

$AgentMj = "banc-mj-$Save"
$AgentJoueur = "banc-joueur-$Save"

# --- 3. Dry-run : affiche le montage complet sans rien lancer --------------

if ($DryRun) {
    Write-Output "=== DryRun — rien n'est lancé ==="
    Write-Output "Session tour   : $SessionTour"
    Write-Output "Save           : $Save"
    Write-Output "Tours (max)    : $Tours"
    Write-Output "Journal        : $JournalDir"
    Write-Output "Pane MJ        : agent $AgentMj (claude, sonnet, effort medium)"
    Write-Output "Pane joueur    : agent $AgentJoueur (claude, sonnet, effort low)"
    Write-Output ""
    Write-Output "Commandes qui seraient exécutées :"
    Write-Output "  (herdr résolu : $HerdrExe)"
    Write-Output "  New-Item -ItemType Directory -Force -Path `"$JournalDir`""
    Write-Output "  `$paneMj = $HerdrExe pane current"
    Write-Output "  `$paneJoueur = $HerdrExe pane split <paneMj> --direction right --cwd `"$RepoRoot`""
    Write-Output "  $HerdrExe agent start $AgentMj --kind claude --pane <paneMj> -- --model sonnet --effort medium --permission-mode acceptEdits"
    Write-Output "  $HerdrExe agent start $AgentJoueur --kind claude --pane <paneJoueur> -- --model sonnet --effort low --permission-mode acceptEdits"
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

Write-Output "Création de l'arborescence du journal ($JournalDir)..."
New-Item -ItemType Directory -Force -Path $JournalDir | Out-Null

Write-Output "Ouverture des deux panes (MJ + joueur-banc)..."
$paneMjJson = & $HerdrExe pane current
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr pane current' — impossible de localiser le pane courant pour y ancrer le pane MJ."
    exit 1
}
$paneMjData = $paneMjJson | ConvertFrom-Json
$paneMjId = $paneMjData.result.pane_id

$paneJoueurJson = & $HerdrExe pane split $paneMjId --direction right --cwd $RepoRoot
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr pane split' pour ouvrir le pane joueur-banc."
    exit 1
}
$paneJoueurData = $paneJoueurJson | ConvertFrom-Json
$paneJoueurId = $paneJoueurData.result.pane_id

Write-Output "Pane MJ         : $paneMjId"
Write-Output "Pane joueur-banc: $paneJoueurId"

# Pas d'automode Bash(*) ici, à la différence de lancer-lane.ps1 : ce banc ne
# crée ni branche ni PR (les deux panes n'ont pas besoin d'un large accès
# shell pour jouer des tours via les outils MCP) — laissé aux permissions
# déjà en place dans le worktree courant.

Write-Output "Démarrage de l'agent MJ ($AgentMj, sonnet, effort medium)..."
& $HerdrExe agent start $AgentMj --kind claude --pane $paneMjId -- --model sonnet --effort medium --permission-mode acceptEdits
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr agent start' pour $AgentMj sur le pane $paneMjId."
    exit 1
}

Write-Output "Démarrage de l'agent joueur-banc ($AgentJoueur, sonnet, effort low)..."
& $HerdrExe agent start $AgentJoueur --kind claude --pane $paneJoueurId -- --model sonnet --effort low --permission-mode acceptEdits
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
