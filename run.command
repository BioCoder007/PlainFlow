#!/usr/bin/env bash
# Starts PlainFlow. The first run sets everything up (about a minute); later runs start at once.
set -e
cd "$(dirname "$0")"

PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/ and run this again."
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "PlainFlow needs Python 3.11 or newer. You have: $("$PY" --version)"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up PlainFlow. This takes about a minute."
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
fi

exec .venv/bin/python main.py "$@"
