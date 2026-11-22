@echo off
rem Daily run for Windows Task Scheduler. Every run is logged to powerbi\refresh_log.csv.
cd /d "%~dp0"
".venv\Scripts\python.exe" pipeline.py --charts %*
