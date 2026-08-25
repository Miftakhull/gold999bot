@echo off
cd /d "%~dp0"
python src\main.py >> bot_log.txt 2>&1
