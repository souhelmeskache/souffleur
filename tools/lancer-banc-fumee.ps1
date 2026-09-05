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

.PARAMETER AgentMj
    Nom de l'agent MJ (défaut : "banc-mj"). Ajouté pour le banc de nuit en
    parallèle (#282) : nuit.sh passe un nom suffixé par paire (ex.
    "banc-mj-01") pour que N paires simultanées dans le même worktree
    n'entrent jamais en collision de nom sur `agent start`.

.PARAMETER AgentJoueur
    Nom de l'agent joueur-banc (défaut : "banc-joueur"). Même usage
    qu'-AgentMj (#282).

.PARAMETER WorkspaceLabel
    Label du workspace herdr DÉDIÉ au banc (défaut : "banc"), créé s'il
    n'existe pas encore, réutilisé sinon (Issue #298). Les deux panes
    MJ/joueur se splittent DANS ce workspace, jamais depuis `herdr pane
    current` — un banc ne doit plus jamais dépendre du pane focalisé par
    l'opérateur ou par une lane (`circuit.sh lancer`/`nettoyer`), qui change
    à chaque lancement/nettoyage de lane. nuit.sh passe "banc-<date du
    jour>" pour qu'une nuit vive dans son propre workspace, distinct d'un
    smoke test manuel (label "banc" par défaut).

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

    # Noms d'agent (Issue #282, banc de nuit en PARALLÈLE) : défauts
    # inchangés ("banc-mj"/"banc-joueur", comportement historique) — nuit.sh
    # passe des noms suffixés par paire (ex. "banc-mj-01") pour que N paires
    # simultanées dans le même worktree n'entrent jamais en collision de nom
    # sur `agent start` (#271, déjà vécu en séquentiel — bataille de panes
    # constatée le 02/09 en parallèle manuel). Rester sous 32 caractères
    # (limite herdr, correctif scratchpad #196).
    [string]$AgentMj = 'banc-mj',
    [string]$AgentJoueur = 'banc-joueur',

    # Label du workspace herdr dédié au banc (Issue #298) : créé s'il
    # n'existe pas, réutilisé sinon — jamais `herdr pane current`, qui
    # dépend du focus de l'opérateur/des lanes (#298, craquement 05/09 :
    # panes du banc ouverts dans le workspace d'une lane, fermé par
    # `circuit.sh nettoyer` en cours de partie).
    [string]$WorkspaceLabel = 'banc',

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

# --- 0bis. Envoi du prompt sans interprétation shell (I-385, #263) ---------
#
# Les deux gabarits (tools/prompts/banc-mj.md/banc-joueur.md) sont envoyés en
# UN SEUL argument à `herdr agent prompt` via `&` natif de PowerShell 5.1
# (Windows PowerShell, pas de $PSNativeCommandArgumentPassing) : celui-ci
# réinterprète les guillemets doubles internes avant de construire la ligne
# de commande Win32 — un nombre IMPAIR de guillemets dans le gabarit éclate
# l'argument en plusieurs argv (herdr lit un mot du gabarit comme option,
# `unknown option`). Constaté sur la nuit N0 du 02/09 (#263) : #258 a ajouté
# au gabarit MJ un exemple JSON avec des guillemets doubles, la nuit a joué
# 0 tour, 4 parties/4 craquées au lancement.
#
# Même contournement que lancer-lane.ps1 (I-385, mêmes fonctions reprises à
# l'identique) : construire nous-mêmes la ligne de commande avec
# l'échappement Win32 standard (CommandLineToArgvW / argv C), puis lancer le
# process via .NET (ProcessStartInfo.Arguments — pas .ArgumentList, absent
# du .NET Framework de Windows PowerShell 5.1) en contournant l'invocation
# native `&`. $script:LASTEXITCODE est reposé en sortie pour que les
# `if ($LASTEXITCODE -ne 0)` déjà en place restent inchangés.

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

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory)] [string]$FilePath,
        [Parameter(Mandatory)] [string[]]$Arguments
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = ($Arguments | ForEach-Object { ConvertTo-Win32Arg $_ }) -join ' '
    $psi.UseShellExecute = $false
    $p = [System.Diagnostics.Process]::Start($psi)
    $p.WaitForExit()
    $script:LASTEXITCODE = $p.ExitCode
}

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
# $AgentMj/$AgentJoueur viennent des paramètres ci-dessus (#282) — défauts
# "banc-mj"/"banc-joueur" inchangés quand ce script est appelé sans eux.

