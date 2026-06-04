@echo off
chcp 65001 >nul
echo ========================================
echo   Velora - IndiaMART Login Helper
echo ========================================
echo.
echo This will open Chrome on YOUR computer.
echo After you login, session uploads to server.
echo.

REM Server details - EDIT THESE
set SERVER_IP=68.178.160.47
set SSH_USER=autoclicker
set PROFILE_NAME=indiamart

echo Server: %SERVER_IP%
echo Profile: %PROFILE_NAME%
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python from https://python.org
    pause
    exit /b 1
)

REM Always download latest upload script from the deployment branch
echo Downloading latest upload script...
curl -o login_local_and_upload.py https://raw.githubusercontent.com/devangdadhich02/autoclicker/feat/new/scripts/login_local_and_upload.py

REM Install dependencies
echo Installing dependencies...
pip install playwright paramiko -q 2>nul
python -m playwright install chromium 2>nul

echo.
echo Starting Chrome... Please login to IndiaMART when it opens.
echo After login, come back here and press ENTER to upload.
echo.

python login_local_and_upload.py --server %SERVER_IP% --user %SSH_USER% --profile %PROFILE_NAME%

echo.
echo Done! Press any key to close...
pause >nul
