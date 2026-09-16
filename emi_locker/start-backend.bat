@echo off
REM Starts the EMI Locker backend for local testing.
REM Double-click this file, or run it from Command Prompt.
REM Leave the window open while you use the app; press Ctrl+C to stop.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating a Python virtual environment...
  python -m venv .venv || goto :failed
)

call .venv\Scripts\activate.bat

echo Installing dependencies...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r backend\requirements.txt || goto :failed

if not exist "emi_locker.db" (
  echo Seeding the database...
  python -m backend.seed || goto :failed
)

echo.
echo ==========================================================
echo  Backend starting. Leave this window open.
echo  API docs:  http://localhost:8000/docs
echo  Sign in:   retailer 9000000003 ^| customer 9876543210
echo ==========================================================
echo.
python -m backend.app.main
goto :eof

:failed
echo.
echo Something went wrong. See SETUP notes in docs\WINDOWS_SETUP.md
pause
