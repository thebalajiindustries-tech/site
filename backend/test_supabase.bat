@echo off
REM ============================================================
REM  Test the Supabase database connection for Ganak.
REM  Right-click this file -> "Run as administrator" (or just
REM  double-click it) and read the result on screen.
REM ============================================================
setlocal
cd /d "%~dp0"

if exist "venv\Scripts\activate.bat" (
  call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
  call .venv\Scripts\activate.bat
)

echo ============================================================
echo   Testing Supabase connection...
echo ============================================================
echo.

python test_supabase.py

echo.
echo ============================================================
echo   Copy everything above and send it back.
echo ============================================================
pause
