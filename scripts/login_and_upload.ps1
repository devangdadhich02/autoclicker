# Velora - IndiaMART Login Helper (PowerShell)
# =============================================
# Run this on YOUR local Windows computer

param(
    [string]$Server = "68.178.160.47",
    [string]$User = "autoclicker",
    [string]$Profile = "indiamart"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Velora - IndiaMART Login Helper" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "This will open Chrome on YOUR computer." -ForegroundColor Yellow
Write-Host "After you login, session uploads to server." -ForegroundColor Yellow
Write-Host ""
Write-Host "Server: $Server" -ForegroundColor Green
Write-Host "Profile: $Profile" -ForegroundColor Green
Write-Host ""

# Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "ERROR: Python not found!" -ForegroundColor Red
    Write-Host "Please install Python from https://python.org" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Download script if not exists
$scriptFile = "login_local_and_upload.py"
if (-not (Test-Path $scriptFile)) {
    Write-Host "Downloading required files..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://raw.githubusercontent.com/devangdadhich02/autoclicker/main/scripts/login_local_and_upload.py" -OutFile $scriptFile
}

# Install dependencies
Write-Host "Installing dependencies (one-time)..." -ForegroundColor Yellow
& python -m pip install playwright paramiko -q 2>$null
& python -m playwright install chromium 2>$null

Write-Host ""
Write-Host "Starting Chrome... Please login to IndiaMART when it opens." -ForegroundColor Green
Write-Host "After login, come back here and press ENTER to upload." -ForegroundColor Green
Write-Host ""

# Run the script
& python $scriptFile --server $Server --user $User --profile $Profile

Write-Host ""
Read-Host "Done! Press Enter to close"
