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

.PARAMETER SessionTour
    Nom de la session de tour de contrôle à tester en premier via SendMessage
    au premier blocage de la lane (ex. meta-rpg-5f). Vide par défaut : ce nom
    change à chaque fil de tour, aucune valeur figée ne resterait valide — sans
    ce paramètre la lane saute directement le test du canal rapide et poste son
    ``BLOQUÉ : ...`` sur l'Issue, qui reste le canal de secours garanti.

.EXAMPLE
    .\tools\lancer-lane.ps1 14 -DryRun
    .\tools\lancer-lane.ps1 14 -Modele fable -Effort medium
    .\tools\lancer-lane.ps1 14 -SessionTour meta-rpg-5f
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
    [string]$SessionTour = '',

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

# --- 1. Garde-fou pause (garde la moins chère d'abord — avant tout appel réseau) --

if (Test-Path $PauseFlag) {
    Write-Error "Pause active (tools/PAUSE présent) — aucune lane ne se lance. Supprime le fichier pour reprendre."
    exit 1
}

# --- 2. Lecture de l'issue ---------------------------------------------
#
# Le label `prete` est LA frontière de confiance de ce lanceur : le repo est
# public, n'importe qui peut ouvrir une issue, et son corps est injecté
# verbatim dans le prompt de la lane plus bas. Voir la ligne dédiée dans
# CLAUDE.md (« ne jamais labelliser prete une issue externe sans l'avoir lue
# en entier ») — ce script fait confiance au label, pas au contenu.

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
        [Parameter(Mandatory)] [string]$RepoSlug,
        [Parameter()] [string]$SessionTour = ''
    )

    $canalRapide = if ($SessionTour) {
        @"
## Test du canal rapide (à faire une seule fois, au premier blocage)

Avant de poster ton tout premier commentaire ``BLOQUÉ : ...`` sur cette
Issue, tente d'abord ``SendMessage`` vers la session ``$SessionTour`` avec la
question qui te bloque. C'est un test du canal rapide (interrogation directe
d'une session plutôt qu'un aller-retour par commentaire GitHub) :

- Si ``SendMessage`` aboutit (session trouvée, message envoyé) : note-le dans
  ton commentaire ``BLOQUÉ : ...`` (« canal rapide testé : SendMessage vers
  $SessionTour a fonctionné ») et attends sa réponse avant de continuer si elle
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
    } else {
        @"
## Canal rapide

Pas de session de tour de contrôle fournie à ce lancement (paramètre
``-SessionTour`` absent) — pas de test ``SendMessage``. Poste directement ton
``BLOQUÉ : ...`` sur cette Issue dès qu'un arbitrage manque, qui est le canal
garanti.
"@
    }

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

$canalRapide
"@
}

