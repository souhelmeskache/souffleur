[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Nom,
    [Parameter(Mandatory = $true)][string]$Fiche,
    [switch]$DryRun,
    [string]$RepoRoot
)

$ErrorActionPreference = 'Stop'

function Fail {
    param([string]$Message)
    Write-Host "[nouvelle-lane] ECHEC : $Message" -ForegroundColor Red
    exit 1
}

if (-not $RepoRoot) { $RepoRoot = Join-Path $env:USERPROFILE 'coderain' }
$resolved = Resolve-Path -LiteralPath $RepoRoot -ErrorAction SilentlyContinue
if (-not $resolved -or -not (Test-Path -LiteralPath (Join-Path $resolved.Path '.git'))) {
    Fail "depot moteur introuvable : $RepoRoot"
}
$RepoRoot = $resolved.Path
$Parent = Split-Path -LiteralPath $RepoRoot
$WorktreePath = Join-Path $Parent "coderain-$Nom"

Write-Host "[nouvelle-lane] lane=$Nom fiche=$Fiche depot=$RepoRoot dryrun=$DryRun" -ForegroundColor Cyan

if ($Nom -eq 'main') { Fail "nom de lane reserve : 'main'" }
if ($Nom -notmatch '^[a-z0-9][a-z0-9-]*$') { Fail "nom de lane invalide : '$Nom' (attendu : kebab-case minuscule)" }

# ---- Controle 1 : la fiche existe et porte une section PERIMETRE D'ECRITURE
if (-not (Test-Path -LiteralPath $Fiche)) { Fail "fiche introuvable : $Fiche" }
$Lines = Get-Content -LiteralPath $Fiche -Encoding UTF8
$patternPerimetre = "P[E\u00C9\u00E9]RIM[\u00C8\u00C8\u00E8\u00E9]TRE\s+D'[\u00C9\u00C9\u00E9]?CRITURE"
$IdxPerimetre = -1
for ($i = 0; $i -lt $Lines.Count; $i++) {
    if ($Lines[$i] -match $patternPerimetre) { $IdxPerimetre = $i; break }
}
if ($IdxPerimetre -lt 0) { Fail "la fiche ne contient aucune section 'PERIMETRE D'ECRITURE' : $Fiche" }

# Extraction des fichiers du perimetre P1 (premier bloc fence apres l'en-tete)
$P1Files = @()
$j = $IdxPerimetre + 1
while ($j -lt $Lines.Count -and $Lines[$j] -notmatch '^```') { $j++ }
$j++
while ($j -lt $Lines.Count -and $Lines[$j] -notmatch '^```') {
    $t = (($Lines[$j].Trim()) -replace '\s*#.*$', '').Trim()
    if ($t -ne '') { $P1Files += ($t -replace '\\', '/') }
    $j++
}
if ($P1Files.Count -eq 0) { Fail "section PERIMETRE D'ECRITURE trouvee mais aucun fichier liste : $Fiche" }
Write-Host ("[nouvelle-lane] controle 1 OK - perimetre P1 ({0} fichiers) : {1}" -f $P1Files.Count, ($P1Files -join ', ')) -ForegroundColor Green

