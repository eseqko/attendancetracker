@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Attendance Tracker - deploy the web version
echo ============================================
echo  Attendance Tracker - deploy the web version
echo ============================================
echo.
echo Before the first run: create a free project at
echo console.firebase.google.com and have its Project ID ready.
echo.

rem --- Find Node.js, or install it ------------------------------------
set "NODECMD="
node --version >nul 2>nul
if not errorlevel 1 set "NODECMD=node"
if not defined NODECMD (
    echo Node.js was not found. Installing it with winget...
    winget install --id OpenJS.NodeJS.LTS -e --silent --accept-package-agreements --accept-source-agreements
    if exist "%ProgramFiles%\nodejs\node.exe" set "PATH=%ProgramFiles%\nodejs;%PATH%"
    node --version >nul 2>nul
    if not errorlevel 1 set "NODECMD=node"
)
if not defined NODECMD (
    echo.
    echo Could not install Node.js automatically. Install the LTS version
    echo from the page that just opened, then run this file again.
    start https://nodejs.org/
    pause
    exit /b 1
)
for /f %%V in ('node --version') do echo Using Node.js %%V

rem --- Python for the build (the app's own environment, or any Python) -
set "PYCMD=.venv\Scripts\python.exe"
if not exist "%PYCMD%" set "PYCMD=py -3"

rem --- Firebase project ID: asked once, remembered in .firebaserc -----
if not exist ".firebaserc" (
    echo.
    echo Enter your Firebase Project ID ^(shown in the Firebase console
    echo under Project settings, e.g. attendance-tracker-1a2b3^):
    set /p FBPROJECT="Project ID: "
    > .firebaserc echo { "projects": { "default": "!FBPROJECT!" } }
)

echo.
echo Building the web app - the first run downloads its components
echo ^(~430 MB^) and can take a while. Please leave this window open...
%PYCMD% scripts\build_webapp.py --vendor || goto :fail

echo.
echo Signing in to Firebase - a browser window may open the first time...
call npx -y firebase-tools@latest login:list 2>nul | find "@" >nul
if errorlevel 1 (
    call npx -y firebase-tools@latest login
    rem The login helper can crash on exit AFTER succeeding (a known Node
    rem bug on Windows) - judge by the signed-in state, not the exit code.
    call npx -y firebase-tools@latest login:list 2>nul | find "@" >nul
    if errorlevel 1 goto :fail
) else (
    echo Already signed in.
)

echo.
echo Deploying ^(~73 MB upload^)...
call npx -y firebase-tools@latest deploy --only hosting || goto :fail

echo.
echo ============================================
echo  Done! Your link is the "Hosting URL" shown
echo  a few lines above - it ends in .web.app and
echo  works on any Chromebook. Re-run this file
echo  any time to publish an updated version.
echo ============================================
pause
exit /b 0

:fail
echo.
echo Something went wrong - see the messages above.
echo If this keeps happening, ask for the text in this window.
pause
exit /b 1
