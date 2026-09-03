@echo off
setlocal enabledelayedexpansion
rem tools/banc/nuit.cmd -- la commande du soir (Issue #260, complement de
rem cadrage) : lancable par double-clic ou depuis un terminal ordinaire
rem (.\tools\banc\nuit.cmd), SANS ouvrir Claude Code. Enchaine, dans une
rem fenetre qui reste ouverte :
rem   git pull --ff-only
rem   -> garde (herdr/claude/gh presents, save presente, rien en vol)
rem   -> tools/banc/nuit.sh -Parties 4 -Director ab -FinA 06:00 (surchargeable
rem      par les arguments passes a ce .cmd) -- s'arrete au plus tard a
rem      l'heure -FinA (Issue #276), rapport-nuit.md ecrit et poste sur
rem      l'Issue #201 a la fin de la nuit quelle que soit la raison d'arret
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
"%GITBASH%" tools/banc/verifier-avant-nuit.sh
if errorlevel 1 (
  echo REFUS : la garde a echoue -- voir le message ci-dessus.
  goto fin_erreur
)

set "NUIT_ARGS=%*"
if "%NUIT_ARGS%"=="" set "NUIT_ARGS=-Parties 4 -Director ab -FinA 06:00"

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