# ---- Controle 2 : main propre
$Status = @(& git -C $RepoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { Fail "git status a echoue sur $RepoRoot" }
if ($Status.Count -gt 0) { Fail "main n'est pas propre (git status --porcelain non vide) - commit ou nettoyage requis avant lane" }
Write-Host "[nouvelle-lane] controle 2 OK - main propre" -ForegroundColor Green

# ---- Controle 3 : collisions branche/chemin + recouvrement de perimetre avec les lanes actives
$null = & git -C $RepoRoot rev-parse --verify --quiet "refs/heads/$Nom"
if ($LASTEXITCODE -eq 0) { Fail "la branche '$Nom' existe deja dans le depot moteur" }
if (Test-Path -LiteralPath $WorktreePath) { Fail "le chemin cible existe deja : $WorktreePath" }

$Overlaps = @()
$WtList = @(& git -C $RepoRoot worktree list --porcelain)
$ActiveBranches = @()
for ($k = 0; $k -lt $WtList.Count; $k++) {
    if ($WtList[$k] -like 'worktree *') {
        $wtPath = $WtList[$k].Substring('worktree '.Length)
        if ($wtPath -ne $RepoRoot) {
            for ($m = $k + 1; $m -lt [Math]::Min($k + 4, $WtList.Count); $m++) {
                if ($WtList[$m] -like 'branch *') {
                    $ActiveBranches += ($WtList[$m].Substring('branch '.Length) -replace '^refs/heads/', '')
                    break
                }
            }
        }
    }
}
foreach ($br in $ActiveBranches) {
    $changed = @(& git -C $RepoRoot diff --name-only "main...$br" | ForEach-Object { $_ -replace '\\', '/' })
    foreach ($f in $P1Files) {
        if ($changed -contains $f) { $Overlaps += "lane '$br' touche deja '$f'" }
    }
}
if ($Overlaps.Count -gt 0) {
    Write-Host "[nouvelle-lane] ATTENTION - recouvrement de perimetre avec lanes actives :" -ForegroundColor Yellow
    $Overlaps | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
    Write-Host "[nouvelle-lane] sequencement obligatoire si meme arbre vise (protocole anti-recidive P1/P2)" -ForegroundColor Yellow
} else {
    Write-Host "[nouvelle-lane] controle 3 OK - aucun recouvrement de perimetre avec les lanes actives" -ForegroundColor Green
}

# ---- Creation du worktree (arbre propre garanti : ni --no-checkout, ni depot nu)
& git -C $RepoRoot worktree add $WorktreePath -b $Nom main
if ($LASTEXITCODE -ne 0) { Fail "git worktree add a echoue" }

# Verification d'isolement P2 : le worktree doit avoir son propre arbre checkoute
$gitFile = Join-Path $WorktreePath '.git'
$entries = @(Get-ChildItem -LiteralPath $WorktreePath -Force)
if (-not (Test-Path -LiteralPath $gitFile) -or $entries.Count -lt 2) {
    & git -C $RepoRoot worktree remove --force $WorktreePath
    & git -C $RepoRoot branch -D $Nom
    Fail "isolement P2 non constate (pas d'arbre propre) - worktree annule et nettoye"
}
$checkedOut = @(Get-ChildItem -LiteralPath $WorktreePath -Recurse -File -ErrorAction SilentlyContinue).Count
Write-Host "[nouvelle-lane] isolement P2 constate - arbre propre : $checkedOut fichiers checkoutes dans $WorktreePath" -ForegroundColor Green

# ---- Recapitulatif une ligne
Write-Host ("[nouvelle-lane] {0} | branche {0} | {1} | fiche : {2}" -f $Nom, $WorktreePath, $Fiche) -ForegroundColor Cyan

if ($DryRun) {
    Write-Host "[nouvelle-lane] DRYRUN - nettoyage : suppression du worktree et de la branche" -ForegroundColor Magenta
    & git -C $RepoRoot worktree remove $WorktreePath
    if ($LASTEXITCODE -ne 0) { & git -C $RepoRoot worktree remove --force $WorktreePath }
    & git -C $RepoRoot branch -D $Nom | Out-Null
    if (Test-Path -LiteralPath $WorktreePath) { Fail "nettoyage incomplet : $WorktreePath existe encore" }
    $null = & git -C $RepoRoot rev-parse --verify --quiet "refs/heads/$Nom"
    if ($LASTEXITCODE -eq 0) { Fail "nettoyage incomplet : la branche '$Nom' existe encore" }
    Write-Host "[nouvelle-lane] DRYRUN - nettoyage verifie : worktree supprime, branche supprimee, main intacte" -ForegroundColor Magenta
    exit 0
}

# ---- Lancement de la session opencode dediee au poste technique
# Le prompt voyage par FICHIER, jamais en positionnel : le premier positionnel d'opencode
# est un CHEMIN DE PROJET ('opencode [project]') - bug du 2026-08-23, corrige comme cote
# reveil (Invoke-WakeMeta de veilleur.ps1). Invocation directe de opencode.cmd : PowerShell
# preferait le shim opencode.ps1, qui habillait la premiere ligne stderr de l'exe en
# NativeCommandError rouge. Console passee en UTF8 AVANT l'appel : fleches et accents
# sinon mojibake (fenetres du 2026-08-23).
#
# I-275 livrable 13 : le prompt porte desormais la cloture P4 — si le terminal se ferme a
# completion, plus personne ne peut retirer le worktree apres coup ; c'est DONC a la lane de
# nettoyer elle-meme, en DERNIER geste.
$Prompt = "Execute $Fiche. Branche et worktree deja en place. Commit avant rapport, hash inclus. " +
          "Puis clôture P4 : git worktree remove de ton worktree + suppression de ta branche depuis le dépôt principal, " +
          "selon README-nouvelle-lane - DERNIER geste avant de rendre la main."
$horodatage = Get-Date -Format 'yyyyMMdd-HHmmss'
$promptFile = Join-Path ([System.IO.Path]::GetTempPath()) ("lane-{0}-{1}.md" -f $Nom, $horodatage)
Set-Content -LiteralPath $promptFile -Value $Prompt -Encoding UTF8
# I-275 livrable 12 (D-192) : PLUS de -NoExit. Sortie 0 de 'opencode.cmd run' => la fenetre
# se FERME seule ; sortie <> 0 => la fenetre RESTE ouverte sur l'erreur visible (seul cas de
# fenetre persistante), jusqu'a Entree, puis propage le code sortie.
$inner = "Set-Location -LiteralPath '$WorktreePath'; " +
         "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; chcp 65001 | Out-Null; " +
         "`$p = Get-Content -LiteralPath '$promptFile' -Raw -Encoding UTF8; " +
         "opencode.cmd run `$p; " +
         "`$codeSortie = `$LASTEXITCODE; " +
         "Remove-Item -LiteralPath '$promptFile' -ErrorAction SilentlyContinue; " +
         "if (`$codeSortie -ne 0) { " +
         "  Write-Host ''; Write-Host ('[nouvelle-lane] lane en echec (code sortie ' + `$codeSortie + ') - fenetre laissee ouverte (D-192 : fermeture a completion seulement)' ) -ForegroundColor Red; " +
         "  Read-Host 'Appuyez sur Entree pour fermer'; exit `$codeSortie } "
$b64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $b64)
Write-Host "[nouvelle-lane] session opencode lancee dans une nouvelle fenetre (worktree : $WorktreePath ; fermeture automatique a completion - D-192)" -ForegroundColor Cyan
exit 0
