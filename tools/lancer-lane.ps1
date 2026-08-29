<#
.SYNOPSIS
    Lanceur minimal d'une lane Herdr sur une Issue GitHub du repo souffleur,
    ou d'une lane de revue adversariale sur une PR (D-251).

.DESCRIPTION
    Pas de démon, pas de superviseur. Une commande = une lane. Le plafond de
    lanes et la pause sont garantis par l'usage (on ne lance pas = pause ; on
    lance une fois = 1 lane). Voir BRIEF-2026-08-28-phase-2-herdr-premiere-lane.md
    (bloc C) dans le vault meta-rpg.

    Deux modes, mutuellement exclusifs :
    - Mode par défaut (-Issue) : lance une lane d'exécution sur une Issue
      labellisée `prete`, dans un worktree neuf.
    - Mode -Revue : lance une lane de revue adversariale FABLE sur une PR
      existante, dans un pane SANS worktree neuf (lecture seule via gh).

.PARAMETER Issue
    Numéro de l'Issue GitHub à lancer en lane (repo souhelmeskache/souffleur).
    Exclusif avec -Revue.

.PARAMETER Revue
    Numéro de la PR GitHub à soumettre à une lane de revue adversariale
    (D-251). Crée un pane SANS worktree neuf (lecture seule via gh), lance
    claude en modèle fable / effort medium — FIGÉS, jamais paramétrables
    dans ce mode (le contrôle qualité ne se fait pas au rabais, D-225). La
    lane lit la spec de l'Issue liée, lit le diff de la PR, et poste un
    verdict en commentaire de PR commençant littéralement par
    `REVUE : APPROUVE` ou `REVUE : REFUS`. Exclusif avec -Issue.

.PARAMETER Modele
    sonnet (défaut) | opus | fable. Jamais haiku (D-225) — refusé explicitement
    si passé. Ignoré (et sans effet) en mode -Revue, où le modèle est figé à
    fable.

.PARAMETER Effort
    low | medium. Par défaut : low si l'issue porte le label `mecanique`,
    medium sinon (D-225 : contrôle qualité = fable medium, exécution = sonnet
    low/medium, orchestration = opus). Ignoré (et sans effet) en mode -Revue,
    où l'effort est figé à medium.

.PARAMETER DryRun
    Affiche ce qui serait lancé (issue/PR, branche ou pane, worktree, commandes
    herdr) sans rien créer ni lancer. Couvre les deux modes.

.PARAMETER SessionTour
    Nom de la session de tour de contrôle à tenter en priorité via SendMessage
    aux jalons BLOQUÉ et TERMINÉ de la lane (ex. meta-rpg-5f) — sonnette
    nominale (D-251) : ce nom change à chaque fil de tour, aucune valeur figée
    ne resterait valide. Vide par défaut : sans ce paramètre la lane saute la
    tentative SendMessage et poste directement ses commentaires sur l'Issue,
    qui reste le canal de secours garanti. Ne s'applique qu'au mode -Issue
    (une lane de revue commente une PR, pas une Issue).

.EXAMPLE
    .\tools\lancer-lane.ps1 14 -DryRun
    .\tools\lancer-lane.ps1 14 -Modele fable -Effort medium
    .\tools\lancer-lane.ps1 14 -SessionTour meta-rpg-5f
    .\tools\lancer-lane.ps1 -Revue 42 -DryRun
    .\tools\lancer-lane.ps1 -Revue 42
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0, ParameterSetName = 'Lane')]
    [int]$Issue,

    [Parameter(Mandatory = $true, ParameterSetName = 'Revue')]
    [int]$Revue,

    [Parameter(ParameterSetName = 'Lane')]
    [ValidateSet('sonnet', 'opus', 'fable')]
    [string]$Modele = 'sonnet',

    [Parameter(ParameterSetName = 'Lane')]
    [ValidateSet('low', 'medium')]
    [string]$Effort,

    [Parameter(ParameterSetName = 'Lane')]
    [string]$SessionTour = '',

    [Parameter()]
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$EstRevue = ($PSCmdlet.ParameterSetName -eq 'Revue')

# Jamais Haiku (D-225) — filet en plus du ValidateSet, au cas où un appelant
# contournerait le paramètre typé via -Modele:$var non validé en amont.
# Sans objet en mode -Revue : le modèle y est figé à fable plus bas, jamais
# lu depuis $Modele.
if (-not $EstRevue -and $Modele -eq 'haiku') {
    Write-Error "Modele 'haiku' exclu par D-225 (contrôle qualité = fable, exécution = sonnet, orchestration = opus)."
    exit 1
}

