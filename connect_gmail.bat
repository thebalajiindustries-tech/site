@echo off
REM Loads a year of finance emails into Ganak's warehouse ('emails' table).
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if exist "backend\venv\Scripts\activate.bat" call backend\venv\Scripts\activate.bat
python -m pip install --quiet --disable-pip-version-check psycopg2-binary
echo Loading your finance emails into Ganak...
python backend\connectors\load_gmail_snapshot.py
echo.
echo Done. Close the "Ganak Backend" window and re-run start.bat so Ganak sees
echo the new emails, then ask things like: "how many bank payment advices last month?"
echo.
pause