# --- 2bis. Refus nommé si un agent du banc est déjà en vol (#271) ----------
#
# nuit N0 (02/09) : un `banc-joueur` survivant d'une partie précédente a fait
# échouer `herdr agent start` pour la partie suivante avec un « échec de
# herdr agent start » muet -- aucune indication que la cause est une
# collision de nom. Vérifié ici, AVANT tout `pane split`/`agent start` (y
# compris en -DryRun, pour que le refus soit testable sans rien lancer).
function Verifie-AgentsNonEnVol {
    param(
        [Parameter(Mandatory)] [string]$HerdrExe,
        [Parameter(Mandatory)] [string[]]$Noms
    )
    $listeJson = & $HerdrExe agent list 2>$null
    if (-not $listeJson) { return }
    try {
        $listeData = $listeJson | ConvertFrom-Json
    } catch {
        return
    }
    $agents = $listeData.result.agents
    if (-not $agents) { return }
    foreach ($nom in $Noms) {
        $existant = $agents | Where-Object { $_.name -eq $nom } | Select-Object -First 1
        if ($existant) {
            Write-Error "REFUS : agent $nom déjà en vol sur le pane $($existant.pane_id) — ferme-le avant de relancer (#271)."
            exit 1
        }
    }
}
Verifie-AgentsNonEnVol -HerdrExe $HerdrExe -Noms @($AgentMj, $AgentJoueur)

# --- 2ter. Workspace herdr DÉDIÉ au banc (#298) -----------------------------
#
# Le banc ne doit plus jamais dépendre de `herdr pane current` : le pane
# focalisé appartient à l'opérateur et aux lanes (`circuit.sh lancer` crée et
# focalise un nouveau workspace à chaque lancement, `nettoyer` en ferme un) —
# craquement du 05/09 (#298) : les panes MJ/joueur d'une partie ont été
# ouverts dans le workspace d'une lane focalisée juste avant, puis fermés
# avec elle par `circuit.sh nettoyer`, en pleine partie. Les deux panes de ce
# script vivent désormais dans un workspace herdr identifié par SON PROPRE
# label ($WorkspaceLabel), créé s'il n'existe pas encore, réutilisé sinon —
# et `--no-focus` partout (création + splits) : ce script ne change JAMAIS
# le focus de l'opérateur.

# workspace_id du label passé en $Label, $null si absent.
function Get-WorkspaceIdParLabel {
    param(
        [Parameter(Mandatory)] [string]$HerdrExe,
        [Parameter(Mandatory)] [string]$Label
    )
    $json = & $HerdrExe workspace list 2>$null
    if (-not $json) { return $null }
    try { $data = $json | ConvertFrom-Json } catch { return $null }
    $ws = $data.result.workspaces | Where-Object { $_.label -eq $Label } | Select-Object -First 1
    if ($ws) { return $ws.workspace_id }
    return $null
}

# pane_id du premier pane trouvé dans le workspace $WorkspaceId (pane
# "pivot" depuis lequel splitter) — $null si le workspace n'a aucun pane
# (état incohérent, ne devrait jamais arriver : un workspace herdr en a
# toujours au moins un).
function Get-PanePivotWorkspace {
    param(
        [Parameter(Mandatory)] [string]$HerdrExe,
        [Parameter(Mandatory)] [string]$WorkspaceId
    )
    $json = & $HerdrExe pane list --workspace $WorkspaceId 2>$null
    if (-not $json) { return $null }
    try { $data = $json | ConvertFrom-Json } catch { return $null }
    $pane = $data.result.panes | Select-Object -First 1
    if ($pane) { return $pane.pane_id }
    return $null
}