# --- 0. Résolution gh/herdr (D-228) ---------------------------------------
#
# La session tour (celle qui exécute ce script) n'a pas forcément `gh` et
# `herdr` dans son PATH — constaté en usage réel. Repli sur le chemin complet
# constaté sur cette machine si `Get-Command` échoue ; échec propre (pas de
# `gh`/`herdr` nu qui plante plus loin avec une erreur PowerShell générique)
# si ni le PATH ni le repli ne trouvent la commande.

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

$GhExe = Resolve-ExternalCommand -Name 'gh' -FallbackPaths @('C:\Program Files\GitHub CLI\gh.exe')
$HerdrExe = Resolve-ExternalCommand -Name 'herdr' -FallbackPaths @("$env:LOCALAPPDATA\Programs\Herdr\bin\herdr.exe")

$RepoRoot = (git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
$RepoSlug = 'souhelmeskache/souffleur'
$PauseFlag = Join-Path $RepoRoot 'tools/PAUSE'

# --- 1. Garde-fou pause (garde la moins chère d'abord — avant tout appel réseau) --
# S'applique aux deux modes : une lane de revue reste une lane.

if (Test-Path $PauseFlag) {
    Write-Error "Pause active (tools/PAUSE présent) — aucune lane ne se lance. Supprime le fichier pour reprendre."
    exit 1
}

# ============================================================================
# Mode -Revue : lane de revue adversariale FABLE sur une PR existante (D-251)
# ============================================================================

function Build-RevuePrompt {
    param(
        [Parameter(Mandatory)] [int]$PrNumber,
        [Parameter(Mandatory)] [string]$RepoSlug
    )

    @"
# Revue adversariale — PR #$PrNumber ($RepoSlug)

Tu es une lane de REVUE, pas une lane d'exécution : tu ne modifies aucun
fichier, tu ne crées aucune branche, tu ne commit ni ne push rien. Ton seul
livrable est un verdict posté en commentaire sur la PR #$PrNumber.

## Étapes

1. Identifie l'Issue liée à cette PR (``gh pr view $PrNumber --repo $RepoSlug --json title,body,url,closingIssuesReferences``
   ou, à défaut, le titre/corps de la PR) et lis la spec complète de cette
   Issue (``gh issue view <numero> --repo $RepoSlug``).
2. Lis le diff complet de la PR : ``gh pr diff $PrNumber --repo $RepoSlug``.
3. Attaque le diff contre la spec de l'Issue liée. Cherche activement :
   - **Violations de spec** — ce que l'Issue demandait et que le diff ne fait
     pas, ou fait autrement que demandé.
   - **Étanchéité** — tout matériau de campagne réel ou secret qui se serait
     glissé dans le repo (voir CLAUDE.md du repo : le matériau réel vit dans
     le dépôt privé ``ttrpg-corpus``, jamais ici, même gitignoré).
   - **Zéro-spoiler** — toute fuite d'information de partie (contenu de
     module, résultat de jet, secret de PJ/PNJ) qui ne devrait pas apparaître
     en clair dans du code/test/doc versionné.
   - **Tests creux** — tests qui ne testent rien (assertions triviales, mocks
     qui masquent le comportement réel, absence de cas d'échec).

## Verdict

Poste UN commentaire sur la PR (``gh pr comment $PrNumber --repo $RepoSlug --body "..."``)
dont la première ligne commence **littéralement** par l'une de ces deux
chaînes :

- ``REVUE : APPROUVE`` — suivi de tes points d'attention mineurs s'il y en a.
- ``REVUE : REFUS`` — suivi de la liste précise des points bloquants trouvés
  à l'étape 3.

Puis poste un second commentaire sur la même PR, commençant littéralement par
``TERMINÉ : `` confirmant que le verdict est posté.

## Ce que tu ne fais PAS

- Pas de commit, pas de push, pas de modification de fichier, pas de nouvelle
  branche.
- Pas de merge — le merge reste un geste de la tour.
- Le modèle et l'effort de cette revue sont figés (fable / medium) par le
  lanceur qui t'a démarrée : ne cherche pas à la déléguer à un modèle moins
  cher.
"@
}

