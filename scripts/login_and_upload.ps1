# Velora - IndiaMART Login Helper (PowerShell)
# =============================================
# Run this on YOUR local Windows computer

param(
    [string]$Server = "68.178.160.47",
    [string]$User = "autoclicker",
    [string]$Profile = "indiamart",
    [string]$Url = "https://seller.indiamart.com/bltxn/?pref=recent"
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

# Check Python (try multiple commands and verify they actually work)
$pythonCmd = $null
foreach ($cmd in @("py", "python", "python3")) {
    try {
        $version = & $cmd --version 2>&1
        if ($version -match "Python (\d+\.\d+)") {
            $pythonCmd = $cmd
            Write-Host "Found Python: $version" -ForegroundColor Green
            break
        }
    } catch {
        # Command not found or not working, try next
    }
}

if (-not $pythonCmd) {
    Write-Host "ERROR: Python not found or not working!" -ForegroundColor Red
    Write-Host "" -ForegroundColor Red
    Write-Host "Please install Python using ONE of these methods:" -ForegroundColor Yellow
    Write-Host "" -ForegroundColor Yellow
    Write-Host "METHOD 1 - Microsoft Store (Easiest):" -ForegroundColor Cyan
    Write-Host "  Type 'python' in PowerShell and press Enter" -ForegroundColor White
    Write-Host "  Microsoft Store will open - click 'Install' on Python 3.11" -ForegroundColor White
    Write-Host "" -ForegroundColor Yellow
    Write-Host "METHOD 2 - Python.org (Recommended):" -ForegroundColor Cyan
    Write-Host "  1. Go to: https://python.org/downloads" -ForegroundColor White
    Write-Host "  2. Download Python 3.11+" -ForegroundColor White
    Write-Host "  3. IMPORTANT: Check 'Add Python to PATH' during install" -ForegroundColor White
    Write-Host "  4. Re-open PowerShell after installation" -ForegroundColor White
    Write-Host "" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Always use latest upload script from GitHub (fixes server path issues)
$scriptFile = Join-Path (Get-Location) "login_local_and_upload.py"
Write-Host "Downloading latest upload script..." -ForegroundColor Yellow
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/devangdadhich02/autoclicker/main/scripts/login_local_and_upload.py" -OutFile $scriptFile

# Install dependencies
Write-Host "Installing dependencies (one-time)..." -ForegroundColor Yellow
& $pythonCmd -m pip install playwright paramiko -q 2>$null
& $pythonCmd -m playwright install chromium 2>$null

Write-Host ""
Write-Host "Starting Chrome... Please login to IndiaMART when it opens." -ForegroundColor Green
Write-Host "After login, come back here and press ENTER to upload." -ForegroundColor Green
Write-Host ""

# Run the script (uploads into Docker volume on server)
& $pythonCmd $scriptFile --server $Server --user $User --profile $Profile --url $Url

Write-Host ""
Read-Host "Done! Press Enter to close"
