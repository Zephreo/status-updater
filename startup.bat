@echo off
cd /d "%~dp0"
echo Starting Status Updater (pipenv run python main.py)...
echo.
call pipenv run python main.py
