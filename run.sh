#!/usr/bin/env bash
# Always & Furever Donor CRM — local dev runner.
# Creates a venv, installs Flask, builds + seeds a demo SQLite db, starts the app.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating virtualenv..."
  python3 -m venv .venv
fi
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet flask

echo "Building demo database..."
./.venv/bin/python seed_demo.py

echo ""
echo "Starting server at http://127.0.0.1:5000  (Ctrl+C to stop)"
echo ""
exec ./.venv/bin/python app.py
