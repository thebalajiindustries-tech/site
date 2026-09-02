@echo off
REM Loads 23 of Balaji's REAL finance emails into your local warehouse,
REM so you can query Gmail data in Ganak before setting up the full Gmail sync.
setlocal
cd /d "%~dp0"
if not exist "backend\venv\" (
  echo Run start.bat first to set up the backend, then run this.
  pause & exit /b
)
call backend\venv\Scripts\activate.bat
cd backend\connectors
python load_emails_seed.py
echo.
echo Done. Now ask Ganak:  "show payment-received emails over 1 lakh this year"
pause
