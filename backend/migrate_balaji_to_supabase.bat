@echo off
REM ============================================================
REM  One-time: copy Balaji's local Postgres warehouse into the
REM  Supabase 'balaji' schema, so the cloud-hosted Ganak backend
REM  can see your real business data.
REM ============================================================
setlocal
cd /d "%~dp0"

if exist "venv\Scripts\activate.bat" (
  call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
  call .venv\Scripts\activate.bat
)

echo Installing/checking required packages...
python -m pip install --quiet --disable-pip-version-check sqlalchemy psycopg2-binary pandas
echo.

python migrate_balaji_to_supabase.py

echo.
echo ============================================================
echo   Copy everything above and send it back.
echo ============================================================
pause
