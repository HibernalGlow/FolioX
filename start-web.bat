@echo off
cd /d "%~dp0"

:: Start web mode (FastAPI only)
.venv\Scripts\python.exe server.py
