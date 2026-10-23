#!/usr/bin/env bash
# BFF -> load balancer -> gunicorn/Django origin-signature integration test (docs/deployment.md, WP7f).
# Unit vectors prove both implementations agree on paper; this proves the bytes Next puts on the
# wire are the bytes gunicorn hands Django (RAW_URI), for awkward paths and queries.
#
# Usage: ci/integration/run.sh            (expects images pglive-api:local and pglive-web:local)
#        API_IMAGE=... WEB_IMAGE=... ci/integration/run.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"
COMPOSE=(docker compose -f docker-compose.yml)
WEB=http://localhost:18300
EDGE=http://localhost:18301
CLIENT_IP=203.0.113.77
failures=0

cleanup() { "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

psql_db() { "${COMPOSE[@]}" exec -T db psql -U postgres -v ON_ERROR_STOP=1 "$@"; }
check() { # name expected actual
  if [[ "$2" == "$3" ]]; then echo "ok   $1"; else echo "FAIL $1: expected '$2', got '$3'"; failures=$((failures + 1)); fi
}

echo "--- database with the production role model"
"${COMPOSE[@]}" up -d --wait db
psql_db -d postgres -v migration_password=migpw -v app_password=apppw -v db_name=pg_platform \
  -f - < "$ROOT/infra/sql/roles-1-roles.sql" >/dev/null
"${COMPOSE[@]}" run --rm --no-deps -e DB_USER=migration_user -e DB_PASSWORD=migpw api \
  python manage.py migrate --noinput >/dev/null
psql_db -d pg_platform -f - < "$ROOT/infra/sql/roles-2-grants.sql" >/dev/null
"${COMPOSE[@]}" run --rm --no-deps api python manage.py check_db_roles

echo "--- servers"
"${COMPOSE[@]}" up -d api edge-api web
for _ in $(seq 1 60); do curl -fs "$WEB/api/health" >/dev/null 2>&1 && break; sleep 1; done
# web's health route never touches Django by design (its docstring: "a Django outage never restarts
# this service"), so it says nothing about gunicorn. start-api.sh now runs `manage.py check --deploy`
# before gunicorn binds its port, which is slow enough that the checks below used to start racing it
# and see 502s from edge-api. Wait for Django's own readiness through the edge before testing anything.
for _ in $(seq 1 60); do curl -fs "$EDGE/health/ready/" >/dev/null 2>&1 && break; sleep 1; done

status() { curl -s -o /dev/null -w '%{http_code}' -H "x-pglive-client-ip: $CLIENT_IP" "$@"; }

echo "--- signed requests through the BFF are accepted (never 400)"
check "plain GET" 200 "$(status "$WEB/api/v1/support/")"
check "raw query: encoded space, plus, repeated and empty params" 200 \
  "$(status "$WEB/api/v1/support/?q=a%20b+c&p=1&p=2&empty=")"
check "percent-encoded slash in path" 404 "$(status "$WEB/api/v1/support%2Fx/")"
check "UTF-8 Telugu path segment" 404 "$(status "$WEB/api/v1/tags/%E0%B0%A4%E0%B1%86%E0%B0%B2%E0%B1%81%E0%B0%97%E0%B1%81/")"
check "missing trailing slash (verified, then Django's APPEND_SLASH redirect)" 301 "$(status "$WEB/api/v1/support")"

echo "--- the audit-relevant IP is the browser's, not the BFF's"
check "contact form accepted" 201 "$(status -X POST -H 'content-type: application/json' \
  -d '{"name":"Ravi Kumar","email":"ravi@example.com","message":"Integration test message for the PG."}' \
  "$WEB/api/v1/public/contact/")"
stored_ip=$(psql_db -d pg_platform -At -c "SELECT host(ip_address) FROM contact_messages ORDER BY created_at DESC LIMIT 1")
check "stored client IP" "$CLIENT_IP" "$stored_ip"

echo "--- forged origin headers sent straight at the edge are rejected"
check "forged signature" 400 "$(curl -s -o /dev/null -w '%{http_code}' \
  -H 'X-PGLive-Origin-IP: 198.51.100.1' -H "X-PGLive-Origin-Ts: $(date +%s)" -H 'X-PGLive-Origin-Sig: 00' \
  "$EDGE/api/v1/support/")"
check "direct call without origin headers" 200 "$(curl -s -o /dev/null -w '%{http_code}' "$EDGE/api/v1/support/")"

echo "--- web: apex redirect, CSP on real responses (WP11, WP17)"
# curl can exit non-zero here (e.g. it stops reading a streamed body) after writing the headers.
headers() { curl -s -o /dev/null -D - "$@" | tr -d '\r' || true; }
has() { printf '%s\n' "$1" | grep -qi "$2" && echo yes || echo no; }
apex=$(headers -H 'Host: pglive.in' "$WEB/features?x=1")
check "apex 301" "301" "$(printf '%s\n' "$apex" | awk 'NR==1{print $2}')"
check "apex target" yes "$(has "$apex" '^location: https://www.pglive.in/features?x=1$')"
for path in / /features /login /no-such-page; do
  h=$(headers -H 'Host: www.pglive.in' -H 'cookie: pg_session=1' "$WEB$path")
  check "CSP report-only on $path" yes "$(has "$h" "^content-security-policy-report-only: default-src 'self'")"
done
check "no Set-Cookie on anonymous marketing home" no "$(has "$(headers -H 'Host: www.pglive.in' "$WEB/")" '^set-cookie:')"
check "404 status for unknown page" "404" \
  "$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: www.pglive.in' -H 'cookie: pg_session=1' "$WEB/no-such-page")"

echo "--- Razorpay webhook straight at the API (as Razorpay sends it), stored by the runtime role"
body='{"event":"subscription.charged","created_at":1760000000,"payload":{"subscription":{"entity":{"id":"sub_integration_unknown"}}}}'
sig="$(printf '%s' "$body" | openssl dgst -sha256 -hmac integration-webhook-secret | awk '{print $NF}')"
hook() { curl -s -o /dev/null -w '%{http_code}' -X POST -H 'content-type: application/json' \
  -H "X-Razorpay-Signature: $1" -H "X-Razorpay-Event-Id: $2" -d "$body" "$EDGE/api/v1/subscriptions/webhook/"; }
check "webhook with a valid signature" 200 "$(hook "$sig" evt_integration_1)"
check "webhook redelivery (same event id)" 200 "$(hook "$sig" evt_integration_1)"
check "webhook with a bad signature is rejected" 400 "$(hook 00 evt_integration_2)"
check "event stored once, by app_user, with its outcome" "1|unknown_subscription" \
  "$(psql_db -d pg_platform -At -c "SELECT count(*) || '|' || max(outcome) FROM razorpay_webhook_events WHERE event_id = 'evt_integration_1'")"
check "rejected event not stored" 0 \
  "$(psql_db -d pg_platform -At -c "SELECT count(*) FROM razorpay_webhook_events WHERE event_id = 'evt_integration_2'")"

echo "--- readiness (gunicorn exposes RAW_URI)"
ready=$(curl -s "$EDGE/health/ready/")
check "readiness" '{"status": "ok", "checks": {"database": "ok", "raw_uri": "ok"}}' "$ready"

if (( failures )); then
  echo "$failures check(s) failed"; "${COMPOSE[@]}" logs api web --tail 40; exit 1
fi
echo "All integration checks passed."
