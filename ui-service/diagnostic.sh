#!/bin/bash
# RAG UI Service - Diagnostic Script (Bash/Linux/macOS)
# Run this to diagnose common issues

echo -e "\033[36m🔍 RAG UI Service Diagnostic Tool\033[0m"
echo "================================="
echo ""

API_BASE="http://localhost:8000"

# 1. Check if UI service is running
echo -e "\033[33m1️⃣  Checking UI Service...\033[0m"
if curl -s "$API_BASE/health" > /dev/null; then
    echo -e "\033[32m✅ UI Service is running at $API_BASE\033[0m"
else
    echo -e "\033[31m❌ UI Service is NOT running at $API_BASE\033[0m"
    echo -e "\033[33m   Start it with: uvicorn app.main:app --reload\033[0m"
    exit 1
fi

# 2. Get configuration
echo ""
echo -e "\033[33m2️⃣  Checking Configuration...\033[0m"
CONFIG=$(curl -s "$API_BASE/api/debug/config")
if [ $? -eq 0 ]; then
    echo -e "\033[32m✅ Configuration loaded\033[0m"
    echo -e "\033[36m   RAG URL: $(echo $CONFIG | grep -o '"rag_url":"[^"]*' | cut -d'"' -f4)\033[0m"
    echo -e "\033[36m   Sessions: $(echo $CONFIG | grep -o '"sessions_count":[0-9]*' | cut -d':' -f2)\033[0m"
else
    echo -e "\033[31m❌ Cannot load configuration\033[0m"
fi

# 3. Check service status
echo ""
echo -e "\033[33m3️⃣  Checking Backend Services...\033[0m"
STATUS=$(curl -s "$API_BASE/api/services-status")

echo "$STATUS" | jq -r '.services | to_entries[] | if .value.status == "healthy" then "\u001b[32m✅ \(.key) - Healthy\u001b[0m" else "\u001b[31m❌ \(.key) - OFFLINE at \(.value.url)\u001b[0m" end' 2>/dev/null || echo -e "\033[31m❌ Cannot parse service status\033[0m"

# 4. Test RAG connection
echo ""
echo -e "\033[33m4️⃣  Testing RAG Service Connection...\033[0m"
TEST_RESULT=$(curl -s -X POST "$API_BASE/api/debug/test-rag" -d "question=test")

if echo "$TEST_RESULT" | grep -q '"status":"success"'; then
    echo -e "\033[32m✅ RAG Service is working!\033[0m"
    ANSWER=$(echo "$TEST_RESULT" | grep -o '"answer":"[^"]*' | cut -d'"' -f4 | head -c 100)
    if [ ! -z "$ANSWER" ]; then
        echo -e "\033[36m   Answer: $ANSWER...\033[0m"
    fi
else
    echo -e "\033[31m❌ RAG Service Error\033[0m"
    ERROR=$(echo "$TEST_RESULT" | grep -o '"error":"[^"]*' | cut -d'"' -f4)
    DETAILS=$(echo "$TEST_RESULT" | grep -o '"details":"[^"]*' | cut -d'"' -f4)
    echo -e "\033[31m   Error: $ERROR\033[0m"
    echo -e "\033[33m   Details: $DETAILS\033[0m"
fi

# 5. Summary
echo ""
echo -e "\033[36m📋 Summary\033[0m"
echo "=========="

# Check Docker
if command -v docker &> /dev/null; then
    if docker ps > /dev/null 2>&1; then
        echo -e "\033[32m✅ Docker is running\033[0m"
        echo ""
        echo -e "\033[33mRunning containers:\033[0m"
        docker ps --format "table {{.Names}}\t{{.Status}}" | head -10
    else
        echo -e "\033[33m⚠️  Docker may not be running\033[0m"
    fi
else
    echo -e "\033[33m⚠️  Docker is not installed\033[0m"
fi

echo ""
echo -e "\033[33m🔧 Quick Tips:\033[0m"
echo "  1. Check logs: docker logs -f rag-service"
echo "  2. Restart services: docker-compose restart"
echo "  3. Check .env file: RAG_SERVICE_URL should be set correctly"
echo "  4. Verify network: docker network ls"
echo ""
echo "More help: Check README.md Troubleshooting section"
