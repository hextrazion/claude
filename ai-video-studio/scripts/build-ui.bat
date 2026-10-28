@echo off
rem Rebuild the web UI after changing files in app\frontend\src.
cd /d "%~dp0..\app\frontend"
call npm ci --no-audit --no-fund && call npm run build
pause
