#!/bin/bash
echo "======================================="
echo "Boom TangDou - Local Server Starter"
echo "======================================="

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "[Error] python3 is not installed!"
    exit 1
fi

# Install dependencies if requirements.txt exists
if [ -f "requirements.txt" ]; then
    echo "[Info] Installing dependencies..."
    pip install -r requirements.txt
fi

# Ensure config.json exists, otherwise copy from example
if [ ! -f "config.json" ]; then
    if [ -f "config.json.example" ]; then
        echo "[Info] Copying config.json.example to config.json..."
        cp config.json.example config.json
    else
        echo "[Warning] No config.json found and no example available."
    fi
fi

echo "[Info] Starting Boom V3.0 Server..."
echo "---------------------------------------"
python3 server.py
