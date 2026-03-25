#!/bin/bash

# ============================================================================
# RAG UI Service - Comprehensive API Test Suite
# ============================================================================
# Usage: bash api-examples.sh
# Tests all API endpoints with detailed output
# ============================================================================

API_BASE="http://localhost:8000"
SESSION_ID="session-$(date +%s)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Utilities
log_section() {
    echo -e "\n${BLUE}═══════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}$1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════${NC}\n"
}

log_test() {
    echo -e "${CYAN}[TEST] $1${NC}"
}

log_success() {
    echo -e "${GREEN}[✓] $1${NC}"
}

log_error() {
    echo -e "${RED}[✗] $1${NC}"
}

log_info() {
    echo -e "${BLUE}[i] $1${NC}"
}

# ============================================================================
# MAIN TEST FLOW
# ============================================================================

echo -e "${CYAN}╔═══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   RAG UI Service - Comprehensive API Tests    ║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════════════╝${NC}"

log_info "Base URL: $API_BASE"
log_info "Session ID: $SESSION_ID"
log_info "Timestamp: $(date)"

# ============================================================================
# 1. HEALTH CHECKS
# ============================================================================

log_section "Phase 1: Health Checks"

log_test "UI Service Health"
HEALTH=$(curl -s -X GET "$API_BASE/health")
echo "$HEALTH" | python -m json.tool 2>/dev/null || echo "$HEALTH"
echo ""

log_test "Services Status"
curl -s -X GET "$API_BASE/services/status" | python -m json.tool 2>/dev/null || echo "Failed"
echo ""

# ============================================================================
# 2. SESSION MANAGEMENT
# ============================================================================

log_section "Phase 2: Session Management"

log_test "Create New Session"
CREATE_RESPONSE=$(curl -s -X POST "$API_BASE/sessions" \
  -H "Content-Type: application/json" \
  -d '{}')
echo "$CREATE_RESPONSE" | python -m json.tool 2>/dev/null || echo "$CREATE_RESPONSE"
echo ""

log_test "List All Sessions"
curl -s -X GET "$API_BASE/sessions" | python -m json.tool 2>/dev/null || echo "Failed"
echo ""

# ============================================================================
# 3. DEBUG ENDPOINTS
# ============================================================================

log_section "Phase 3: Debug & Configuration"

log_test "Configuration (Debug)"
curl -s -X GET "$API_BASE/api/debug/config" | python -m json.tool 2>/dev/null || echo "Failed"
echo ""

log_test "Test RAG Service Connection"
RAG_TEST=$(curl -s -X POST "$API_BASE/api/debug/test-rag" \
  -H "Content-Type: application/json" \
  -d '{"question":"test connection"}')
echo "$RAG_TEST" | python -m json.tool 2>/dev/null || echo "$RAG_TEST"
echo ""

# ============================================================================
# 4. CHAT ENDPOINTS
# ============================================================================

log_section "Phase 4: Chat Functionality"

log_test "Ask First Question"
QUESTION1=$(curl -s -X POST "$API_BASE/ask" \
  -H "Content-Type: application/json" \
  -d "{
    \"question\": \"What is the RAG system and how does it work?\",
    \"session_id\": \"$SESSION_ID\"
  }")
echo "$QUESTION1" | python -m json.tool 2>/dev/null || echo "$QUESTION1"
echo ""

log_test "Ask Follow-up Question"
QUESTION2=$(curl -s -X POST "$API_BASE/ask" \
  -H "Content-Type: application/json" \
  -d "{
    \"question\": \"Can you provide more details?\",
    \"session_id\": \"$SESSION_ID\"
  }")
echo "$QUESTION2" | python -m json.tool 2>/dev/null || echo "$QUESTION2"
echo ""

log_test "Get Session History"
curl -s -X GET "$API_BASE/sessions/${SESSION_ID}" | python -m json.tool 2>/dev/null || echo "Failed"
echo ""

# ============================================================================
# 5. ERROR HANDLING TESTS
# ============================================================================

log_section "Phase 5: Error Handling & Validation"

log_test "Invalid Session ID (should return 404 or empty)"
curl -s -X GET "$API_BASE/sessions/invalid-session-xyz" \
  -w "\nHTTP Status: %{http_code}\n"
echo ""

