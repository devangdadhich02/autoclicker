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

# Check Python (try multiple commands for Windows compatibility)
$pythonCmd = $null
foreach ($cmd in @("py", "python", "python3")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) {
        $pythonCmd = $cmd
        break
    }
}

if (-not $pythonCmd) {
    Write-Host "ERROR: Python not found!" -ForegroundColor Red
    Write-Host "Please install Python from https://python.org" -ForegroundColor Red
    Write-Host "" -ForegroundColor Yellow
    Write-Host "Quick fix - Install Python:" -ForegroundColor Yellow
    Write-Host "  1. Go to: https://python.org/downloads" -ForegroundColor Yellow
    Write-Host "  2. Download Python 3.11+" -ForegroundColor Yellow
    Write-Host "  3. Install with 'Add Python to PATH' checked" -ForegroundColor Yellow
    Write-Host "  4. Re-open PowerShell and run again" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Found Python: $pythonCmd" -ForegroundColor Green

# Download script if not exists
$scriptFile = "login_local_and_upload.py"
if (-not (Test-Path $scriptFile)) {
    Write-Host "Downloading required files..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://raw.githubusercontent.com/devangdadhich02/autoclicker/main/scripts/login_local_and_upload.py" -OutFile $scriptFile
}

# Install dependencies
Write-Host "Installing dependencies (one-time)..." -ForegroundColor Yellow
& $pythonCmd -m pip install playwright paramiko -q 2>$null
& $pythonCmd -m playwright install chromium 2>$null

Write-Host ""
Write-Host "Starting Chrome... Please login to IndiaMART when it opens." -ForegroundColor Green
Write-Host "After login, come back here and press ENTER to upload." -ForegroundColor Green
Write-Host ""

# Run the script
& $pythonCmd $scriptFile --server $Server --user $User --profile $Profile

Write-Host ""
Read-Host "Done! Press Enter to close"
