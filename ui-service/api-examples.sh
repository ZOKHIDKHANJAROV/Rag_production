#!/bin/bash
# RAG UI Service - API Testing Examples
# Usage: source api-examples.sh

API_BASE="http://localhost:8000"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== RAG UI Service API Examples ===${NC}\n"

# 1. Health Check
echo -e "${GREEN}1. Health Check${NC}"
curl -s "$API_BASE/health" | json_pp
echo ""

# 2. Create New Session
echo -e "${GREEN}2. Create New Session${NC}"
SESSION=$(curl -s -X POST "$API_BASE/api/session/new" | grep -o '"session_id":"[^"]*' | cut -d'"' -f4)
echo "Session ID: $SESSION"
echo ""

# 3. Get Services Status
echo -e "${GREEN}3. Get Services Status${NC}"
curl -s "$API_BASE/api/services-status" | json_pp
echo ""

# 4. Upload a File (example)
echo -e "${GREEN}4. Upload Document (create sample first)${NC}"
cat > sample.txt << 'EOF'
Machine learning is a subset of artificial intelligence
that focuses on developing algorithms that can learn from data.
EOF
curl -s -X POST "$API_BASE/upload" \
  -F "file=@sample.txt" \
  -F "session_id=$SESSION" | json_pp
echo ""

# 5. Get Documents List
echo -e "${GREEN}5. Get Documents List${NC}"
curl -s "$API_BASE/api/documents" | json_pp
echo ""

# 6. Ask a Question
echo -e "${GREEN}6. Ask a Question${NC}"
curl -s -X POST "$API_BASE/ask" \
  -d "question=What is machine learning?" \
  -d "session_id=$SESSION" | json_pp
echo ""

# 7. Get Session History
echo -e "${GREEN}7. Get Session History${NC}"
curl -s "$API_BASE/api/session/$SESSION/history" | json_pp
echo ""

# 8. List All Sessions
echo -e "${GREEN}8. List All Sessions${NC}"
curl -s "$API_BASE/api/sessions" | json_pp
echo ""

# 9. Get Specific Session
echo -e "${GREEN}9. Get Specific Session${NC}"
curl -s "$API_BASE/api/session/$SESSION" | json_pp
echo ""

# 10. Create Another Session and Compare
echo -e "${GREEN}10. Create Another Session${NC}"
SESSION2=$(curl -s -X POST "$API_BASE/api/session/new" | grep -o '"session_id":"[^"]*' | cut -d'"' -f4)
echo "New Session ID: $SESSION2"
echo ""

echo -e "${BLUE}=== Examples Complete ===${NC}"
echo "Session 1: $SESSION"
echo "Session 2: $SESSION2"
echo ""
echo "Optional: Delete a session"
echo "curl -s -X DELETE \"$API_BASE/api/session/$SESSION\""
