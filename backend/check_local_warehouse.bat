@echo off
REM ============================================================
REM  Check what tables/rows exist in the LOCAL Postgres warehouse.
REM ============================================================
setlocal
cd /d "%~dp0"

if exist "venv\Scripts\activate.bat" (
  call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
  call .venv\Scripts\activate.bat
)

python check_local_warehouse.py

echo.
echo ============================================================
echo   Copy everything above and send it back.
echo ============================================================
pause
