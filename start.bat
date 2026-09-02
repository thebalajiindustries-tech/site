@echo off
REM ============================================================
REM  Ganak - local development launcher (Windows)
REM  Double-click this file to set up and run Ganak locally.
REM  Everything stays on THIS computer (except the AI call).
REM ============================================================
setlocal
cd /d "%~dp0"

echo ============================================================
echo   GANAK  -  local development
echo ============================================================
echo.

REM ---------- Backend: first-time setup ----------
if not exist "backend\venv\" (
  echo [setup] Creating backend environment ^(one time^)...
  python -m venv backend\venv
  if errorlevel 1 (
     echo ERROR: Python not found. Install Python 3.11+ from python.org and retry.
     pause & exit /b
  )
  call backend\venv\Scripts\activate.bat
  echo [setup] Installing backend packages...
  pip install -r backend\requirements.txt
  if not exist "backend\.env" copy backend\.env.example backend\.env >nul
  echo.
  echo ------------------------------------------------------------
  echo  ONE-TIME STEP: open this file in Notepad and fill in 2 lines:
  echo.
  echo     backend\.env
  echo.
  echo     DATABASE_URL=postgresql://postgres:YOUR_PG_PASSWORD@localhost:5432/the_balaji
  echo     ANTHROPIC_API_KEY=sk-ant-...   ^(from console.anthropic.com^)
  echo.
  echo  Save it, then double-click start.bat again.
  echo ------------------------------------------------------------
  echo.
  start notepad backend\.env
  pause
  exit /b
)

REM ---------- Frontend: first-time setup ----------
if not exist "frontend\node_modules\" (
  echo [setup] Installing frontend packages ^(one time^)...
  if not exist "frontend\.env.local" copy frontend\.env.local.example frontend\.env.local >nul
  pushd frontend
  call npm install
  if errorlevel 1 (
     echo ERROR: Node.js not found. Install Node 18+ from nodejs.org and retry.
     popd & pause & exit /b
  )
  popd
)

REM ---------- Stop any leftover copy from a previous run ----------
echo [run] Clearing any previous Ganak processes...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3000 " ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3001 " ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
timeout /t 2 >nul

REM ---------- Launch both services ----------
echo [run] Starting backend on http://localhost:8000 ...
start "Ganak Backend" cmd /k "cd /d %~dp0backend && venv\Scripts\activate.bat && uvicorn app.main:app --reload"

echo [run] Starting frontend on http://localhost:3000 ...
start "Ganak Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo [run] Opening the app in your browser...
timeout /t 7 >nul
start http://localhost:3000

echo.
echo ============================================================
echo   Ganak is running.
echo   App:      http://localhost:3000
echo   Backend:  http://localhost:8000/health
echo   Close the two new windows to stop it.
echo ============================================================