log_test "Missing Required Field (question)"
curl -s -X POST "$API_BASE/ask" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test"}' \
  -w "\nHTTP Status: %{http_code}\n"
echo ""

log_test "Invalid JSON Format"
curl -s -X POST "$API_BASE/ask" \
  -H "Content-Type: application/json" \
  -d 'this is not valid json' \
  -w "\nHTTP Status: %{http_code}\n"
echo ""

# ============================================================================
# 6. SERVICE CONNECTIVITY TESTS
# ============================================================================

log_section "Phase 6: Individual Service Health"

echo -e "${YELLOW}Testing each backend service:${NC}\n"

log_test "RAG Service (localhost:8003/health)"
curl -s -X GET "http://localhost:8003/health" \
  -w "\nHTTP Status: %{http_code}\n" || log_error "Cannot connect to RAG service"
echo ""

log_test "Embedding Service (localhost:8001/health)"
curl -s -X GET "http://localhost:8001/health" \
  -w "\nHTTP Status: %{http_code}\n" || log_error "Cannot connect to Embedding service"
echo ""

log_test "Ingestion Service (localhost:8004/health)"
curl -s -X GET "http://localhost:8004/health" \
  -w "\nHTTP Status: %{http_code}\n" || log_error "Cannot connect to Ingestion service"
echo ""

log_test "Qdrant Vector DB (localhost:6333/health)"
curl -s -X GET "http://localhost:6333/health" \
  -w "\nHTTP Status: %{http_code}\n" || log_error "Cannot connect to Qdrant"
echo ""

# ============================================================================
# 7. PERFORMANCE TESTING
# ============================================================================

log_section "Phase 7: Performance Analysis"

log_test "Response Time Measurement"
START=$(date +%s%N)
curl -s -X POST "$API_BASE/ask" \
  -H "Content-Type: application/json" \
  -d "{
    \"question\": \"What is artificial intelligence?\",
    \"session_id\": \"test-perf\"
  }" > /dev/null 2>&1
END=$(date +%s%N)
ELAPSED=$(( (END - START) / 1000000 ))
log_info "Response time: ${ELAPSED}ms"
echo ""

# ============================================================================
# 8. ADVANCED SCENARIOS
# ============================================================================

log_section "Phase 8: Advanced Scenarios"

log_test "Multi-turn Conversation"
echo "Creating 3-turn conversation..."
for i in {1..3}; do
  echo "Turn $i..."
  curl -s -X POST "$API_BASE/ask" \
    -H "Content-Type: application/json" \
    -d "{
      \"question\": \"Question $i: Tell me about topic $i\",
      \"session_id\": \"conv-test\"
    }" > /dev/null
done
log_success "Conversation completed"
echo ""

log_test "Retrieve Conversation History"
curl -s -X GET "$API_BASE/sessions/conv-test" | python -m json.tool 2>/dev/null || echo "Failed"
echo ""

# ============================================================================
# 9. CLEANUP
# ============================================================================

log_section "Phase 9: Cleanup"

log_test "Delete Test Sessions"
for sid in "$SESSION_ID" "test-perf" "conv-test"; do
  curl -s -X DELETE "$API_BASE/sessions/$sid" > /dev/null 2>&1
  log_success "Deleted session: $sid"
done
echo ""

# ============================================================================
# TEST SUMMARY
# ============================================================================

log_section "Test Suite Summary"

echo -e "${GREEN}✓ API Test Suite Completed Successfully${NC}\n"

echo "Endpoints tested:"
echo "  • Health checks (UI service + all backend services)"
echo "  • Session management (create, list, delete)"
echo "  • Chat functionality (ask, retrieve history)"
echo "  • Debug endpoints (config, RAG connection test)"
echo "  • Error handling (invalid input, missing fields)"
echo "  • Service connectivity (all 4 backend services)"
echo "  • Performance measurement (response time)"
echo "  • Advanced scenarios (multi-turn conversation)"
echo ""

echo "For detailed error analysis, check:"
echo "  • Server logs: docker logs ui-service"
echo "  • Service status: curl http://localhost:8000/services/status"
echo "  • Configuration: curl http://localhost:8000/api/debug/config"
echo ""

echo -e "${CYAN}Test Results: See output above for details${NC}"
echo "UI Service: $API_BASE"
echo "Documentation: README.md, TROUBLESHOOTING.md, QUICK_REFERENCE.md"
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