if ($EstRevue) {
    $ModeleRevue = 'fable'
    $EffortRevue = 'medium'

    $prJson = & $GhExe pr view $Revue --repo $RepoSlug --json number,title,url,state
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Impossible de lire la PR #$Revue sur $RepoSlug."
        exit 1
    }
    $prData = $prJson | ConvertFrom-Json

    $revuePromptText = Build-RevuePrompt -PrNumber $prData.number -RepoSlug $RepoSlug

    $agentName = "revue-$Revue"
    $tabLabel = "revue-$Revue"

    if ($DryRun) {
        Write-Output "=== DryRun (mode -Revue) — rien n'est lancé ==="
        Write-Output "PR             : #$($prData.number) — $($prData.title)"
        Write-Output "URL            : $($prData.url)"
        Write-Output "État           : $($prData.state)"
        Write-Output "Modele         : $ModeleRevue (figé)"
        Write-Output "Effort         : $EffortRevue (figé)"
        Write-Output "Nom agent      : $agentName"
        Write-Output ""
        Write-Output "Commandes qui seraient exécutées :"
        Write-Output "  (gh résolu : $GhExe)"
        Write-Output "  (herdr résolu : $HerdrExe)"
        Write-Output "  $HerdrExe tab create --cwd `"$RepoRoot`" --label $tabLabel   (SANS worktree neuf, lecture seule via gh)"
        Write-Output "  $HerdrExe pane run <pane_id_du_tab> `$env:GH_TOKEN = [Environment]::GetEnvironmentVariable(...GH_TOKEN_LANES...)  (jeton jamais lu/affiché par ce script)"
        Write-Output "  $HerdrExe agent start $agentName --kind claude --pane <pane_id_du_tab> -- --model $ModeleRevue --effort $EffortRevue --permission-mode acceptEdits"
        Write-Output "  $HerdrExe agent prompt $agentName <prompt-gabarit ci-dessous> --wait --until working --timeout 15000"
        Write-Output ""
        Write-Output "--- Prompt-gabarit (revue) ---"
        Write-Output $revuePromptText
        exit 0
    }

    Write-Output "Création du pane de revue (sans worktree neuf) pour la PR #$Revue..."
    $tabJson = & $HerdrExe tab create --cwd $RepoRoot --label $tabLabel
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Échec de 'herdr tab create' pour la revue de la PR #$Revue."
        exit 1
    }
    $tabData = $tabJson | ConvertFrom-Json
    $paneId = $tabData.result.root_pane.pane_id

    Write-Output "Pane : $paneId"

    # Automode local — même filet que le mode -Issue (voir plus bas) : ce pane
    # tourne dans le checkout courant ($RepoRoot), pas un worktree jetable,
    # mais reste soumis aux mêmes interdits (--no-verify, push forcé) même si
    # la lane de revue n'a en principe aucune raison de committer/pousser.
    $claudeDir = Join-Path $RepoRoot '.claude'
    New-Item -ItemType Directory -Force -Path $claudeDir | Out-Null
    $settingsLocalPath = Join-Path $claudeDir 'settings.local.json'
    $settingsLocal = [ordered]@{
        permissions = [ordered]@{
            allow = @('Bash(*)')
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

    Write-Output "Câblage du jeton scopé lanes (GH_TOKEN_LANES -> GH_TOKEN du pane)..."
    # Même schéma que le mode -Issue (D-227) : le jeton n'est lu que DANS le
    # pane, jamais par ce process. Pas de câblage git credential.helper ici :
    # une lane de revue ne fait ni commit ni push, seulement des appels `gh`
    # qui lisent GH_TOKEN directement depuis l'environnement.
    $setTokenCmd = '$env:GH_TOKEN = [System.Environment]::GetEnvironmentVariable(''GH_TOKEN_LANES'',''User'')'
    & $HerdrExe pane run $paneId $setTokenCmd | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Échec de la pose de GH_TOKEN dans le pane $paneId."
        exit 1
    }

    Write-Output "Démarrage de l'agent de revue ($ModeleRevue, effort $EffortRevue — figés)..."
    & $HerdrExe agent start $agentName --kind claude --pane $paneId -- --model $ModeleRevue --effort $EffortRevue --permission-mode acceptEdits
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Échec de 'herdr agent start' pour $agentName sur le pane $paneId."
        exit 1
    }

    Write-Output "Envoi du prompt-gabarit de revue..."
    & $HerdrExe agent prompt $agentName $revuePromptText --wait --until working --timeout 15000
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Échec de l'envoi du prompt à $agentName (ou l'agent n'est pas passé en 'working' sous 15s)."
        exit 1
    }

    Write-Output "Lane de revue $agentName lancée sur la PR #$Revue (fable, effort medium) — le script rend la main, la revue continue en arrière-plan dans le pane $paneId."
    exit 0
}

