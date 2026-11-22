#!/usr/bin/env bash
# ==============================================================================
# Smoke Test Script for Hostel Management System API
# ==============================================================================
set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
BASE_URL="${BASE_URL%/}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@hostel.example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-AdminPass123}"

echo "Starting smoke tests against ${BASE_URL}..."

# Helper function to extract a field from a JSON string
extract_json_field() {
    local json="$1"
    local field="$2"
    if command -v python3 >/dev/null 2>&1; then
        python3 -c "import sys, json; print(json.loads(sys.argv[1]).get(sys.argv[2], ''))" "$json" "$field"
    elif command -v python >/dev/null 2>&1; then
        python -c "import sys, json; print(json.loads(sys.argv[1]).get(sys.argv[2], ''))" "$json" "$field"
    elif command -v jq >/dev/null 2>&1; then
        echo "$json" | jq -r ".${field} // empty"
    else
        echo "$json" | sed -n 's/.*"'"$field"'"[ ]*:[ ]*"\([^"]*\)".*/\1/p'
    fi
}

# Test 1: GET /api/v1/health -> assert HTTP 200 and status == "ok" (with retry loop for container warmup)
echo "==> [1/4] Testing health check endpoint: GET ${BASE_URL}/api/v1/health"
MAX_HEALTH_RETRIES=30
attempt=0
HTTP_CODE="000"
BODY=""

while [ "$attempt" -lt "$MAX_HEALTH_RETRIES" ]; do
    RESP=$(curl -sS -w "\n%{http_code}" "${BASE_URL}/api/v1/health" 2>/dev/null || true)
    HTTP_CODE=$(echo "$RESP" | tail -n 1)
    BODY=$(echo "$RESP" | sed '$d')

    if [ "$HTTP_CODE" = "200" ]; then
        break
    fi

    attempt=$((attempt + 1))
    sleep 1
done

if [ "$HTTP_CODE" != "200" ]; then
    echo "ERROR: Health check failed after ${MAX_HEALTH_RETRIES} attempts with HTTP ${HTTP_CODE}: ${BODY}" >&2
    exit 1
fi

STATUS=$(extract_json_field "$BODY" "status")
if [ "$STATUS" != "ok" ]; then
    echo "ERROR: Health check expected status 'ok', received '${STATUS}': ${BODY}" >&2
    exit 1
fi
echo "✓ Health check passed (HTTP 200, status=ok)"

# Test 2: POST /api/v1/auth/login with seeded admin -> extract access_token
echo "==> [2/4] Testing admin authentication: POST ${BASE_URL}/api/v1/auth/login"
LOGIN_PAYLOAD=$(printf '{"email":"%s","password":"%s"}' "$ADMIN_EMAIL" "$ADMIN_PASSWORD")
RESP=$(curl -sS -w "\n%{http_code}" \
    -H "Content-Type: application/json" \
    -d "$LOGIN_PAYLOAD" \
    "${BASE_URL}/api/v1/auth/login" || true)
HTTP_CODE=$(echo "$RESP" | tail -n 1)
BODY=$(echo "$RESP" | sed '$d')

if [ "$HTTP_CODE" != "200" ]; then
    echo "ERROR: Admin authentication failed with HTTP ${HTTP_CODE}: ${BODY}" >&2
    exit 1
fi

ACCESS_TOKEN=$(extract_json_field "$BODY" "access_token")
if [ -z "$ACCESS_TOKEN" ]; then
    echo "ERROR: access_token not found in login response: ${BODY}" >&2
    exit 1
fi
echo "✓ Authentication passed (HTTP 200, access token acquired)"

# Test 3: GET /api/v1/hostels with Bearer token -> assert HTTP 200
echo "==> [3/4] Testing hostels endpoint: GET ${BASE_URL}/api/v1/hostels"
RESP=$(curl -sS -w "\n%{http_code}" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    "${BASE_URL}/api/v1/hostels" || true)
HTTP_CODE=$(echo "$RESP" | tail -n 1)
BODY=$(echo "$RESP" | sed '$d')

if [ "$HTTP_CODE" != "200" ]; then
    echo "ERROR: Hostels request failed with HTTP ${HTTP_CODE}: ${BODY}" >&2
    exit 1
fi
echo "✓ Hostels endpoint passed (HTTP 200)"

# Test 4: GET /api/v1/dashboard/summary with Bearer token -> assert HTTP 200
echo "==> [4/4] Testing dashboard summary endpoint: GET ${BASE_URL}/api/v1/dashboard/summary"
RESP=$(curl -sS -w "\n%{http_code}" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    "${BASE_URL}/api/v1/dashboard/summary" || true)
HTTP_CODE=$(echo "$RESP" | tail -n 1)
BODY=$(echo "$RESP" | sed '$d')

if [ "$HTTP_CODE" != "200" ]; then
    echo "ERROR: Dashboard summary request failed with HTTP ${HTTP_CODE}: ${BODY}" >&2
    exit 1
fi
echo "✓ Dashboard summary endpoint passed (HTTP 200)"

echo "=========================================================="
echo "SUCCESS: All smoke tests passed successfully against ${BASE_URL}!"
echo "=========================================================="
