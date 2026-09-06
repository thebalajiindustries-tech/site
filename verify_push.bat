@echo off
setlocal
cd /d "%~dp0"
echo Local main commit:
git rev-parse main
echo.
echo Remote 'ganak' branch commit (reading from GitHub)...
if exist "github_token.txt" (
  set /p GH_TOKEN=<github_token.txt
  git ls-remote https://%GH_TOKEN%@github.com/thebalajiindustries-tech/site.git refs/heads/ganak
) else (
  git ls-remote https://github.com/thebalajiindustries-tech/site.git refs/heads/ganak
)
echo.
echo ============================================================
echo   If the two commit hashes above match (first part of each
echo   line), the push worked. Copy this output and send it back.
echo ============================================================
pause
