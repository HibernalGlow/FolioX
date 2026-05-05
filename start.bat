@echo off
cd /d "%~dp0"

:: Build frontend if needed
if not exist "dist-frontend\index.html" (
    echo Building Svelte frontend...
    cd frontend
    call pnpm install
    call pnpm run build
    cd ..
)

:: Start desktop app
.venv\Scripts\python.exe main.py
