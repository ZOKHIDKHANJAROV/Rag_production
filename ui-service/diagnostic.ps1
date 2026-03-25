# RAG UI Service - Diagnostic Script
# Run this to diagnose common issues

Write-Host "🔍 RAG UI Service Diagnostic Tool" -ForegroundColor Cyan
Write-Host "=================================" -ForegroundColor Cyan
Write-Host ""

$API_BASE = "http://localhost:8000"

# 1. Check if UI service is running
Write-Host "1️⃣  Checking UI Service..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$API_BASE/health" -Method Get -ErrorAction Stop
    Write-Host "✅ UI Service is running at $API_BASE" -ForegroundColor Green
} catch {
    Write-Host "❌ UI Service is NOT running at $API_BASE" -ForegroundColor Red
    Write-Host "   Start it with: uvicorn app.main:app --reload" -ForegroundColor Yellow
    exit 1
}

# 2. Get configuration
Write-Host ""
Write-Host "2️⃣  Checking Configuration..." -ForegroundColor Yellow
try {
    $config = Invoke-WebRequest -Uri "$API_BASE/api/debug/config" -Method Get -ErrorAction Stop | ConvertFrom-Json
    Write-Host "✅ Configuration loaded" -ForegroundColor Green
    Write-Host "   RAG URL: $($config.rag_url)" -ForegroundColor Cyan
    Write-Host "   Sessions: $($config.sessions_count)" -ForegroundColor Cyan
} catch {
    Write-Host "❌ Cannot load configuration: $($_.Exception.Message)" -ForegroundColor Red
}

# 3. Check service status
Write-Host ""
Write-Host "3️⃣  Checking Backend Services..." -ForegroundColor Yellow
try {
    $status = Invoke-WebRequest -Uri "$API_BASE/api/services-status" -Method Get -ErrorAction Stop | ConvertFrom-Json
    
    foreach ($service in $status.services.PSObject.Properties) {
        $name = $service.Name
        $serviceStatus = $service.Value.status
        $url = $service.Value.url
        
        if ($serviceStatus -eq "healthy") {
            Write-Host "   ✅ $name - Healthy" -ForegroundColor Green
        } else {
            Write-Host "   ❌ $name - OFFLINE at $url" -ForegroundColor Red
        }
    }
} catch {
    Write-Host "❌ Cannot check service status: $($_.Exception.Message)" -ForegroundColor Red
}

# 4. Test RAG connection
Write-Host ""
Write-Host "4️⃣  Testing RAG Service Connection..." -ForegroundColor Yellow
try {
    $testResult = Invoke-WebRequest -Uri "$API_BASE/api/debug/test-rag" -Method Post -Body "question=test" -ContentType "application/x-www-form-urlencoded" -ErrorAction Stop | ConvertFrom-Json
    
    if ($testResult.status -eq "success") {
        Write-Host "✅ RAG Service is working!" -ForegroundColor Green
        if ($testResult.response.answer) {
            Write-Host "   Answer: $($testResult.response.answer.Substring(0, 100))..." -ForegroundColor Cyan
        }
    } else {
        Write-Host "❌ RAG Service Error:" -ForegroundColor Red
        Write-Host "   Error: $($testResult.error)" -ForegroundColor Red
        Write-Host "   Details: $($testResult.details)" -ForegroundColor Yellow
        if ($testResult.suggestions) {
            Write-Host "   Suggestions:" -ForegroundColor Yellow
            foreach ($suggestion in $testResult.suggestions) {
                Write-Host "   - $suggestion" -ForegroundColor Cyan
            }
        }
    }
} catch {
    Write-Host "❌ Cannot test RAG service: $($_.Exception.Message)" -ForegroundColor Red
}

# 5. Summary
Write-Host ""
Write-Host "📋 Summary" -ForegroundColor Cyan
Write-Host "==========" -ForegroundColor Cyan

$dockerRunning = docker ps -q 2>$null
if ($dockerRunning) {
    Write-Host "✅ Docker is running" -ForegroundColor Green
    Write-Host ""
    Write-Host "Running containers:" -ForegroundColor Yellow
    docker ps --format "table {{.Names}}\t{{.Status}}" | Select-Object -First 10
} else {
    Write-Host "⚠️  Docker may not be running" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "🔧 Quick Tips:" -ForegroundColor Yellow
Write-Host "  1. Check logs: docker logs -f rag-service"
Write-Host "  2. Restart services: docker-compose restart"
Write-Host "  3. Check .env file: RAG_SERVICE_URL should be set correctly"
Write-Host "  4. Verify network: docker network ls"
Write-Host ""
Write-Host "More help: Check README.md Troubleshooting section"
