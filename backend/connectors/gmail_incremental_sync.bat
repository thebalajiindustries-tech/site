@echo off
REM ============================================================
REM  Ongoing Gmail sync -- only new mail since the last run.
REM  Requires gmail_full_sync.bat to have been run at least once
REM  (needs token.json to already exist).
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist "token.json" (
  echo ERROR: token.json not found -- run gmail_full_sync.bat first.
  pause
  exit /b 1
)

if exist "..\venv\Scripts\activate.bat" (
  call ..\venv\Scripts\activate.bat
) else if exist "..\.venv\Scripts\activate.bat" (
  call ..\.venv\Scripts\activate.bat
)

python gmail_sync.py incremental

echo.
echo ============================================================
echo   Copy everything above and send it back.
echo ============================================================
pause
