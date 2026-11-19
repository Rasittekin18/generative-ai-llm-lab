@echo off
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
python -B run_app.py
pause
