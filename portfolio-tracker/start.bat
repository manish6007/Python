@echo off
REM Run from source on Windows. Needs Python 3.9+ and Node 18+.
REM If you would rather not install those, download the ready-made app
REM instead - see the README.
cd /d "%~dp0"

if not exist "frontend\dist" (
  echo Building the interface ^(first run only^)...
  pushd frontend
  call npm install || goto :fail
  call npm run build || goto :fail
  popd
)

if not exist ".venv" (
  echo Setting up Python ^(first run only^)...
  python -m venv .venv || goto :fail
  ".venv\Scripts\python" -m pip install --quiet --upgrade pip
  ".venv\Scripts\pip" install --quiet -r backend\requirements.txt || goto :fail
)

".venv\Scripts\python" backend\desktop.py %*
goto :eof

:fail
echo.
echo Something went wrong. Check that Python 3.9+ and Node 18+ are installed
echo and on your PATH, then run this again.
pause
