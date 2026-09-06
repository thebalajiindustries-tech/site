@echo off
REM ============================================================
REM  Reproduce the "expenses" question failure locally, with a
REM  full Python traceback (the deployed API hides this).
REM ============================================================
setlocal
cd /d "%~dp0"

if exist "venv\Scripts\activate.bat" (
  call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
  call .venv\Scripts\activate.bat
)

python debug_expenses_ask.py

echo.
echo ============================================================
echo   Copy everything above and send it back.
echo ============================================================
pause
