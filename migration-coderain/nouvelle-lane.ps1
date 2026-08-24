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
# Dossier du POSTE (la ou vivent state/journal/preuves du veilleur) : les deux scripts sont
# deployes cote a cote ; le dossier du present script EST le poste (I-287 : preuves de session
# lane et marques d'echec externe ecrites LA, la ou le veilleur les lit au tour suivant).
$PostRoot = [System.IO.Path]::GetDirectoryName($PSCommandPath)

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

# ---- I-281 : recu de livraison VERIFIE - seuls les chemins ABSOLUS du P1 sont testables
# (une ligne de prose du type « miroir ... » ne designe aucun fichier et est ignoree).
# La liste sert APRES le run : un exit 0 d'opencode sans livrable sur disque n'est pas une
# completion (lane disparue sans trace, I-281) - voir le controle dans la fenetre lancee.
# ---- I-285 : controle 1b DURCI - un P1 sans AUCUN chemin absolu testable est REFUSE a
# l'armement (plus un simple avertissement vert). Un recu de livraison qui ne teste rien
# n'est pas un recu : lane audit-dnd5e-engine du 24/08, fiche a P1 relatif => recu
# « non verifiable » annonce en VERT, lane auto-nettoiee AVANT depot, exit 0 « honnete ».
# Toute fiche doit desormais designer ses livrables P1 par des chemins ABSOLUS.
$P1Absolus = @($P1Files | Where-Object { [System.IO.Path]::IsPathRooted($_) })
if ($P1Absolus.Count -eq 0) {
    Fail ("controle 1b (I-285) : aucun chemin ABSOLU testable dans le perimetre P1 ({0} entree(s)) - recu de livraison impossible, fiche refusee a l'armement. Corriger la fiche : chaque livrable P1 doit porter son chemin complet." -f $P1Files.Count)
}
$P1Lit = (@($P1Absolus | ForEach-Object { "'" + ($_ -replace "'", "''") + "'" }) -join ', ')
Write-Host ("[nouvelle-lane] controle 1b OK - recu de livraison (I-281/I-285), livrables verifiables : {0}" -f ($P1Absolus -join ', ')) -ForegroundColor Green