# ============================================================================
# Mode -Issue (défaut) : lane d'exécution dans un worktree neuf
# ============================================================================

# --- 2. Lecture de l'issue ---------------------------------------------
#
# Le label `prete` est LA frontière de confiance de ce lanceur : le repo est
# public, n'importe qui peut ouvrir une issue, et son corps est injecté
# verbatim dans le prompt de la lane plus bas. Voir la ligne dédiée dans
# CLAUDE.md (« ne jamais labelliser prete une issue externe sans l'avoir lue
# en entier ») — ce script fait confiance au label, pas au contenu.

$issueJson = & $GhExe issue view $Issue --repo $RepoSlug --json number,title,body,labels,url
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

    $sonnette = if ($SessionTour) {
        @"
## Sonnette nominale (canal SendMessage vers la session tour)

À chacun des jalons **2 (``BLOQUÉ : ...``)** et **3 (``TERMINÉ : ...``)**
ci-dessus — pas seulement au premier blocage — tente D'ABORD ``SendMessage``
vers la session ``$SessionTour`` avec le contenu du commentaire (la question
qui bloque, ou le lien de la PR pour TERMINÉ), PUIS poste dans tous les cas
le commentaire GitHub correspondant sur cette Issue. Le commentaire GitHub
reste le canal garanti, inchangé ; ``SendMessage`` est un canal rapide en
plus, jamais un remplacement — ne saute JAMAIS le commentaire GitHub même si
``SendMessage`` a réussi.

- Si ``SendMessage`` aboutit (session trouvée, message envoyé) : note-le dans
  le commentaire GitHub correspondant (« sonnette : SendMessage vers
  $SessionTour a fonctionné »).
- Si ``SendMessage`` échoue ou n'est pas disponible dans ton environnement :
  note-le aussi (« sonnette : SendMessage indisponible/échoué — repli sur
  commentaire GitHub ») et continue normalement avec le commentaire GitHub.

C'est le régime nominal de cette lane, pas un test ponctuel : répète la
tentative ``SendMessage`` à chacun des deux jalons, pas seulement au premier.
"@
    } else {
        @"
## Sonnette

Pas de session de tour de contrôle fournie à ce lancement (paramètre
``-SessionTour`` absent) — pas de tentative ``SendMessage`` aux jalons. Poste
directement tes commentaires ``BLOQUÉ : ...`` et ``TERMINÉ : ...`` sur cette
Issue, qui reste le canal garanti.
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
- Une fois la PR ouverte : si elle touche autre chose que ``docs/`` seul,
  signale-le explicitement dans ton commentaire ``TERMINÉ : ...`` avec la
  mention ``REVUE REQUISE`` (ex. ``TERMINÉ : <lien PR> — REVUE REQUISE``) —
  une lane de revue adversariale (``lancer-lane.ps1 -Revue <numero-PR>``)
  pourra alors être lancée dessus avant merge.

## Commentaires d'Issue obligatoires (trois jalons, sur l'Issue #$IssueNumber)

Cette lane commente ``gh issue comment $IssueNumber --repo $RepoSlug`` à
chacun des trois moments suivants — aucun n'est optionnel :

1. **Jalon franchi** — dès qu'une étape significative du travail est bouclée
   (ex. diagnostic posé, correctif écrit, tests rejoués), un commentaire court
   décrivant ce qui vient d'être franchi.
2. **« BLOQUÉ : <question> »** — dès qu'un arbitrage manque pour continuer
   (ambiguïté de spec, décision qui dépasse le périmètre de la lane, conflit
   non résoluble seul). Le commentaire commence littéralement par
   ``BLOQUÉ : `` suivi de la question précise qui débloque. Voir sonnette
   ci-dessous : tentative ``SendMessage`` avant ce commentaire si
   ``-SessionTour`` a été fourni au lancement.
3. **« TERMINÉ : <PR> »** — à la toute fin, une fois la PR ouverte (mergée ou
   non). Le commentaire commence littéralement par ``TERMINÉ : `` suivi du
   lien de la PR (et de la mention ``REVUE REQUISE`` si applicable, voir
   règles fixes ci-dessus). Voir sonnette ci-dessous : même tentative
   ``SendMessage`` avant ce commentaire si ``-SessionTour`` a été fourni.

$sonnette
"@
}

