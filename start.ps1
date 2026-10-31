Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  OTT Platform Backend - Starting Server     " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# 1. Locate Python
$python = ""
if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
    Write-Host "[OK] Using virtual environment Python (.venv)" -ForegroundColor Green
} else {
    $python = "python"
    Write-Host "[OK] Using system Python" -ForegroundColor Green
}

# 2. Run Database Migrations
Write-Host ""
Write-Host "Applying database migrations..." -ForegroundColor Yellow
& $python -m alembic upgrade head

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[Warning] Database migration failed!" -ForegroundColor Red
    Write-Host "Make sure PostgreSQL is running on port 5432 with the password from DATABASE_URL in .env." -ForegroundColor Yellow
    Write-Host "Alternatively, to test with SQLite, change DATABASE_URL in .env to:" -ForegroundColor Yellow
    Write-Host "DATABASE_URL=sqlite:///./ott.db" -ForegroundColor White
} else {
    Write-Host "[OK] Database is up to date!" -ForegroundColor Green
}

# 3. Start Uvicorn
Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host "  API running at: http://localhost:8000       " -ForegroundColor Green
Write-Host "  Swagger Docs:   http://localhost:8000/api/v1/docs" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host "Press Ctrl + C to stop the server." -ForegroundColor Gray
Write-Host ""

& $python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
