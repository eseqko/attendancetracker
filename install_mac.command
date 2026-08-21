#!/bin/bash
# Attendance Tracker — one-time installer (macOS).
# First time opening: right-click -> Open (Gatekeeper warns about downloads).
set -e
cd "$(dirname "$0")"
echo "============================================"
echo " Attendance Tracker — one-time installer"
echo "============================================"
echo

PY=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PY="$candidate"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "Python 3.10+ was not found."
    echo "Opening the Python download page — install it, then"
    echo "double-click this installer again."
    open "https://www.python.org/downloads/" 2>/dev/null || true
    read -r -p "Press Enter to close..."
    exit 1
fi

echo "Using Python: $PY"
echo
echo "Setting up the app environment — this can take a few minutes"
echo "the first time. Please leave this window open..."
echo
"$PY" -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install .

echo
echo "============================================"
echo " Done! Start the app by double-clicking"
echo " run_tracker.command"
echo "============================================"
read -r -p "Press Enter to close..."
