@echo off
cd /d "%~dp0"

::: Start web mode (FastAPI only)
.venv\Scripts\folio.exe web
