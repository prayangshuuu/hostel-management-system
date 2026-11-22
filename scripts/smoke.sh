#!/usr/bin/env bash
# ==============================================================================
# Smoke Test Script for Hostel Management System API
# ==============================================================================
# Verifies:
#   1. GET  /api/v1/health
#   2. POST /api/v1/auth/login (seeded administrator)
#   3. GET  /api/v1/hostels (authenticated)
#   4. GET  /api/v1/dashboard/summary (authenticated admin/warden)
# ==============================================================================

set -eo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@hostel.example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-AdminPass123}"

# Styling
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

PASSED_TESTS=0
TOTAL_TESTS=4

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_step() {
    echo -e "\n${BOLD}==> Step $1: $2${NC}"
}

log_pass() {
    echo -e "${GREEN}✓ PASS:${NC} $1"
    PASSED_TESTS=$((PASSED_TESTS + 1))
}

log_fail() {
    echo -e "${RED}✗ FAIL:${NC} $1" >&2
}

# Helper to extract JSON fields portably (supports jq, python3, or fallback regex)
extract_json_field() {
    local json="$1"
    local field="$2"
    if command -v jq >/dev/null 2>&1; then
        echo "$json" | jq -r ".${field} // empty"
    elif command -v python3 >/dev/null 2>&1; then
        echo "$json" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('${field}', ''))" 2>/dev/null || true
    else
        echo "$json" | grep -o "\"${field}\":\"[^\"]*\"" | head -n1 | cut -d'"' -f4
    fi
}

echo -e "${BOLD}======================================================${NC}"
echo -e "${BOLD}   Hostel Management System API - Smoke Test Suite    ${NC}"
echo -e "${BOLD}======================================================${NC}"
log_info "Target Host:    ${BASE_URL}"
log_info "Admin Identity: ${ADMIN_EMAIL}"

# ------------------------------------------------------------------------------
# Test 1: Health Check Endpoint
# ------------------------------------------------------------------------------
log_step "1/4" "Testing Health Check Endpoint (/api/v1/health)"
HEALTH_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${BASE_URL}/api/v1/health" \
    -H "Accept: application/json")

HEALTH_HTTP_CODE=$(echo "$HEALTH_RESPONSE" | tail -n1)
HEALTH_BODY=$(echo "$HEALTH_RESPONSE" | sed '$d')

if [ "$HEALTH_HTTP_CODE" -eq 200 ]; then
    HEALTH_STATUS=$(extract_json_field "$HEALTH_BODY" "status")
    DB_STATUS=$(extract_json_field "$HEALTH_BODY" "database")
    log_info "Response: HTTP ${HEALTH_HTTP_CODE} | status='${HEALTH_STATUS}', database='${DB_STATUS}'"
    if [ "$HEALTH_STATUS" = "ok" ]; then
        log_pass "Health endpoint responded with HTTP 200 and healthy status."
    else
        log_fail "Health endpoint returned 200 but status is not 'ok': ${HEALTH_BODY}"
        exit 1
    fi
else
    log_fail "Health endpoint returned HTTP ${HEALTH_HTTP_CODE}: ${HEALTH_BODY}"
    exit 1
fi

# ------------------------------------------------------------------------------
# Test 2: Admin Login
# ------------------------------------------------------------------------------
log_step "2/4" "Testing Admin Authentication (/api/v1/auth/login)"
LOGIN_PAYLOAD=$(printf '{"email":"%s","password":"%s"}' "$ADMIN_EMAIL" "$ADMIN_PASSWORD")

LOGIN_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -d "$LOGIN_PAYLOAD")

LOGIN_HTTP_CODE=$(echo "$LOGIN_RESPONSE" | tail -n1)
LOGIN_BODY=$(echo "$LOGIN_RESPONSE" | sed '$d')

if [ "$LOGIN_HTTP_CODE" -eq 200 ]; then
    ACCESS_TOKEN=$(extract_json_field "$LOGIN_BODY" "access_token")
    if [ -n "$ACCESS_TOKEN" ]; then
        log_pass "Successfully authenticated admin user; received valid JWT Bearer token."
    else
        log_fail "Login succeeded with 200 but access_token was missing in payload: ${LOGIN_BODY}"
        exit 1
    fi
else
    log_fail "Admin login failed with HTTP ${LOGIN_HTTP_CODE}: ${LOGIN_BODY}"
    echo -e "${YELLOW}[TIP] If database is newly initialized, ensure seed data is loaded via:${NC}"
    echo "      docker compose exec api python scripts/seed.py"
    echo "      or: uv run python scripts/seed.py"
    exit 1
fi

# ------------------------------------------------------------------------------
# Test 3: List Hostels (Authenticated)
# ------------------------------------------------------------------------------
log_step "3/4" "Testing Hostel Listing Endpoint (/api/v1/hostels)"
HOSTELS_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${BASE_URL}/api/v1/hostels" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Accept: application/json")

HOSTELS_HTTP_CODE=$(echo "$HOSTELS_RESPONSE" | tail -n1)
HOSTELS_BODY=$(echo "$HOSTELS_RESPONSE" | sed '$d')

if [ "$HOSTELS_HTTP_CODE" -eq 200 ]; then
    log_pass "Hostels endpoint responded with HTTP 200."
    log_info "Hostels payload sample: $(echo "$HOSTELS_BODY" | cut -c1-150)..."
else
    log_fail "Hostels endpoint returned HTTP ${HOSTELS_HTTP_CODE}: ${HOSTELS_BODY}"
    exit 1
fi

# ------------------------------------------------------------------------------
# Test 4: Executive Dashboard Summary (Authenticated Admin)
# ------------------------------------------------------------------------------
log_step "4/4" "Testing Dashboard Summary Endpoint (/api/v1/dashboard/summary)"
DASHBOARD_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${BASE_URL}/api/v1/dashboard/summary" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Accept: application/json")

DASHBOARD_HTTP_CODE=$(echo "$DASHBOARD_RESPONSE" | tail -n1)
DASHBOARD_BODY=$(echo "$DASHBOARD_RESPONSE" | sed '$d')

if [ "$DASHBOARD_HTTP_CODE" -eq 200 ]; then
    log_pass "Dashboard summary endpoint responded with HTTP 200."
    log_info "Dashboard metrics sample: $(echo "$DASHBOARD_BODY" | cut -c1-150)..."
else
    log_fail "Dashboard summary endpoint returned HTTP ${DASHBOARD_HTTP_CODE}: ${DASHBOARD_BODY}"
    exit 1
fi

# ------------------------------------------------------------------------------
# Test Summary
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}======================================================${NC}"
echo -e "${GREEN}${BOLD}SMOKE TEST SUCCESSFUL: ${PASSED_TESTS}/${TOTAL_TESTS} tests passed!${NC}"
echo -e "${BOLD}======================================================${NC}"
exit 0
