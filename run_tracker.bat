@echo off
cd /d "%~dp0"
title Attendance Tracker
if not exist ".venv\Scripts\python.exe" (
    echo Please run install_windows.bat first - it sets everything up.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo The app environment looks broken - please run install_windows.bat again.
    echo It rebuilds everything cleanly; your saved data is not touched.
    pause
    exit /b 1
)
rem After an update the environment may be missing new pieces - refresh it.
fc /b pyproject.toml ".venv\pyproject.installed" >nul 2>nul
if errorlevel 1 (
    echo Finishing an app update - this only happens once per update...
    ".venv\Scripts\python.exe" -m pip install -e . && copy /y pyproject.toml ".venv\pyproject.installed" >nul
    echo.
)
echo Starting the Attendance Tracker... your browser will open shortly.
echo Keep this window open while you use the app. Close it to stop.
echo.
".venv\Scripts\python.exe" -m streamlit run app.py
pause
