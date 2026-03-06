# RAG UI Service - API Testing Examples (PowerShell)
# Usage: .\api-examples.ps1

$API_BASE = "http://localhost:8000"

Write-Host "=== RAG UI Service API Examples ===" -ForegroundColor Cyan
Write-Host ""

# 1. Health Check
Write-Host "1. Health Check" -ForegroundColor Green
Invoke-WebRequest -Uri "$API_BASE/health" -Method Get | ConvertTo-Json | Write-Host
Write-Host ""

# 2. Create New Session
Write-Host "2. Create New Session" -ForegroundColor Green
$response = Invoke-WebRequest -Uri "$API_BASE/api/session/new" -Method Post
$session = ($response.Content | ConvertFrom-Json).session_id
Write-Host "Session ID: $session"
Write-Host ""

# 3. Get Services Status
Write-Host "3. Get Services Status" -ForegroundColor Green
Invoke-WebRequest -Uri "$API_BASE/api/services-status" -Method Get | ConvertTo-Json | Write-Host
Write-Host ""

# 4. Upload a File
Write-Host "4. Upload Document" -ForegroundColor Green
$sampleContent = "Machine learning is a subset of artificial intelligence`nthat focuses on developing algorithms that can learn from data."
$sampleContent | Out-File -FilePath "sample.txt"

$form = @{
    file = Get-Item -Path "sample.txt"
    session_id = $session
}
Invoke-WebRequest -Uri "$API_BASE/upload" -Method Post -Form $form | ConvertTo-Json | Write-Host
Write-Host ""

# 5. Get Documents List
Write-Host "5. Get Documents List" -ForegroundColor Green
Invoke-WebRequest -Uri "$API_BASE/api/documents" -Method Get | ConvertTo-Json | Write-Host
Write-Host ""

# 6. Ask a Question
Write-Host "6. Ask a Question" -ForegroundColor Green
$body = "question=What is machine learning?&session_id=$session"
Invoke-WebRequest -Uri "$API_BASE/ask" -Method Post -Body $body -ContentType "application/x-www-form-urlencoded" | ConvertTo-Json | Write-Host
Write-Host ""

# 7. Get Session History
Write-Host "7. Get Session History" -ForegroundColor Green
Invoke-WebRequest -Uri "$API_BASE/api/session/$session/history" -Method Get | ConvertTo-Json | Write-Host
Write-Host ""

# 8. List All Sessions
Write-Host "8. List All Sessions" -ForegroundColor Green
Invoke-WebRequest -Uri "$API_BASE/api/sessions" -Method Get | ConvertTo-Json | Write-Host
Write-Host ""

# 9. Get Specific Session
Write-Host "9. Get Specific Session" -ForegroundColor Green
Invoke-WebRequest -Uri "$API_BASE/api/session/$session" -Method Get | ConvertTo-Json | Write-Host
Write-Host ""

# 10. Create Another Session
Write-Host "10. Create Another Session" -ForegroundColor Green
$response2 = Invoke-WebRequest -Uri "$API_BASE/api/session/new" -Method Post
$session2 = ($response2.Content | ConvertFrom-Json).session_id
Write-Host "New Session ID: $session2"
Write-Host ""

Write-Host "=== Examples Complete ===" -ForegroundColor Cyan
Write-Host "Session 1: $session"
Write-Host "Session 2: $session2"
Write-Host ""
Write-Host "Optional: Delete a session"
Write-Host "Invoke-WebRequest -Uri '$API_BASE/api/session/$session' -Method Delete"

# Cleanup
Remove-Item "sample.txt" -Force
