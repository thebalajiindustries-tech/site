@echo off
REM ============================================================
REM  Push Ganak to GitHub as a new 'ganak' branch on your
REM  existing thebalajiindustries-tech/site repo, authenticating
REM  with the token saved in github_token.txt (never printed).
REM  This does NOT touch main / your live vidmahitech.com site --
REM  it's a completely separate branch.
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist "github_token.txt" (
  echo ERROR: github_token.txt not found in this folder.
  pause & exit /b 1
)

set /p GH_TOKEN=<github_token.txt

echo.
echo Pushing local 'main' to the 'ganak' branch on GitHub...
echo.
git push https://%GH_TOKEN%@github.com/thebalajiindustries-tech/site.git main:ganak

echo.
echo ============================================================
echo   Copy everything above and send it back.
echo   (If it says "done" / shows a new branch, it worked --
echo    you can then delete github_token.txt for safety.)
echo ============================================================
pause
