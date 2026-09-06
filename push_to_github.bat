@echo off
REM ============================================================
REM  Push Ganak to GitHub as a new 'ganak' branch on your
REM  existing thebalajiindustries-tech/site repo. This does NOT
REM  touch main / your live vidmahitech.com website in any way --
REM  it's a completely separate branch.
REM ============================================================
setlocal
cd /d "%~dp0"

git remote get-url site >nul 2>&1
if errorlevel 1 (
  echo Adding GitHub remote 'site'...
  git remote add site https://github.com/thebalajiindustries-tech/site.git
)

echo.
echo Pushing local 'main' to the 'ganak' branch on GitHub...
echo (If a browser window opens asking you to sign in to GitHub, do that.)
echo.
git push site main:ganak

echo.
echo ============================================================
echo   Copy everything above (especially any red error text)
echo   and send it back.
echo ============================================================
pause
