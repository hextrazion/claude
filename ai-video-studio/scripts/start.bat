@echo off
setlocal EnableExtensions
rem AI Video Studio - one-click launcher for Windows.
rem First run: creates a Python virtual environment, installs dependencies and
rem builds the web UI. Later runs start straight away.

cd /d "%~dp0.."
set "ROOT=%CD%"
title AI Video Studio

rem ---- Python --------------------------------------------------------------
set "PY="
where py >nul 2>nul && (py -3.13 -c "1" >nul 2>nul && set "PY=py -3.13")
if not defined PY where py >nul 2>nul && (py -3.12 -c "1" >nul 2>nul && set "PY=py -3.12")
if not defined PY where py >nul 2>nul && (py -3.11 -c "1" >nul 2>nul && set "PY=py -3.11")
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/ ^(tick "Add to PATH"^).
  pause & exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python environment...
  %PY% -m venv .venv || (echo Could not create the virtual environment. & pause & exit /b 1)
)
set "VPY=%ROOT%\.venv\Scripts\python.exe"

rem Reinstall only when requirements.txt changed.
fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>nul
if errorlevel 1 (
  echo Installing Python packages...
  "%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip
  "%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt || (echo Package install failed. & pause & exit /b 1)
  copy /y requirements.txt ".venv\installed-requirements.txt" >nul
)

rem ---- Web UI ----------------------------------------------------------------
if not exist "app\frontend\dist\index.html" (
  where npm >nul 2>nul || (
    echo The web UI has not been built yet and Node.js was not found.
    echo Install Node.js 22 LTS from https://nodejs.org/ and run this script again.
    pause & exit /b 1
  )
  echo Building the web UI ^(first run only^)...
  pushd app\frontend
  call npm ci --no-audit --no-fund || (popd & echo npm install failed. & pause & exit /b 1)
  call npm run build || (popd & echo UI build failed. & pause & exit /b 1)
  popd
)

rem ---- FFmpeg hint -------------------------------------------------------------
if not exist "tools\ffmpeg\bin\ffmpeg.exe" (
  where ffmpeg >nul 2>nul || echo Note: FFmpeg not found. Assembly will not work until it is installed - see docs\SETUP.md.
)

rem ---- Run -------------------------------------------------------------------------
set "PYTHONPATH=%ROOT%\app\backend"
"%VPY%" -m studio
if errorlevel 1 pause