# Trouve (par label) ou crée le workspace dédié au banc, jamais en changeant
# le focus de l'opérateur. Rend un objet {WorkspaceId, PaneAncre, Cree}.
#
# Verrou (bench\.verrou-workspace-banc\<label>, mkdir atomique, #298, même
# discipline que ARRET_DIR dans nuit.sh) : le banc de nuit EN PARALLÈLE
# (-Paires > 1, #282) lance PLUSIEURS instances de ce script en même temps,
# toutes visant le MÊME label — sans ce verrou, deux instances qui listent
# les workspaces au même instant verraient toutes les deux "absent" et
# créeraient CHACUNE un workspace, doublon qui casse la réutilisation ET le
# nettoyage de fin de nuit (un seul label attendu).
function Assure-WorkspaceBanc {
    param(
        [Parameter(Mandatory)] [string]$HerdrExe,
        [Parameter(Mandatory)] [string]$Label,
        [Parameter(Mandatory)] [string]$RepoRoot
    )
    $verrouDir = Join-Path $RepoRoot "bench\.verrou-workspace-banc\$Label"
    $acquis = $false
    for ($i = 0; $i -lt 150; $i++) {
        try {
            New-Item -ItemType Directory -Path $verrouDir -ErrorAction Stop | Out-Null
            $acquis = $true
            break
        } catch {
            Start-Sleep -Milliseconds 200
        }
    }
    if (-not $acquis) {
        Write-Error "REFUS : verrou de création du workspace banc ($verrouDir) non acquis après 30s -- une autre instance le tient trop longtemps."
        exit 1
    }
    try {
        $wsId = Get-WorkspaceIdParLabel -HerdrExe $HerdrExe -Label $Label
        if ($wsId) {
            $paneAncre = Get-PanePivotWorkspace -HerdrExe $HerdrExe -WorkspaceId $wsId
            if (-not $paneAncre) {
                Write-Error "workspace banc '$Label' ($wsId) trouvé mais sans aucun pane -- état incohérent."
                exit 1
            }
            return [PSCustomObject]@{ WorkspaceId = $wsId; PaneAncre = $paneAncre; Cree = $false }
        }
        $json = & $HerdrExe workspace create --cwd $RepoRoot --label $Label --no-focus
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Échec de 'herdr workspace create' pour le workspace banc '$Label'."
            exit 1
        }
        $data = $json | ConvertFrom-Json
        $wsIdCree = $data.result.workspace.workspace_id
        $paneAncreCree = $data.result.root_pane.pane_id
        if (-not $wsIdCree -or -not $paneAncreCree) {
            Write-Error "workspace banc créé mais illisible (label '$Label')."
            exit 1
        }
        return [PSCustomObject]@{ WorkspaceId = $wsIdCree; PaneAncre = $paneAncreCree; Cree = $true }
    } finally {
        Remove-Item -Path $verrouDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

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
    Write-Output "Workspace banc : label '$WorkspaceLabel' (créé si absent, réutilisé sinon, #298 -- jamais 'pane current')"
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
    Write-Output "  `$workspaceBanc = trouve (herdr workspace list) ou crée (herdr workspace create --cwd `"$RepoRoot`" --label '$WorkspaceLabel' --no-focus) -- focus opérateur inchangé"
    $envArgAffiche = if ($SavesDirOverride) { " --env `"SAVES_DIR=$SavesDirOverride`"" } else { "" }
    Write-Output "  `$paneMj = $HerdrExe pane split <pane-ancre-workspace-banc> --direction right --cwd `"$RepoRoot`" --no-focus$envArgAffiche"
    Write-Output "  `$paneJoueur = $HerdrExe pane split <paneMj> --direction down --cwd `"$RepoRoot`" --no-focus$envArgAffiche"
    Write-Output "  (automode : pose ou complète .claude\settings.local.json dans $RepoRoot — Issue #210, garanti #267)"
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

Write-Output "Résolution du workspace banc (label '$WorkspaceLabel', #298)..."
$workspaceBanc = Assure-WorkspaceBanc -HerdrExe $HerdrExe -Label $WorkspaceLabel -RepoRoot $RepoRoot
if ($workspaceBanc.Cree) {
    Write-Output "Workspace banc  : $($workspaceBanc.WorkspaceId) (créé, label '$WorkspaceLabel')"
} else {
    Write-Output "Workspace banc  : $($workspaceBanc.WorkspaceId) (réutilisé, label '$WorkspaceLabel')"
}

Write-Output "Ouverture des deux panes (MJ + joueur-banc) dans ce workspace -- focus opérateur inchangé..."

# Correctif scratchpad (issue #196) : le MJ prend un pane NEUF (split), jamais
# le pane courant — et le chemin JSON est result.pane.pane_id.
#
# $SavesDirOverride (#260) : --env SAVES_DIR=... posé sur les DEUX panes, pas
# seulement au niveau du process courant — la résolution SAVES_DIR
# (coderain/config.py::_resolve_dir) est dynamique par process, chaque agent
# lit son propre environnement de pane.
#
# --no-focus (#298) : ni la création du workspace ni ces deux splits ne
# doivent jamais changer le focus de l'opérateur.
$envSplitArgs = @()
if ($SavesDirOverride) { $envSplitArgs = @('--env', "SAVES_DIR=$SavesDirOverride") }

$paneMjJson = & $HerdrExe pane split $workspaceBanc.PaneAncre --direction right --cwd $RepoRoot --no-focus @envSplitArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr pane split' pour ouvrir le pane MJ (workspace banc $($workspaceBanc.WorkspaceId))."
    exit 1
}
$paneMjData = $paneMjJson | ConvertFrom-Json
$paneMjId = $paneMjData.result.pane.pane_id
if (-not $paneMjId) { $paneMjId = $paneMjData.result.pane_id }
if (-not $paneMjId) { Write-Error "pane MJ illisible"; exit 1 }

