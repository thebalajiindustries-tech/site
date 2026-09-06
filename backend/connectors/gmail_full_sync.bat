@echo off
REM ============================================================
REM  One-time Gmail authorization + full sync (last 12 months)
REM  into the local Postgres warehouse (the `emails` table).
REM  Run this AFTER placing credentials.json in this folder
REM  (see README.md "One-time setup", step 1).
REM
REM  A browser window will open once, asking you to sign in to
REM  thebalajiindustries7333@gmail.com and allow read-only Gmail
REM  access. After that it stores token.json and future runs
REM  (gmail_incremental_sync.bat) won't prompt again.
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist "credentials.json" (
  echo ERROR: credentials.json not found in this folder.
  echo Follow README.md step 1 first: Google Cloud Console -^>
  echo enable Gmail API -^> create OAuth client (Desktop app) -^>
  echo download credentials.json here.
  pause
  exit /b 1
)

if exist "..\venv\Scripts\activate.bat" (
  call ..\venv\Scripts\activate.bat
) else if exist "..\.venv\Scripts\activate.bat" (
  call ..\.venv\Scripts\activate.bat
)

echo Installing/checking Gmail packages...
python -m pip install --quiet --disable-pip-version-check -r requirements-gmail.txt

echo.
echo ============================================================
echo   A browser window should open now for you to sign in.
echo ============================================================
python gmail_sync.py full

echo.
echo ============================================================
echo   Copy everything above and send it back.
echo ============================================================
pause
