@echo off
setlocal enabledelayedexpansion
rem tools/banc/nuit.cmd -- la commande du soir (Issue #260, complement de
rem cadrage) : lancable par double-clic ou depuis un terminal ordinaire
rem (.\tools\banc\nuit.cmd), SANS ouvrir Claude Code. Enchaine, dans une
rem fenetre qui reste ouverte :
rem   git pull --ff-only
rem   -> garde (herdr/claude/gh presents, save presente, rien en vol)
rem   -> tools/banc/nuit.sh -Director sonnet -FinA 06:00 (surchargeable par
rem      les arguments passes a ce .cmd) -- sans -Parties, boucle jusqu'a
rem      l'heure -FinA (decision Souhel #279 : Director sonnet seul, mesure
rem      N1 Haiku 0/2 vs Sonnet 2/2 ; nuit bornee par l'heure plutot qu'un
rem      budget de parties fixe, N1 s'etant arretee a 01:30 pour 06:00) --
rem      rapport-nuit.md ecrit et poste sur l'Issue #201 a la fin de la nuit
rem      quelle que soit la raison d'arret
rem   -> affiche le chemin de nuit.md
rem Voir tools/banc/README.md.

rem --- resolution Git Bash : jamais une dependance au PATH seul -------------
set "GITBASH="
for %%G in (git.exe) do set "GITEXE=%%~$PATH:G"
if defined GITEXE (
  for %%P in ("%GITEXE%") do set "GITBIN=%%~dpP"
  if exist "%GITBIN%..\bin\bash.exe" set "GITBASH=%GITBIN%..\bin\bash.exe"
)
if not defined GITBASH if exist "C:\Program Files\Git\bin\bash.exe" set "GITBASH=C:\Program Files\Git\bin\bash.exe"
if not defined GITBASH (
  echo REFUS : Git Bash introuvable ^(ni via git.exe du PATH, ni C:\Program Files\Git\bin\bash.exe^).
  goto fin_erreur
)

set "REPO_ROOT=%~dp0..\.."
pushd "%REPO_ROOT%" || goto fin_erreur

echo === git pull --ff-only ===
git pull --ff-only
if errorlevel 1 (
  echo REFUS : git pull --ff-only a echoue -- resous d'abord l'etat du depot.
  goto fin_erreur
)

echo.
echo === garde : prerequis + rien en vol ===
set "GARDE_LOG=%TEMP%\verifier-avant-nuit-%RANDOM%.log"
"%GITBASH%" tools/banc/verifier-avant-nuit.sh > "%GARDE_LOG%" 2>&1
set "GARDE_RC=%ERRORLEVEL%"
type "%GARDE_LOG%"
if %GARDE_RC% neq 0 (
  echo REFUS : la garde a echoue -- voir le message ci-dessus.
  del "%GARDE_LOG%" >nul 2>&1
  goto fin_erreur
)
rem #292 -- une lane en vol n'est plus un REFUS mais un AVERTISSEMENT :
rem transmis a nuit.sh (variable d'environnement heritee par le process
rem Git Bash enfant) pour etre repris dans nuit.md.
set "AVERTISSEMENT_PRE_NUIT="
for /f "delims=" %%L in ('findstr /B "AVERTISSEMENT" "%GARDE_LOG%" 2^>nul') do set "AVERTISSEMENT_PRE_NUIT=%%L"
del "%GARDE_LOG%" >nul 2>&1

set "NUIT_ARGS=%*"
if "%NUIT_ARGS%"=="" set "NUIT_ARGS=-Director sonnet -FinA 06:00"

echo.
echo === tools/banc/nuit.sh %NUIT_ARGS% ===
"%GITBASH%" tools/banc/nuit.sh %NUIT_ARGS%
set "NUIT_RC=%ERRORLEVEL%"

for /f "delims=" %%D in ('"%GITBASH%" -c "date +%%Y%%m%%d"') do set "DATEJOUR=%%D"
echo.
echo === nuit terminee (code %NUIT_RC%) ===
echo Journal : %REPO_ROOT%\bench\nuit-%DATEJOUR%\nuit.md
echo Rapport : %REPO_ROOT%\bench\nuit-%DATEJOUR%\rapport-nuit.md (poste sur l'Issue #201 si possible, #276).
echo Le matin : le rapport est deja sur l'Issue #201 -- sinon ouvre un fil et dis "lis la nuit".

popd
pause
exit /b %NUIT_RC%

:fin_erreur
popd 2>nul
pause
exit /b 1
