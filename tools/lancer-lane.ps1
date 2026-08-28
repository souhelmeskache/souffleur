<#
.SYNOPSIS
    Lanceur minimal d'une lane Herdr sur une Issue GitHub du repo souffleur.

.DESCRIPTION
    Pas de démon, pas de superviseur. Une commande = une lane. Le plafond de
    lanes et la pause sont garantis par l'usage (on ne lance pas = pause ; on
    lance une fois = 1 lane). Voir BRIEF-2026-08-28-phase-2-herdr-premiere-lane.md
    (bloc C) dans le vault meta-rpg.

.PARAMETER Issue
    Numéro de l'Issue GitHub à lancer en lane (repo souhelmeskache/souffleur).

.PARAMETER Modele
    sonnet (défaut) | opus | fable. Jamais haiku (D-225) — refusé explicitement
    si passé.

.PARAMETER Effort
    low | medium. Par défaut : low si l'issue porte le label `mecanique`,
    medium sinon (D-225 : contrôle qualité = fable medium, exécution = sonnet
    low/medium, orchestration = opus).

.PARAMETER DryRun
    Affiche ce qui serait lancé (issue, branche, worktree, pane, commandes
    herdr) sans rien créer ni lancer.

.EXAMPLE
    .\tools\lancer-lane.ps1 14 -DryRun
    .\tools\lancer-lane.ps1 14 -Modele fable -Effort medium
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [int]$Issue,

    [Parameter()]
    [ValidateSet('sonnet', 'opus', 'fable')]
    [string]$Modele = 'sonnet',

    [Parameter()]
    [ValidateSet('low', 'medium')]
    [string]$Effort,

    [Parameter()]
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# Jamais Haiku (D-225) — filet en plus du ValidateSet, au cas où un appelant
# contournerait le paramètre typé via -Modele:$var non validé en amont.
if ($Modele -eq 'haiku') {
    Write-Error "Modele 'haiku' exclu par D-225 (contrôle qualité = fable, exécution = sonnet, orchestration = opus)."
    exit 1
}

$RepoRoot = (git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
$RepoSlug = 'souhelmeskache/souffleur'
$PauseFlag = Join-Path $RepoRoot 'tools/PAUSE'

# --- 1. Lecture de l'issue ---------------------------------------------

$issueJson = gh issue view $Issue --repo $RepoSlug --json number,title,body,labels,url
if ($LASTEXITCODE -ne 0) {
    Write-Error "Impossible de lire l'Issue #$Issue sur $RepoSlug."
    exit 1
}
$issueData = $issueJson | ConvertFrom-Json

$labelNames = @($issueData.labels | ForEach-Object { $_.name })
if ($labelNames -notcontains 'prete') {
    Write-Error "Issue #$Issue : label 'prete' absent — refus de lancer (queue de travail = labelisée 'prete' uniquement)."
    exit 1
}

# --- 2. Garde-fou pause --------------------------------------------------

if (Test-Path $PauseFlag) {
    Write-Error "Pause active (tools/PAUSE présent) — aucune lane ne se lance. Supprime le fichier pour reprendre."
    exit 1
}

# --- 3. Défauts d'effort selon D-225 -------------------------------------

if (-not $Effort) {
    $Effort = if ($labelNames -contains 'mecanique') { 'low' } else { 'medium' }
}

# --- 4. Gabarit de prompt -------------------------------------------------

function Build-LanePrompt {
    param(
        [Parameter(Mandatory)] [int]$IssueNumber,
        [Parameter(Mandatory)] [string]$Title,
        [Parameter(Mandatory)] [string]$Body,
        [Parameter(Mandatory)] [string]$RepoSlug
    )

    @"
# Lane — Issue #$IssueNumber : $Title

## Contexte (corps de l'Issue #$IssueNumber)

$Body

## Règles fixes de toute lane de ce dispatch

- Travaille exclusivement dans ce worktree.
- Petite PR ciblée vers ``main`` (verrouillée côté serveur : PR + CI obligatoires) — pas de commit direct sur ``main``.
- CI verte attendue avant de considérer la lane terminée.
- **Jamais ``--no-verify``** sur aucune commande git, en aucune circonstance.

## Commentaires d'Issue obligatoires (trois jalons, sur l'Issue #$IssueNumber)

Cette lane commente ``gh issue comment $IssueNumber --repo $RepoSlug`` à
chacun des trois moments suivants — aucun n'est optionnel :

1. **Jalon franchi** — dès qu'une étape significative du travail est bouclée
   (ex. diagnostic posé, correctif écrit, tests rejoués), un commentaire court
   décrivant ce qui vient d'être franchi.
2. **« BLOQUÉ : <question> »** — dès qu'un arbitrage manque pour continuer
   (ambiguïté de spec, décision qui dépasse le périmètre de la lane, conflit
   non résoluble seul). Le commentaire commence littéralement par
   ``BLOQUÉ : `` suivi de la question précise qui débloque.
3. **« TERMINÉ : <PR> »** — à la toute fin, une fois la PR ouverte (mergée ou
   non). Le commentaire commence littéralement par ``TERMINÉ : `` suivi du
   lien de la PR.

## Test du canal rapide (à faire une seule fois, au premier blocage)

Avant de poster ton tout premier commentaire ``BLOQUÉ : ...`` sur cette
Issue, tente d'abord ``SendMessage`` vers la session ``meta-rpg-32`` avec la
question qui te bloque. C'est un test du canal rapide (interrogation directe
d'une session plutôt qu'un aller-retour par commentaire GitHub) :

- Si ``SendMessage`` aboutit (session trouvée, message envoyé) : note-le dans
  ton commentaire ``BLOQUÉ : ...`` (« canal rapide testé : SendMessage vers
  meta-rpg-32 a fonctionné ») et attends sa réponse avant de continuer si elle
  arrive vite ; sinon poste quand même le commentaire GitHub en parallèle pour
  ne pas rester bloqué.
- Si ``SendMessage`` échoue ou n'est pas disponible dans ton environnement :
  note-le aussi dans le commentaire (« canal rapide testé : SendMessage
  indisponible/échoué — repli sur commentaire GitHub ») et continue avec le
  commentaire ``BLOQUÉ : ...`` normalement, qui reste le canal de secours
  garanti.

Ce test ne se refait pas à chaque blocage ultérieur de la même lane — une
seule tentative suffit à établir si le canal fonctionne dans cet
environnement ; les blocages suivants passent directement par le commentaire
``BLOQUÉ : ...``.
"@
}

