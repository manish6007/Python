#!/usr/bin/env sh
# Run from source on macOS or Linux, without meeting a terminal properly.
# Needs Python 3.9+ and Node 18+. If you would rather not install those,
# download the ready-made app instead — see the README.
set -e
cd "$(dirname "$0")"

if [ ! -d frontend/dist ]; then
  echo "Building the interface (first run only)..."
  (cd frontend && npm install && npm run build)
fi

if [ ! -d .venv ]; then
  echo "Setting up Python (first run only)..."
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r backend/requirements.txt
fi

exec .venv/bin/python backend/desktop.py "$@"
