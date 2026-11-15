#!/usr/bin/env bash
# =============================================================================
# Sends exactly TWO requests to your deployed API: GET /health, then POST /tickets.
# It does not load-test. Use it right after deployment to see that the API works.
#
# Usage:
#   ./scripts/invoke_api.sh https://abc123.execute-api.ap-south-1.amazonaws.com
# =============================================================================
set -euo pipefail

API_URL="${1:-}"
if [[ -z "$API_URL" ]]; then
  echo "Usage: $0 <API_URL>   (the ApiUrl output printed by deploy.sh)"
  exit 1
fi
API_URL="${API_URL%/}"

echo "1) GET $API_URL/health"
curl -sS -w "\nHTTP status: %{http_code}  total time: %{time_total}s\n" "$API_URL/health"

echo
echo "2) POST $API_URL/tickets   (synthetic data only)"
curl -sS -w "\nHTTP status: %{http_code}  total time: %{time_total}s\n" \
  -X POST "$API_URL/tickets" \
  -H "Content-Type: application/json" \
  -d '{"subject": "Order delayed", "description": "My order has not arrived yet.", "customerEmail": "student@example.com"}'