$promptText = Build-LanePrompt -IssueNumber $issueData.number -Title $issueData.title -Body $issueData.body -RepoSlug $RepoSlug

$branch = "lane-$Issue"
$agentName = "lane-$Issue"

# --- 5. Dry-run : affiche et sort sans rien créer -------------------------

if ($DryRun) {
    Write-Output "=== DryRun — rien n'est lancé ==="
    Write-Output "Issue          : #$($issueData.number) — $($issueData.title)"
    Write-Output "URL            : $($issueData.url)"
    Write-Output "Labels         : $($labelNames -join ', ')"
    Write-Output "Modele         : $Modele"
    Write-Output "Effort         : $Effort"
    Write-Output "Branche        : $branch"
    Write-Output "Nom agent      : $agentName"
    Write-Output ""
    Write-Output "Commandes qui seraient exécutées :"
    Write-Output "  herdr worktree create --cwd `"$RepoRoot`" --branch $branch"
    Write-Output "  herdr agent start $agentName --kind claude --pane <pane_id_du_worktree> -- --model $Modele"
    Write-Output "  herdr agent prompt $agentName <prompt-gabarit ci-dessous> --wait"
    Write-Output ""
    Write-Output "--- Prompt-gabarit ---"
    Write-Output $promptText
    exit 0
}

# --- 6. Exécution réelle ---------------------------------------------------

Write-Output "Création du worktree + pane pour la lane-$Issue..."
$worktreeJson = herdr worktree create --cwd $RepoRoot --branch $branch
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr worktree create' pour la branche $branch."
    exit 1
}
$worktreeData = $worktreeJson | ConvertFrom-Json
$paneId = $worktreeData.result.root_pane.pane_id
$worktreePath = $worktreeData.result.worktree.path

Write-Output "Worktree : $worktreePath"
Write-Output "Pane     : $paneId"

Write-Output "Démarrage de l'agent claude ($Modele)..."
herdr agent start $agentName --kind claude --pane $paneId -- --model $Modele
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr agent start' pour $agentName sur le pane $paneId."
    exit 1
}

Write-Output "Envoi du prompt-gabarit..."
herdr agent prompt $agentName $promptText --wait
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de l'envoi du prompt à $agentName."
    exit 1
}

Write-Output "Lane $agentName lancée sur l'Issue #$Issue (effort $Effort, modèle $Modele)."