$promptText = Build-LanePrompt -IssueNumber $issueData.number -Title $issueData.title -Body $issueData.body -RepoSlug $RepoSlug -SessionTour $SessionTour

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
    Write-Output "  git -C `"$RepoRoot`" fetch origin main"
    Write-Output "  herdr worktree create --cwd `"$RepoRoot`" --branch $branch --base origin/main"
    Write-Output "  git -C <repo> config extensions.worktreeConfig true"
    Write-Output "  git -C <worktree> config --worktree credential.helper `"`""
    Write-Output "  git -C <worktree> config --worktree --add credential.helper '!gh auth git-credential'"
    Write-Output '  herdr pane run <pane_id_du_worktree> $env:GH_TOKEN = [Environment]::GetEnvironmentVariable(...GH_TOKEN_LANES...)  (jeton jamais lu/affiché par ce script)'
    Write-Output "  herdr agent start $agentName --kind claude --pane <pane_id_du_worktree> -- --model $Modele --effort $Effort --permission-mode acceptEdits"
    Write-Output "  herdr agent prompt $agentName <prompt-gabarit ci-dessous> --wait --until working --timeout 15000"
    Write-Output ""
    Write-Output "--- Prompt-gabarit ---"
    Write-Output $promptText
    exit 0
}

# --- 6. Exécution réelle ---------------------------------------------------

Write-Output "Fetch d'origin/main (base fraîche de la branche de lane)..."
# `herdr worktree create` ne fait ni fetch ni choix de base par lui-même : sans
# --base explicite, la branche de lane est coupée depuis le HEAD courant du
# dépôt principal — s'il n'est pas sur `main` au moment du lancement, la lane
# hérite des commits de la branche courante en plus des siens. Cause constatée
# de la pollution de la PR #20 (lane-18 lancée depuis la branche du lanceur ->
# 3 fichiers au lieu d'un, cf. revue PR #17). Fetch + --base origin/main
# garantissent une base saine indépendamment de la branche du repo principal.
git -C $RepoRoot fetch origin main
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'git fetch origin main' — base de lane non garantie fraîche, abandon."
    exit 1
}

Write-Output "Création du worktree + pane pour la lane-$Issue..."
$worktreeJson = herdr worktree create --cwd $RepoRoot --branch $branch --base origin/main
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr worktree create' pour la branche $branch."
    exit 1
}
$worktreeData = $worktreeJson | ConvertFrom-Json
$paneId = $worktreeData.result.root_pane.pane_id
$worktreePath = $worktreeData.result.worktree.path

Write-Output "Worktree : $worktreePath"
Write-Output "Pane     : $paneId"

# --- Jeton scopé lanes (D-227) --------------------------------------------
#
# GH_TOKEN_LANES est un jeton fine-grained limité au repo souffleur seul
# (contents/issues/PR en write). Ce script ne le lit ni ne l'affiche jamais :
# la résolution se fait DANS le pane (pas dans ce process-ci), via
# [Environment]::GetEnvironmentVariable(..., 'User') exécuté par le pane
# lui-même — cette API lit le registre en direct, donc elle voit la valeur
# même si le process du pane (ou le serveur Herdr qui l'a fait naître) est
# resté ouvert depuis avant un `setx` (setx ne touche pas les fenêtres déjà
# ouvertes ; lire depuis 'User' contourne ce cache).

Write-Output "Câblage du jeton scopé lanes (GH_TOKEN_LANES -> GH_TOKEN du pane)..."

# extensions.worktreeConfig : permet une config git isolée par worktree —
# sans ça, .git/config est partagé entre tous les worktrees (cf. CLAUDE.md,
# section « Garde de branche main »). Idempotent, sans effet si déjà activé ;
# posé sur le repo principal, jamais sur le compte/la config globale.
git -C $RepoRoot config extensions.worktreeConfig true

# Credential helper LOCAL à ce worktree seul. Une valeur vide de
# credential.helper réinitialise la liste de helpers déjà accumulée par la
# config globale/système (comportement documenté par git) ; on n'ajoute
# ensuite QUE `gh` comme seul helper pour ce worktree — `gh` lit GH_TOKEN
# depuis l'environnement du pane (posé juste après), jamais le compte gh
# global de l'opérateur.
git -C $worktreePath config --worktree credential.helper ""
git -C $worktreePath config --worktree --add credential.helper "!gh auth git-credential"

# GH_TOKEN posé dans l'environnement du PANE, pas dans celui de ce script :
# `herdr agent start` tape la commande de lancement dans ce même pane juste
# après, donc le process claude qu'il démarre hérite de cette variable.
$setTokenCmd = '$env:GH_TOKEN = [System.Environment]::GetEnvironmentVariable(''GH_TOKEN_LANES'',''User'')'
herdr pane run $paneId $setTokenCmd | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de la pose de GH_TOKEN dans le pane $paneId."
    exit 1
}

Write-Output "Démarrage de l'agent claude ($Modele, effort $Effort)..."
# --permission-mode acceptEdits : les éditions de fichiers sont auto-acceptées
# (doc officielle claude) ; les commandes bash restent gouvernées par la
# liste blanche de .claude/settings.json — pas un blanc-seing.
herdr agent start $agentName --kind claude --pane $paneId -- --model $Modele --effort $Effort --permission-mode acceptEdits
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr agent start' pour $agentName sur le pane $paneId."
    exit 1
}

# --until working (pas les défauts idle/done/blocked) : on veut seulement la
# confirmation que le prompt a été accepté et que l'agent s'est mis au
# travail, pas attendre que toute la lane se termine. `agent prompt --wait`
# sans --until suit l'état "settled" (idle/done/blocked) qui, pour une tâche
# agentique autonome, ne survient qu'à la fin du tour complet — donc à la fin
# de la lane. Constaté en lançant réellement ce script (pas seulement en
# -DryRun) sur l'Issue #18 — voir PR #17.
Write-Output "Envoi du prompt-gabarit..."
herdr agent prompt $agentName $promptText --wait --until working --timeout 15000
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de l'envoi du prompt à $agentName (ou l'agent n'est pas passé en 'working' sous 15s)."
    exit 1
}

Write-Output "Lane $agentName lancée sur l'Issue #$Issue (effort $Effort, modèle $Modele) — le script rend la main, la lane continue en arrière-plan dans le pane $paneId."
