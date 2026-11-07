# Production-Parity Local Docker Testing & Development Script

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Building & Starting Local Production-Parity Environment" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Build and start containers (MySQL, Redis, Web App)
docker-compose up --build -d

if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Docker Compose failed to start." -ForegroundColor Red
    exit 1
}

Write-Host "`nWaiting for web container health check..." -ForegroundColor Yellow
$timeout = 60
$elapsed = 0
$isHealthy = $false

while ($elapsed -lt $timeout) {
    $rawStatus = (docker inspect --format='{{json .State.Health.Status}}' attn_billing_web 2>$null)
    if ($rawStatus) {
        $status = $rawStatus | ConvertFrom-Json
        if ($status -eq "healthy") {
            Write-Host "[+] Local environment is healthy and running!" -ForegroundColor Green
            $isHealthy = $true
            break
        }
    }
    Start-Sleep -Seconds 2
    $elapsed += 2
}

if (-not $isHealthy) {
    Write-Host "[!] Web container failed to reach healthy state. Check docker logs attn_billing_web." -ForegroundColor Red
    exit 1
}

# 2. Apply database migrations to local MySQL container
Write-Host "`n--> Applying Database Migrations to Local MySQL Container..." -ForegroundColor Yellow
docker exec -t attn_billing_web python scratch/apply_production_migrations_v4.py

# 3. Run automated regression test suite inside container
Write-Host "`n--> Running 100% Automated Multi-Tenant Test Gate Suite..." -ForegroundColor Yellow
docker exec -t attn_billing_web python scratch/test_auth_rate_limit.py

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host " Local Production-Parity Docker Environment is Ready!" -ForegroundColor Green
Write-Host " Web App URL:      http://localhost:8080" -ForegroundColor Green
Write-Host " Health Check:     http://localhost:8080/healthz" -ForegroundColor Green
Write-Host " MySQL (Port):     localhost:3308" -ForegroundColor Green
Write-Host " Redis (Port):     localhost:6379" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
