@echo off
rem Daily run for Windows Task Scheduler. Every run is logged to powerbi\refresh_log.csv.
rem Uses the project's .venv when there is one, otherwise the python on PATH.
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" pipeline.py --charts %*
