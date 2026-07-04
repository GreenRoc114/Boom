@echo off
chcp 65001 >nul
echo =======================================
echo Boom TangDou - Local Server Starter
echo =======================================

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [Error] Python is not installed or not in PATH!
    pause
    exit /b
)

:: Install dependencies if requirements.txt exists
if exist requirements.txt (
    echo [Info] Installing dependencies...
    pip install -r requirements.txt >nul
)

:: Ensure config.json exists, otherwise copy from example
if not exist config.json (
    if exist config.json.example (
        echo [Info] Copying config.json.example to config.json...
        copy config.json.example config.json >nul
    ) else (
        echo [Warning] No config.json found and no example available.
    )
)

echo [Info] Starting Boom V3.0 Server...
echo ---------------------------------------
python server.py
pause
