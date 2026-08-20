@echo off
cd /d "%~dp0"
title Attendance Tracker
if not exist ".venv\Scripts\python.exe" (
    echo Please run install_windows.bat first - it sets everything up.
    pause
    exit /b 1
)
echo Starting the Attendance Tracker... your browser will open shortly.
echo Keep this window open while you use the app. Close it to stop.
echo.
".venv\Scripts\python.exe" -m streamlit run app.py
pause