$paneJoueurJson = & $HerdrExe pane split $paneMjId --direction down --cwd $RepoRoot --no-focus @envSplitArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr pane split' pour ouvrir le pane joueur-banc (workspace banc $($workspaceBanc.WorkspaceId))."
    exit 1
}
$paneJoueurData = $paneJoueurJson | ConvertFrom-Json
$paneJoueurId = $paneJoueurData.result.pane.pane_id
if (-not $paneJoueurId) { $paneJoueurId = $paneJoueurData.result.pane_id }
if (-not $paneJoueurId) { Write-Error "pane joueur-banc illisible"; exit 1 }

Write-Output "Pane MJ         : $paneMjId"
Write-Output "Pane joueur-banc: $paneJoueurId"

# --- Automode local (Issue #210, garanti #267), même mécanisme que
# lancer-lane.ps1 -------------------------------------------------------
#
# lancer-lane.ps1 (lignes ~608-624) pose ce fichier dans un worktree NEUF à
# chaque lane ; ce script tourne, lui, dans le worktree courant, relancé
# plusieurs fois d'un run à l'autre (reprise). Fichier absent : création
# complète, comme avant. Fichier déjà présent : Assure-ListeBlancheBanc
# (tools\banc\liste-blanche.ps1) COMPLÈTE la liste blanche (entrées `allow`/
# `deny` du gabarit manquantes) au lieu de se contenter de constater sa
# présence — #267, nuit N0 du 02/09 : un settings.local.json préexistant
# plus étroit (cinq outils moteur seulement, pas de Bash) avait laissé les
# deux agents redemander des autorisations toute la nuit. Rien de ce que
# l'opérateur y a mis n'est retiré ; un JSON invalide REFUSE plutôt que
# d'écraser.
. (Join-Path $RepoRoot 'tools\banc\liste-blanche.ps1')
# Assure-ModeAutoCompatibleAvecModele (#276) : refus nommé Haiku + auto,
# partagée avec tools/lancer-lane.ps1 — sans effet ici (mode acceptEdits
# hardcodé ci-dessous), gardée pour la même discipline dans les deux
# lanceurs d'agents.
. (Join-Path $RepoRoot 'tools\refus-haiku-auto.ps1')
$claudeDir = Join-Path $RepoRoot '.claude'
$settingsLocalPath = Join-Path $claudeDir 'settings.local.json'
$resultatListeBlanche = Assure-ListeBlancheBanc -SettingsLocalPath $settingsLocalPath
Write-Output $resultatListeBlanche.Message
if ($resultatListeBlanche.Status -eq 'refus') {
    exit 1
}

Assure-ModeAutoCompatibleAvecModele -Modele $ModeleMj -PermissionMode 'acceptEdits'
Write-Output "Démarrage de l'agent MJ ($AgentMj, $ModeleMj, effort medium)..."
& $HerdrExe agent start $AgentMj --kind claude --pane $paneMjId -- --model $ModeleMj --effort medium --permission-mode acceptEdits
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr agent start' pour $AgentMj sur le pane $paneMjId."
    exit 1
}

Assure-ModeAutoCompatibleAvecModele -Modele $ModeleJoueur -PermissionMode 'acceptEdits'
Write-Output "Démarrage de l'agent joueur-banc ($AgentJoueur, $ModeleJoueur, effort low)..."
& $HerdrExe agent start $AgentJoueur --kind claude --pane $paneJoueurId -- --model $ModeleJoueur --effort low --permission-mode acceptEdits
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de 'herdr agent start' pour $AgentJoueur sur le pane $paneJoueurId."
    exit 1
}

Write-Output "Envoi du prompt-gabarit MJ..."
# Invoke-NativeCommand (I-385, #263) : $PromptMj porte le gabarit rendu,
# potentiellement truffé de guillemets doubles (exemples JSON) — voir la
# section 0bis plus haut.
Invoke-NativeCommand -FilePath $HerdrExe -Arguments @(
    'agent', 'prompt', $AgentMj, $PromptMj,
    '--wait', '--until', 'working', '--timeout', '15000'
)
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de l'envoi du prompt à $AgentMj (ou l'agent n'est pas passé en 'working' sous 15s)."
    exit 1
}

Write-Output "Envoi du prompt-gabarit joueur-banc..."
Invoke-NativeCommand -FilePath $HerdrExe -Arguments @(
    'agent', 'prompt', $AgentJoueur, $PromptJoueur,
    '--wait', '--until', 'working', '--timeout', '15000'
)
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec de l'envoi du prompt à $AgentJoueur (ou l'agent n'est pas passé en 'working' sous 15s)."
    exit 1
}

Write-Output "Banc de fumée lancé (save $Save, $Tours tours max, session tour $SessionTour) — le script rend la main, le tempo go/pause est tenu par la session tour dans les panes $paneMjId (MJ) et $paneJoueurId (joueur-banc), workspace banc $($workspaceBanc.WorkspaceId) (label '$WorkspaceLabel', #298)."
Write-Output "Journal : $JournalDir"
