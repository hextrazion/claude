@echo off
rem Development mode: backend with live UI reload (Vite on http://127.0.0.1:5173).
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\app\backend"
set "STUDIO_DEV=1"
start "AI Video Studio backend" cmd /k ".venv\Scripts\python.exe -m studio"
cd app\frontend
call npm run dev
