@echo off
setlocal
cd /d "%~dp0"
if exist "venv\Scripts\activate.bat" (
  call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
  call .venv\Scripts\activate.bat
)
python debug_startup.py
echo.
echo ============================================================
echo   Copy EVERYTHING above (including any red error text) and send it back.
echo ============================================================
pause
