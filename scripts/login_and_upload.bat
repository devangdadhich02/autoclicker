@echo off
chcp 65001 >nul
echo.
echo ========================================
echo   Velora — IndiaMART Login Helper
echo ========================================
echo.
echo  This will open Chrome on YOUR computer.
echo  After you login, session uploads to server.
echo.

:: Server details (change these)
set SERVER_IP=68.178.160.47
set SSH_USER=autoclicker
set PROFILE_NAME=indiamart

echo  Server: %SERVER_IP%
echo  Profile: %PROFILE_NAME%
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found!
    echo  Please install Python from https://python.org
    pause
    exit /b 1
)

:: Install dependencies if needed
echo  Checking dependencies...
pip install playwright paramiko -q 2>nul

:: Install browser if needed
echo  Checking Chrome browser...
python -m playwright install chromium 2>nul

echo.
echo  Starting login process...
echo  Chrome will open — login to IndiaMART, then press ENTER here.
echo.

:: Run the script
python "%~dp0login_local_and_upload.py" --server %SERVER_IP% --user %SSH_USER% --profile %PROFILE_NAME%

echo.
echo  Done! Press any key to close...
pause >nul
