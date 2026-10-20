#!/usr/bin/env bash
# Phase 5: global external Application Load Balancer, certificates, Cloud Armor, IAP for /admin/.
#   infra/40-edge.sh prod
# Production only (staging has no LB: testers use the run.app URLs). After it runs it prints the IP and the DNS
# records to enter at GoDaddy. Certificates are issued through DNS authorization BEFORE cutover, so there is
# no window with a broken certificate.
# STATUS: not yet run against a real project (see env.sh).
set -euo pipefail
source "$(dirname "$0")/env.sh" "${1:-prod}"
[[ "$ENVIRONMENT" == prod ]] || { echo "edge is production only" >&2; exit 1; }
g() { gcloud --project "$PROJECT" "$@"; }
HSTS_MAX_AGE="${HSTS_MAX_AGE:-300}"          # ramp: 300 -> 86400 -> 604800 -> 31536000 (re-run to change)
HSTS_FLAGS="max-age=$HSTS_MAX_AGE"           # add ;includeSubDomains only after every subdomain is HTTPS-only
HEADERS=(--custom-request-header='X-PGLive-Client-IP:{client_ip_address}'
         --custom-response-header="Strict-Transport-Security:$HSTS_FLAGS")

echo "== static IP"
g compute addresses describe pglive-ip --global >/dev/null 2>&1 || g compute addresses create pglive-ip --global --ip-version IPV4
IP="$(g compute addresses describe pglive-ip --global --format='value(address)')"

echo "== serverless NEGs + backend services (all three carry the client-IP and HSTS headers)"
neg() { g compute network-endpoint-groups describe "$1" --region "$REGION" >/dev/null 2>&1 || \
  g compute network-endpoint-groups create "$1" --region "$REGION" --network-endpoint-type=serverless --cloud-run-service="$2"; }
backend() { # name neg
  g compute backend-services describe "$1" --global >/dev/null 2>&1 || \
    g compute backend-services create "$1" --global --load-balancing-scheme=EXTERNAL_MANAGED --protocol=HTTPS
  g compute backend-services update "$1" --global "${HEADERS[@]}" --security-policy=pglive-armor 2>/dev/null || \
    g compute backend-services update "$1" --global "${HEADERS[@]}"
  g compute backend-services add-backend "$1" --global --network-endpoint-group="$2" \
    --network-endpoint-group-region="$REGION" 2>/dev/null || true
}
neg pglive-web-neg pglive-web
neg pglive-api-neg pglive-api

echo "== Cloud Armor (rate limits first; OWASP rules stay in preview until reviewed)"
g compute security-policies describe pglive-armor >/dev/null 2>&1 || g compute security-policies create pglive-armor \
  --description "PGLive edge policy"
# Login endpoints, per client IP: www BFF auth routes and the direct mobile API.
g compute security-policies rules describe 1000 --security-policy pglive-armor >/dev/null 2>&1 || \
  g compute security-policies rules create 1000 --security-policy pglive-armor --action=throttle \
    --rate-limit-threshold-count=60 --rate-limit-threshold-interval-sec=60 \
    --conform-action=allow --exceed-action=deny-429 --enforce-on-key=IP \
    --expression="request.path.matches('^/api/auth/.*') || request.path.matches('^/api/v1/auth/.*')"
# Razorpay webhook: excluded from WAF rules (signed payloads trip generic signatures); allowed explicitly.
g compute security-policies rules describe 900 --security-policy pglive-armor >/dev/null 2>&1 || \
  g compute security-policies rules create 900 --security-policy pglive-armor --action=allow \
    --expression="request.path.matches('^/api/v1/subscriptions/webhook/?$')"
g compute security-policies rules describe 2000 --security-policy pglive-armor >/dev/null 2>&1 || \
  g compute security-policies rules create 2000 --security-policy pglive-armor --action=deny-403 --preview \
    --expression="evaluatePreconfiguredWaf('sqli-v33-stable', {'sensitivity': 1}) || evaluatePreconfiguredWaf('xss-v33-stable', {'sensitivity': 1})"
backend pglive-web-backend pglive-web-neg
backend pglive-api-backend pglive-api-neg
backend pglive-api-admin-backend pglive-api-neg      # IAP-enabled; same Cloud Run service

