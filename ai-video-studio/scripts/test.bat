@echo off
rem Runs the backend and frontend test suites.
cd /d "%~dp0.."
.venv\Scripts\python.exe -m pip install -q -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
cd app\frontend && call npm test
pause
