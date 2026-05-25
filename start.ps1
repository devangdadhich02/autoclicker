# Velora Auto Clicker — Quick Start Script (Windows PowerShell)
# Run: .\start.ps1

Write-Host "================================================" -ForegroundColor Cyan
Write-Host " Velora Auto Clicker — Starting..." -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# Check .env exists
if (-not (Test-Path "backend\.env")) {
    Write-Host ""
    Write-Host "[ERROR] backend\.env not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Steps to fix:" -ForegroundColor Yellow
    Write-Host "  1. Copy template:  copy backend\.env.docker backend\.env" -ForegroundColor White
    Write-Host "  2. Edit .env:      notepad backend\.env" -ForegroundColor White
    Write-Host "     - Set SECRET_KEY" -ForegroundColor White
    Write-Host "     - Set DATABASE_URL (your Supabase URL)" -ForegroundColor White
    Write-Host "     - Set FIRST_ADMIN_PASSWORD" -ForegroundColor White
    Write-Host "  3. Run again:      .\start.ps1" -ForegroundColor White
    Write-Host ""
    exit 1
}

Write-Host "[OK] .env file found" -ForegroundColor Green

# Check Docker running
try {
    docker info > $null 2>&1
    Write-Host "[OK] Docker is running" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Docker is not running. Please start Docker Desktop." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Building and starting containers..." -ForegroundColor Cyan
docker compose up -d --build

Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host " Velora is starting up!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""
Write-Host " Dashboard:   http://localhost" -ForegroundColor White
Write-Host " API Docs:    http://localhost:8000/api/docs" -ForegroundColor White
Write-Host " Health:      http://localhost:8000/api/v1/health/ping" -ForegroundColor White
Write-Host ""
Write-Host " Logs: docker compose logs -f" -ForegroundColor Gray
Write-Host " Stop: docker compose down" -ForegroundColor Gray
Write-Host ""