echo "== IAP on the admin backend (admin MFA = IAP + enforced Google 2-Step Verification)"
cat <<EOF
Manual, once: configure the OAuth consent screen (internal), then
  gcloud iap web enable --resource-type=backend-services --service=pglive-api-admin-backend --project=$PROJECT
  gcloud iap web add-iam-policy-binding --resource-type=backend-services --service=pglive-api-admin-backend \\
     --member=group:pglive-admins@pglive.in --role=roles/iap.httpsResourceAccessor --project=$PROJECT
  gcloud run services add-iam-policy-binding pglive-api --region $REGION \\
     --member=serviceAccount:service-$PROJECT_NUMBER@gcp-sa-iap.iam.gserviceaccount.com --role=roles/run.invoker
Then set IAP_AUDIENCE=/projects/$PROJECT_NUMBER/global/backendServices/<pglive-api-admin-backend id> on pglive-api.
EOF

echo "== URL map: api.pglive.in/admin/* -> admin backend; www and the bare apex -> web; api -> api"
g compute url-maps describe pglive-lb >/dev/null 2>&1 || g compute url-maps create pglive-lb --default-service pglive-web-backend
g compute url-maps remove-host-rule pglive-lb --host api.pglive.in 2>/dev/null || true
g compute url-maps add-path-matcher pglive-lb --path-matcher-name api --default-service pglive-api-backend \
  --new-hosts api.pglive.in --path-rules "/admin/*=pglive-api-admin-backend" 2>/dev/null || true
# pglive.in and www.pglive.in both hit the web backend; Next 301s the bare apex (next.config.ts) so that
# redirect response also passes through the backend service that adds HSTS.

echo "== certificates (DNS authorization: issue before cutover)"
for d in pglive.in www.pglive.in api.pglive.in; do
  n="auth-${d//./-}"
  g certificate-manager dns-authorizations describe "$n" >/dev/null 2>&1 || g certificate-manager dns-authorizations create "$n" --domain "$d"
done
g certificate-manager certificates describe pglive-cert >/dev/null 2>&1 || g certificate-manager certificates create pglive-cert \
  --domains pglive.in,www.pglive.in,api.pglive.in --dns-authorizations auth-pglive-in,auth-www-pglive-in,auth-api-pglive-in
g certificate-manager maps describe pglive-certmap >/dev/null 2>&1 || g certificate-manager maps create pglive-certmap
for d in pglive.in www.pglive.in api.pglive.in; do
  e="entry-${d//./-}"
  g certificate-manager maps entries describe "$e" --map pglive-certmap >/dev/null 2>&1 || \
    g certificate-manager maps entries create "$e" --map pglive-certmap --certificates pglive-cert --hostname "$d"
done

echo "== HTTPS proxy + forwarding rule, and the port-80 redirect"
g compute target-https-proxies describe pglive-https >/dev/null 2>&1 || \
  g compute target-https-proxies create pglive-https --url-map pglive-lb --certificate-map pglive-certmap
g compute forwarding-rules describe pglive-https-fr --global >/dev/null 2>&1 || \
  g compute forwarding-rules create pglive-https-fr --global --load-balancing-scheme=EXTERNAL_MANAGED \
    --address pglive-ip --target-https-proxy pglive-https --ports 443
redirect_map="$(mktemp)"; cat >"$redirect_map" <<'YAML'
name: pglive-http-redirect
defaultUrlRedirect:
  redirectResponseCode: MOVED_PERMANENTLY_DEFAULT
  httpsRedirect: true
YAML
g compute url-maps import pglive-http-redirect --global --source "$redirect_map" --quiet
g compute target-http-proxies describe pglive-http >/dev/null 2>&1 || g compute target-http-proxies create pglive-http --url-map pglive-http-redirect
g compute forwarding-rules describe pglive-http-fr --global >/dev/null 2>&1 || \
  g compute forwarding-rules create pglive-http-fr --global --load-balancing-scheme=EXTERNAL_MANAGED \
    --address pglive-ip --target-http-proxy pglive-http --ports 80

echo
echo "== GoDaddy DNS records to enter (lower the TTL to 300 first)"
echo "   A     @      $IP"
echo "   A     www    $IP"
echo "   A     api    $IP"
for d in pglive.in www.pglive.in api.pglive.in; do
  g certificate-manager dns-authorizations describe "auth-${d//./-}" --format='value(dnsResourceRecord.name,dnsResourceRecord.type,dnsResourceRecord.data)' \
    | awk '{printf "   %-5s %s  ->  %s   (certificate validation)\n", $2, $1, $3}'
done
echo "   plus the SPF / DKIM / DMARC records from the email provider"
echo "HSTS check at every ramp step:  curl -sI https://pglive.in https://www.pglive.in https://api.pglive.in/health/ | grep -i strict"
