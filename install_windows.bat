@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Attendance Tracker installer
echo ============================================
echo  Attendance Tracker - one-time installer
echo ============================================
echo.

rem --- Find Python 3.10+ ---------------------------------------------------
set "PYCMD="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if not defined PYCMD (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYCMD=python"
)

rem --- Try to install Python automatically if it's missing -----------------
if not defined PYCMD (
    echo Python 3.10+ was not found. Trying to install it with winget...
    winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
    set "PYEXE="
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do set "PYEXE=%%D\python.exe"
    if defined PYEXE if exist "!PYEXE!" set PYCMD="!PYEXE!"
)
if not defined PYCMD (
    echo.
    echo Could not install Python automatically.
    echo Opening the Python download page. Install Python 3
    echo ^(IMPORTANT: check "Add python.exe to PATH"^), then
    echo double-click this installer again.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Using Python: %PYCMD%
echo.
echo Setting up the app environment - this can take a few minutes
echo the first time. Please leave this window open...
echo.
%PYCMD% -m venv .venv || goto :fail
".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
".venv\Scripts\python.exe" -m pip install -e . || goto :fail
copy /y pyproject.toml ".venv\pyproject.installed" >nul

echo.
echo Creating a desktop shortcut...
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Attendance Tracker.lnk'); $s.TargetPath='%~dp0run_tracker.bat'; $s.WorkingDirectory='%~dp0'; $s.Save()"

echo.
echo ============================================
echo  Done! Start the app with the "Attendance
echo  Tracker" shortcut on your desktop, or by
echo  double-clicking run_tracker.bat
echo ============================================
pause
exit /b 0

:fail
echo.
echo Something went wrong - see the messages above.
echo If this keeps happening, ask for the text in this window.
pause
exit /b 1