# ---- Controle 2 : main propre
$Status = @(& git -C $RepoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { Fail "git status a echoue sur $RepoRoot" }
if ($Status.Count -gt 0) { Fail "main n'est pas propre (git status --porcelain non vide) - commit ou nettoyage requis avant lane" }
Write-Host "[nouvelle-lane] controle 2 OK - main propre" -ForegroundColor Green

# ---- Controle 3 : collisions branche/chemin + recouvrement de perimetre avec les lanes actives
# ---- I-287 : un RESIDU de lane morte (lane tuee reseau en cours, auto-nettoyage P4 jamais
# passe) ne doit plus bloquer la relance. Avant tout Fail, le residu est DIAGNOSTIQUE :
# nettoyage automatique JOURNALISE (worktree remove + suppression de branche) si et seulement si
#   (a) le chemin cible est un worktree ENREGISTRE de CE depot (jamais un repertoire etranger),
#   (b) l'arbre est PROPRE : status --porcelain vide, donc ni modifications non commitees ni
#       fichiers non suivis (exactement le critere que git worktree remove exige lui-meme),
#   (c) la branche est a main OU fusionnee dedans (merge-base --is-ancestor couvre les deux ;
#       sans branche nommee, le HEAD reellement checkout du residu fait foi).
# Sinon Fail CONSERVE avec la cause NOMMEE : on ne supprime JAMAIS du travail non commite ni
# du travail non integre. Cas reel I-287 du 24/08 : inventaire-saves morte reseau a 08:50,
# relance 08:56 code 1 (« chemin existe deja »), compteur d'echecs 1/2, ban evite de justesse.
$brancheExiste = $false
$null = & git -C $RepoRoot rev-parse --verify --quiet "refs/heads/$Nom"
if ($LASTEXITCODE -eq 0) { $brancheExiste = $true }
$cheminExiste = Test-Path -LiteralPath $WorktreePath
if ($brancheExiste -or $cheminExiste) {
    # Diagnostic sous garde : toute surprise git (worktree corrompu, depot illisible...)
    # degrade vers « non nettoyable » - Fail conserve, jamais de suppression a l'aveugle.
    try {
        $enregistre = $false
        foreach ($l in @(& git -C $RepoRoot worktree list --porcelain)) {
            if ($l -like 'worktree *' -and (($l.Substring('worktree '.Length) -replace '/', '\') -ieq ($WorktreePath -replace '/', '\'))) { $enregistre = $true }
        }
        $propre = $false
        if ($enregistre) {
            $porcelaine = @(& git -C $WorktreePath status --porcelain 2>$null | Where-Object { $_ -ne '' })
            if ($LASTEXITCODE -eq 0 -and $porcelaine.Count -eq 0) { $propre = $true }
        }
        $referenceFusion = $null
        if ($brancheExiste) {
            $referenceFusion = "refs/heads/$Nom"
        } elseif ($enregistre) {
            $headResidu = (& git -C $WorktreePath rev-parse HEAD 2>$null)
            if ($LASTEXITCODE -eq 0 -and $headResidu) { $referenceFusion = "$headResidu".Trim() }
        }
        $fusionne = $false
        if ($referenceFusion) {
            & git -C $RepoRoot merge-base --is-ancestor $referenceFusion main 2>$null
            if ($LASTEXITCODE -eq 0) { $fusionne = $true }
        }
    } catch {
        Write-Host "[nouvelle-lane] diagnostic du residu impossible : $($_.Exception.Message)" -ForegroundColor Yellow
        $enregistre = $false; $propre = $false; $fusionne = $false
    }
    if ($fusionne -and -not $cheminExiste) {
        # Residu BRANCHE SEULE (le worktree a deja disparu, ou n'a jamais ete cree) : la
        # fusion suffit, il n'y a aucun arbre a juger. Suppression de branche seulement.
        Write-Host "[nouvelle-lane] [INFO] I-287 residu de lane morte detecte : branche '$Nom' fusionnee dans main (plus de worktree) - nettoyage automatique au lieu de Fail" -ForegroundColor Yellow
        & git -C $RepoRoot branch -d $Nom
        if ($LASTEXITCODE -ne 0) { Fail "I-287 : git a refuse la suppression (-d) de la branche '$Nom' (encore checkout ailleurs ?) - intervention requise" }
        Write-Host "[nouvelle-lane] [INFO] I-287 branch -d OK : '$Nom'" -ForegroundColor Yellow
    } elseif ($enregistre -and $propre -and $fusionne) {
        # Residu COMPLET : worktree enregistre + arbre propre + branche/HEAD fusionne.
        Write-Host "[nouvelle-lane] [INFO] I-287 residu de lane morte detecte : worktree '$WorktreePath' propre + $(if ($brancheExiste) { "branche '$Nom' a main ou fusionnee" } else { "HEAD fusionne" }) dans main - nettoyage automatique au lieu de Fail" -ForegroundColor Yellow
        & git -C $RepoRoot worktree remove $WorktreePath
        if ($LASTEXITCODE -ne 0) { Fail "I-287 : git a refuse le worktree remove du residu propre - intervention requise sur $WorktreePath" }
        Write-Host "[nouvelle-lane] [INFO] I-287 worktree remove OK : $WorktreePath" -ForegroundColor Yellow
        if ($brancheExiste) {
            # -d et non -D : la suppression reste sous la securite fusion de git.
            & git -C $RepoRoot branch -d $Nom
            if ($LASTEXITCODE -ne 0) { Fail "I-287 : git a refuse la suppression (-d) de la branche '$Nom' - intervention requise" }
            Write-Host "[nouvelle-lane] [INFO] I-287 branch -d OK : '$Nom'" -ForegroundColor Yellow
        }
        if (Test-Path -LiteralPath $WorktreePath) { Fail "I-287 : nettoyage incomplet, le chemin existe encore : $WorktreePath" }
    } else {
        $cause = if (-not $enregistre -and $cheminExiste) { "le chemin existe mais n'est pas un worktree enregistre de ce depot - contenu inconnu, jamais supprime" }
                 elseif ($enregistre -and -not $propre) { "arbre NON propre (modifications non commitees ou fichiers non suivis) - jamais supprimer du travail non commite" }
                 elseif (-not $fusionne) { "branche/HEAD NON fusionne dans main - jamais supprimer du travail non integre" }
                 else { "etat du residu non reconnu - intervention requise" }
        Fail ("residu existant non nettoyable pour la lane '{0}' : {1}" -f $Nom, $cause)
    }
}

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
# I-287 livrable 2 : la sortie du run est TEE'ee vers une preuve sur disque (meme ecole que
# les preuves de session meta). Si le run meurt (codeSortie <> 0) et que la preuve porte
# finish_reason: network_error - mort FOURNISSEUR, ni faute de la fiche ni faute de la lane -
# une MARQUE echec-externe-*.flag est posee dans le poste. Le veilleur la lit au tour
# suivant : echec non compte dans echecsParFiche, journal « [INFO] echec externe, compteur
# intact ». Sans elle, la mort reseau du run precedent faisait porter a la RELANCE (et donc
# a la fiche) la responsabilite d'une panne exterieure : c'est exactement I-287.
$proofLog   = Join-Path $PostRoot ("preuve-session-lane-{0}-{1}.log" -f $Nom, $horodatage)
$marqueExt  = Join-Path $PostRoot ("echec-externe-{0}-{1}.flag" -f $Nom, $horodatage)
$FicheLit   = $Fiche -replace "'", "''"
Set-Content -LiteralPath $promptFile -Value $Prompt -Encoding UTF8
# I-275 livrable 12 (D-192) : PLUS de -NoExit. Sortie 0 de 'opencode.cmd run' => la fenetre
# se FERME seule ; sortie <> 0 => la fenetre RESTE ouverte sur l'erreur visible (seul cas de
# fenetre persistante), jusqu'a Entree, puis propage le code sortie.
#
# I-281 recu de livraison : APRES le run, les chemins absolus du P1 ($P1Lit) sont testes sur
# disque. Un exit 0 sans livrable force le code sortie a 3 et nomme chaque fichier absent -
# la fenetre reste alors ouverte sur l'erreur visible (meme regime D-192).
$inner = "Set-Location -LiteralPath '$WorktreePath'; " +
         "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; chcp 65001 | Out-Null; " +
         "`$p = Get-Content -LiteralPath '$promptFile' -Raw -Encoding UTF8; " +
         "opencode.cmd run `$p 2>&1 | Tee-Object -FilePath '$proofLog' -Append; " +
         "`$codeSortie = `$LASTEXITCODE; " +
         "`$p1abs = @($P1Lit); " +
         "`$manquants = @(foreach (`$f in `$p1abs) { if (-not (Test-Path -LiteralPath `$f)) { `$f } }); " +
         "if (`$manquants.Count -gt 0) { " +
         "  Write-Host ''; " +
         "  Write-Host ('[nouvelle-lane] RECU DE LIVRAISON REFUSE (I-281) : sortie 0 d''opencode sans livrable - ' + `$manquants.Count + ' fichier(s) du perimetre P1 absent(s) du disque :') -ForegroundColor Red; " +
         "  foreach (`$f in `$manquants) { Write-Host ('  - ABSENT : ' + `$f) -ForegroundColor Red } " +
         "  Write-Host '[nouvelle-lane] un exit 0 sans livrable n''est pas une completion (I-281) - code sortie force a 3.' -ForegroundColor Red; " +
         "  `$codeSortie = 3 } " +
         "`$sortiePreuve = Get-Content -LiteralPath '$proofLog' -Raw -ErrorAction SilentlyContinue; " +
         "if ((`$codeSortie -ne 0) -and (`$sortiePreuve -match 'finish[_-]?[Rr]eason.{0,24}network[_-]?error')) { " +
         "  Set-Content -LiteralPath '$marqueExt' -Value ('fiche=$FicheLit|horodatage=' + (Get-Date -Format o) + '|preuve=$proofLog') -Encoding UTF8; " +
         "  Write-Host '[nouvelle-lane] [INFO] echec externe (finish_reason: network_error, fournisseur) consigne au veilleur : ce mort n''est pas une faute de fiche (I-287)' -ForegroundColor Yellow } " +
         "Remove-Item -LiteralPath '$promptFile' -ErrorAction SilentlyContinue; " +
         "if (`$codeSortie -ne 0) { " +
         "  Write-Host ''; Write-Host ('[nouvelle-lane] lane en echec (code sortie ' + `$codeSortie + ') - fenetre laissee ouverte (D-192 : fermeture a completion seulement)' ) -ForegroundColor Red; " +
         "  Read-Host 'Appuyez sur Entree pour fermer'; exit `$codeSortie } "
# I-287 livrable 2 : la fenetre TEE la sortie du run vers la preuve, et si le run meurt sur
# finish_reason: network_error (mort FOURNISSEUR), pose une marque echec-externe-*.flag dans
# le poste - posee SEULEMENT si le run a echoue (un run survecu a une coupure ne marque rien).
$b64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $b64)
Write-Host "[nouvelle-lane] session opencode lancee dans une nouvelle fenetre (worktree : $WorktreePath ; fermeture automatique a completion - D-192)" -ForegroundColor Cyan
exit 0
