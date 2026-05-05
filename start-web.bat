@echo off
chcp 65001 >nul
title Folio-OCR Web Server

echo ========================================
echo        Folio-OCR Web Server
echo        http://localhost:3000
echo ========================================
echo.

cd /d %~dp0

::: Check if uv venv exists
if exist ".venv\Scripts\activate.bat" (
    echo Activating uv virtual environment...
    call .venv\Scripts\activate.bat
) else if exist ".venv\Scripts\python.exe" (
    echo Activating uv virtual environment...
    .venv\Scripts\activate.bat
) else (
    echo Warning: Virtual environment not found, using global Python
)

echo.
echo Starting web server at http://localhost:3000
echo Press Ctrl+C to stop
echo.
echo ========================================
echo.

python server.py

pause
