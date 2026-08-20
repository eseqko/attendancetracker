#!/bin/bash
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
    echo "Please run install_mac.command first — it sets everything up."
    read -r -p "Press Enter to close..."
    exit 1
fi
echo "Starting the Attendance Tracker... your browser will open shortly."
echo "Keep this window open while you use the app. Close it to stop."
echo
./.venv/bin/python -m streamlit run app.py