$promptText = Build-LanePrompt -IssueNumber $issueData.number -Title $issueData.title -Body $issueData.body -RepoSlug $RepoSlug -SessionTour $SessionTour

$branch = "lane-$Issue"
$agentName = "lane-$Issue"

# --- 5. Dry-run : affiche et sort sans rien créer -------------------------

if ($DryRun) {
    Write-Output "=== DryRun (mode -Issue) — rien n'est lancé ==="
    Write-Output "Issue          : #$($issueData.number) — $($issueData.title)"
    Write-Output "URL            : $($issueData.url)"
    Write-Output "Labels         : $($labelNames -join ', ')"
    Write-Output "Modele         : $Modele"
    Write-Output "Effort         : $Effort"
    Write-Output "Branche        : $branch"
    Write-Output "Nom agent      : $agentName"
    Write-Output ""
    Write-Output "Commandes qui seraient exécutées :"
    Write-Output "  (gh résolu : $GhExe)"
    Write-Output "  (herdr résolu : $HerdrExe)"
    Write-Output "  git -C `"$RepoRoot`" fetch origin main"
    Write-Output "  $HerdrExe worktree create --cwd `"$RepoRoot`" --branch $branch --base origin/main"
    Write-Output "  git -C <repo> config extensions.worktreeConfig true"
    Write-Output "  git -C <worktree> config --worktree credential.helper `"`""
    Write-Output "  git -C <worktree> config --worktree --add credential.helper '!gh auth git-credential'"
    Write-Output "  $HerdrExe pane run <pane_id_du_worktree> `$env:GH_TOKEN = [Environment]::GetEnvironmentVariable(...GH_TOKEN_LANES...)  (jeton jamais lu/affiché par ce script)"
    Write-Output "  $HerdrExe agent start $agentName --kind claude --pane <pane_id_du_worktree> -- --model $Modele --effort $Effort --permission-mode acceptEdits"
    Write-Output "  $HerdrExe agent prompt $agentName <prompt-gabarit ci-dessous> --wait --until working --timeout 15000"
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
$worktreeJson = & $HerdrExe worktree create --cwd $RepoRoot --branch $branch --base origin/main
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr worktree create' pour la branche $branch."
    exit 1
}
$worktreeData = $worktreeJson | ConvertFrom-Json
$paneId = $worktreeData.result.root_pane.pane_id
$worktreePath = $worktreeData.result.worktree.path

Write-Output "Worktree : $worktreePath"
Write-Output "Pane     : $paneId"

# --- Automode local du worktree (Issue #45) -------------------------------
#
# Posé À LA MAIN le 28/08 dans les worktrees des lanes 33-38, réplique par
# lanceur ici pour que chaque nouveau lancement en hérite d'office (l'ancien
# réglage manuel ne vaut que pour les worktrees qui existaient déjà à
# l'époque). Fichier LOCAL au worktree, non versionné (voir .gitignore) :
# autorise Bash(*) pour ne pas bloquer la lane sur une demande de permission
# que personne ne verra, tout en gardant en deny les commandes qui
# contourneraient les gardes déjà en place (garde pré-commit rouge, garde de
# branche main) — --no-verify/-n restent interdits même avec Bash(*) en allow.
$claudeDir = Join-Path $worktreePath '.claude'
New-Item -ItemType Directory -Force -Path $claudeDir | Out-Null
$settingsLocalPath = Join-Path $claudeDir 'settings.local.json'
$settingsLocal = [ordered]@{
    permissions = [ordered]@{
        allow = @('Bash(*)')
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
& $HerdrExe pane run $paneId $setTokenCmd | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de la pose de GH_TOKEN dans le pane $paneId."
    exit 1
}

Write-Output "Démarrage de l'agent claude ($Modele, effort $Effort)..."
# --permission-mode acceptEdits : les éditions de fichiers sont auto-acceptées
# (doc officielle claude) ; les commandes bash restent gouvernées par la
# liste blanche de .claude/settings.json — pas un blanc-seing.
& $HerdrExe agent start $agentName --kind claude --pane $paneId -- --model $Modele --effort $Effort --permission-mode acceptEdits
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
& $HerdrExe agent prompt $agentName $promptText --wait --until working --timeout 15000
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de l'envoi du prompt à $agentName (ou l'agent n'est pas passé en 'working' sous 15s)."
    exit 1
}

Write-Output "Lane $agentName lancée sur l'Issue #$Issue (effort $Effort, modèle $Modele) — le script rend la main, la lane continue en arrière-plan dans le pane $paneId."
