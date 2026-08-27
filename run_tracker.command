#!/bin/bash
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
    echo "Please run install_mac.command first — it sets everything up."
    read -r -p "Press Enter to close..."
    exit 1
fi
if ! ./.venv/bin/python -c 'import sys' >/dev/null 2>&1; then
    echo "The app environment looks broken — please run install_mac.command again."
    echo "It rebuilds everything cleanly; your saved data is not touched."
    read -r -p "Press Enter to close..."
    exit 1
fi
# After an update the environment may be missing new pieces — refresh it.
if ! cmp -s pyproject.toml .venv/pyproject.installed; then
    echo "Finishing an app update — this only happens once per update..."
    ./.venv/bin/python -m pip install -e . && cp pyproject.toml .venv/pyproject.installed
    echo
fi
echo "Starting the Attendance Tracker... your browser will open shortly."
echo "Keep this window open while you use the app. Close it to stop."
echo
./.venv/bin/python -m streamlit run app.py
