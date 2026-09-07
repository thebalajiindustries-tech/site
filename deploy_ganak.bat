@echo off
REM ============================================================
REM  Commit the current Ganak working tree and push it to the
REM  'ganak' branch of thebalajiindustries-tech/site, which is
REM  what Render builds app.vidmahitech.com / api.vidmahitech.com
REM  from. Does NOT touch main (your live vidmahitech.com site).
REM ============================================================
setlocal
cd /d "%~dp0"

if exist ".git\index.lock" del /f /q ".git\index.lock" >nul 2>&1

echo.
echo [1/3] Staging changes...
git add -A
if errorlevel 1 goto :fail

echo.
echo These files will be committed:
git diff --cached --name-status

echo.
echo [2/3] Committing...
git commit -F ".git\ganak_deploy_msg.txt"
if errorlevel 1 goto :fail

if not exist "github_token.txt" (
  echo.
  echo ERROR: github_token.txt not found in this folder.
  echo The commit was made, but nothing was pushed.
  goto :fail
)

echo.
echo [3/3] Pushing to the 'ganak' branch...
set /p GH_TOKEN=<github_token.txt
git push https://%GH_TOKEN%@github.com/thebalajiindustries-tech/site.git main:ganak
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo   Pushed. Render will now rebuild both services.
echo   Watch progress at https://dashboard.render.com
echo   First build usually takes 3-6 minutes per service.
echo ============================================================
goto :end

:fail
echo.
echo ############################################################
echo   Something failed above. Copy all of this output and
echo   send it back so it can be sorted out.
echo ############################################################

:end
echo.
pause
