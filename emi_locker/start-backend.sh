#!/usr/bin/env bash
# Starts the EMI Locker backend for local testing (macOS / Linux).
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating a Python virtual environment..."
  python3 -m venv .venv
fi
. .venv/bin/activate

echo "Installing dependencies..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r backend/requirements.txt

if [ ! -f emi_locker.db ]; then
  echo "Seeding the database..."
  python -m backend.seed
fi

echo
echo "=========================================================="
echo " Backend starting. Leave this terminal open."
echo " API docs:  http://localhost:8000/docs"
echo " Sign in:   retailer 9000000003 | customer 9876543210"
echo "=========================================================="
echo
exec python -m backend.app.main
