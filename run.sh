#!/usr/bin/env bash
# Fillet - one-command local start on macOS / Linux:  ./run.sh
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Creating virtual environment (Python 3.11)..."
  python3.11 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env - add your GROQ_API_KEY and/or MISTRAL_API_KEY, then run this again."
  exit 1
fi
exec .venv/bin/streamlit run app.py
