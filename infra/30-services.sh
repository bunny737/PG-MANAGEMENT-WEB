#!/usr/bin/env bash
# Phase 5: Cloud Run services and jobs, Cloud Scheduler, the weekly-export Workflow.
#   API_IMAGE=... WEB_IMAGE=... COMPANY_NAME=... COMPANY_ADDRESS=... infra/30-services.sh prod|staging
# Images are SHA-tagged in Artifact Registry. Every job has a FIXED command (no per-run overrides), so
# schedulers and operators need only roles/run.invoker. New service revisions are deployed with
# --no-traffic --tag candidate: nothing is live until infra/deploy.sh has smoke-tested and shifted traffic.
# STATUS: not yet run against a real project (see env.sh).
set -euo pipefail
source "$(dirname "$0")/env.sh" "$1"
: "${API_IMAGE:?API_IMAGE=$AR_REPO/pglive-api:<sha>}" "${WEB_IMAGE:?WEB_IMAGE=$AR_REPO/pglive-web:<sha>}"
: "${ALLOWED_API_HOSTS:=api.pglive.in}" "${SITE_URL:=https://www.pglive.in}"
g() { gcloud --project "$PROJECT" "$@"; }

# Env values contain commas (ALLOWED_HOSTS) and @ (GS_SA_EMAIL, DEFAULT_FROM_EMAIL), so every --set-env-vars uses
# gcloud's custom delimiter ";": "^;^K=v;K2=v2".
SQL_ENV="DB_HOST=/cloudsql/$SQL_CONNECTION;DB_NAME=$DB_NAME"
COMMON_ENV="DJANGO_SETTINGS_MODULE=config.settings.prod;GS_BUCKET_NAME=$MEDIA_BUCKET;GS_PROJECT_ID=$PROJECT"
# FIREBASE_PROJECT_ID: Firebase may live in its own project (prod: pglive-prod-e57a1); defaults to this one.
COMMON_ENV+=";FIREBASE_USE_ADC=True;FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID:-$PROJECT};FRONTEND_BASE_URL=$SITE_URL"
COMMON_ENV+=";APP_RELEASE=${SHA:-unknown};SENTRY_ENVIRONMENT=$([[ $ENVIRONMENT == prod ]] && echo production || echo staging)"
# Staging intentionally runs on Razorpay test keys (infra/README.md); only a prod deploy requires
# a live key (apps.subscriptions.checks, backend/bin/start-api.sh).
COMMON_ENV+=";RAZORPAY_REQUIRE_LIVE_MODE=$([[ $ENVIRONMENT == prod ]] && echo true || echo false)"
# SMTP + company-identity settings (non-secret; the SMTP password is the EMAIL_HOST_PASSWORD secret).
# COMPANY_NAME/COMPANY_ADDRESS also feed every outgoing email's footer (apps.core.email) — both the
# API and the worker send mail, so worker/deploy.sh forwards the same two vars. Only set ones are
# passed, so an empty EMAIL_PORT can't break env.int() and unset ones keep the settings defaults.
for v in EMAIL_HOST EMAIL_PORT EMAIL_HOST_USER DEFAULT_FROM_EMAIL COMPANY_NAME COMPANY_ADDRESS; do
  if [[ -n "${!v:-}" ]]; then COMMON_ENV+=";$v=${!v}"; fi
done
VPC=(--network "$NETWORK" --subnet "$SUBNET" --vpc-egress private-ranges-only)

secrets() { # NAME[=SECRET] ... -> --set-secrets (all :latest)
  local out=() s
  for s in "$@"; do out+=("${s%%=*}=${s##*=}:latest"); done
  local IFS=,; echo "--set-secrets=${out[*]}"
}
API_SECRETS="$(secrets SECRET_KEY=DJANGO_SECRET_KEY JWT_SIGNING_KEY DB_PASSWORD BFF_ORIGIN_SECRET \
  RAZORPAY_KEY_ID RAZORPAY_KEY_SECRET RAZORPAY_WEBHOOK_SECRET EMAIL_HOST_PASSWORD SENTRY_DSN \
  APP_MAINTENANCE_BYPASS_TOKEN REDIS_URL REDIS_CACHE_URL)"

# The tagged candidate URL is the service URL with "candidate---" prefixed. The service URL is stable once the
# service exists, so a re-deploy knows it up front; the very first deploy needs this script run twice.
service_url() { g run services describe "$1" --region "$REGION" --format='value(status.url)' 2>/dev/null || true; }
candidate_host() { local url; url="$(service_url "$1")"; [[ -n "$url" ]] && echo "candidate---${url#https://}"; }
# nginx on the worker VM (infra/edge/) sends Host = the run.app name, because Cloud Run routes on Host.
API_HOSTS="$ALLOWED_API_HOSTS,pglive-api-$PROJECT_NUMBER.$REGION.run.app"
if cand="$(candidate_host pglive-api)" && [[ -n "$cand" ]]; then API_HOSTS="$API_HOSTS,$cand"; fi
# Cloud Run rejects --no-traffic on a service's first deployment; that first revision takes the (still empty)
# traffic instead. Ingress is internal (only the VM edge), so nothing reaches it before nginx is set up.
API_TRAFFIC=(); WEB_TRAFFIC=()
if [[ -n "$(service_url pglive-api)" ]]; then API_TRAFFIC=(--no-traffic --tag candidate); fi
if [[ -n "$(service_url pglive-web)" ]]; then WEB_TRAFFIC=(--no-traffic --tag candidate); fi

echo "== preflight: every secret needs a version, or the deploy fails half-way"
missing=0
for s in DJANGO_SECRET_KEY JWT_SIGNING_KEY DB_PASSWORD DB_MIGRATION_PASSWORD REDIS_URL REDIS_CACHE_URL BFF_ORIGIN_SECRET \
         BFF_EDGE_KEY RAZORPAY_KEY_ID RAZORPAY_KEY_SECRET RAZORPAY_WEBHOOK_SECRET EMAIL_HOST_PASSWORD SENTRY_DSN \
         APP_MAINTENANCE_BYPASS_TOKEN SMOKE_USER_CREDENTIALS; do
  if [[ -z "$(g secrets versions list "$s" --filter=state=ENABLED --limit 1 --format='value(name)' 2>/dev/null)" ]]; then
    echo "  no enabled version: $s  (gcloud secrets versions add $s --data-file=-; the three RAZORPAY_* secrets need real values: the API refuses to start on placeholders)" >&2
    missing=1
  fi
done
(( missing == 0 )) || exit 1

echo "== pglive-api"
# No HTTP liveness probe: probes arrive as plain HTTP with the container address as Host, which prod Django
# answers with 400 DisallowedHost (ALLOWED_HOSTS) before any view runs — Cloud Run would restart the API forever.
# The TCP startup probe needs nothing from Django. Readiness is checked through nginx (https://api.pglive.in).
# /admin/ is guarded by the nginx allowlist, not IAP (no load balancer), hence IAP_REQUIRED=False.
g run deploy pglive-api --region "$REGION" --image "$API_IMAGE" --service-account "$(sa sa-api)" \
  --ingress internal --allow-unauthenticated \
  --cpu 1 --memory 1Gi --concurrency "$API_CONCURRENCY" --timeout 60 \
  --min-instances 1 --max-instances "$API_MAX_INSTANCES" \
  --set-cloudsql-instances "$SQL_CONNECTION" "${VPC[@]}" \
  --startup-probe tcpSocket.port=8080,initialDelaySeconds=0,periodSeconds=3,failureThreshold=20 \
  --set-env-vars "^;^$COMMON_ENV;$SQL_ENV;DB_USER=app_user;ALLOWED_HOSTS=$API_HOSTS;CSRF_TRUSTED_ORIGINS=$SITE_URL,https://api.pglive.in;APP_VERSION_ENFORCEMENT=log;GS_SA_EMAIL=$(sa sa-api);IAP_REQUIRED=False;SECURE_HSTS_SECONDS=0" \
  "$API_SECRETS" "${API_TRAFFIC[@]}"

echo "== pglive-web"
g run deploy pglive-web --region "$REGION" --image "$WEB_IMAGE" --service-account "$(sa sa-web)" \
  --ingress internal --allow-unauthenticated \
  --cpu 1 --memory 512Mi --concurrency 40 --timeout 60 --min-instances 0 --max-instances 5 \
  --startup-probe tcpSocket.port=8080,periodSeconds=3,failureThreshold=20 \
  --liveness-probe httpGet.path=/api/health,httpGet.port=8080,periodSeconds=30 \
  --set-env-vars "^;^INTERNAL_API_URL=https://api.pglive.in;SITE_URL=$SITE_URL;COMPANY_NAME=${COMPANY_NAME:?};COMPANY_ADDRESS=${COMPANY_ADDRESS:?};APP_STATUS=${APP_STATUS:-comingSoon};PLAY_STORE_URL=${PLAY_STORE_URL:-};SIGNUP_ENABLED=${SIGNUP_ENABLED:-false};CSP_MODE=${CSP_MODE:-report-only};CSP_REPORT_URI=${CSP_REPORT_URI:-}" \
  "$(secrets BFF_ORIGIN_SECRET BFF_EDGE_KEY)" "${WEB_TRAFFIC[@]}"

job() { # name service-account db-user secrets-flag django-command-and-args [nosql]
  local name="$1" account="$2" db_user="$3" secret_flag="$4" args="$5" nosql="${6:-}"
  local verb=create sql=(--set-cloudsql-instances "$SQL_CONNECTION")
  [[ -n "$nosql" ]] && sql=(--clear-cloudsql-instances)
  g run jobs describe "$name" --region "$REGION" >/dev/null 2>&1 && verb=update
  g run jobs "$verb" "$name" --region "$REGION" --image "$API_IMAGE" --service-account "$(sa "$account")" \
    --max-retries 0 --task-timeout 1800 "${sql[@]}" "${VPC[@]}" \
    --set-env-vars "^;^$COMMON_ENV;$SQL_ENV;DB_USER=$db_user;ALLOWED_HOSTS=$ALLOWED_API_HOSTS;EXPORT_BUCKET=$BACKUP_BUCKET;EXPORT_MIN_TABLES=${EXPORT_MIN_TABLES:-60}" \
    "$secret_flag" --command python --args "manage.py,$args"
}
echo "== jobs"
# migrate runs as the schema OWNER with its own password; everything else as the runtime role.
MIGRATE_SECRETS="$(secrets SECRET_KEY=DJANGO_SECRET_KEY JWT_SIGNING_KEY DB_PASSWORD=DB_MIGRATION_PASSWORD)"
job pglive-migrate sa-migrate migration_user "$MIGRATE_SECRETS" "migrate,--noinput"
# One job = one command, so the post-migrate role check is its own job; the deploy aborts if it fails.
job pglive-check-roles sa-api app_user "$API_SECRETS" "check_db_roles,--role,app_user"
job pglive-generate-invoices sa-api app_user "$API_SECRETS" "generate_subscription_invoices"
job pglive-check-grace-periods sa-api app_user "$API_SECRETS" "check_subscription_grace_periods"
# Bootstrap exists only for the first deploy: add INITIAL_SUPERADMIN_EMAIL / INITIAL_SUPERADMIN_PASSWORD (a
# temporary secret) for the run, follow the verify-then-destroy order in docs/deployment.md, then delete the job.
job pglive-bootstrap sa-bootstrap app_user "$(secrets SECRET_KEY=DJANGO_SECRET_KEY JWT_SIGNING_KEY DB_PASSWORD)" "bootstrap_platform"
# Reads the backup bucket only: no database attachment, and settings need only the two keys.
job pglive-export-verify sa-export-verify app_user "$(secrets SECRET_KEY=DJANGO_SECRET_KEY JWT_SIGNING_KEY)" "verify_latest_export" nosql

echo "== pglive-smoke (pre-traffic, inside the VPC; no database, bucket or app secrets)"
smoke_verb=create; g run jobs describe pglive-smoke --region "$REGION" >/dev/null 2>&1 && smoke_verb=update
API_CAND="$(service_url pglive-api)"; WEB_CAND="$(service_url pglive-web)"
g run jobs "$smoke_verb" pglive-smoke --region "$REGION" --image "$API_IMAGE" --service-account "$(sa sa-smoke)" \
  --max-retries 0 --task-timeout 300 --network "$NETWORK" --subnet "$SUBNET" --vpc-egress all-traffic \
  --set-env-vars "^;^SMOKE_API_URL=https://candidate---${API_CAND#https://};SMOKE_WEB_URL=https://candidate---${WEB_CAND#https://}" \
  "$(secrets SMOKE_USER_CREDENTIALS)" --command python --args "scripts/smoke.py"

echo "== Scheduler (OAuth tokens: these are googleapis.com endpoints, not Cloud Run URLs)"
JOBS_API="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs"
sched() { # name cron uri
  local verb=create; g scheduler jobs describe "$1" --location "$REGION" >/dev/null 2>&1 && verb=update
  g scheduler jobs "$verb" http "$1" --location "$REGION" --schedule "$2" --time-zone Asia/Kolkata \
    --uri "$3" --http-method POST --oauth-service-account-email "$(sa sa-scheduler)" \
    --oauth-token-scope https://www.googleapis.com/auth/cloud-platform \
    --max-retry-attempts 3 --min-backoff 60s --max-backoff 600s
}
sched pglive-generate-invoices "0 2 * * *" "$JOBS_API/pglive-generate-invoices:run"
sched pglive-check-grace-periods "30 2 * * *" "$JOBS_API/pglive-check-grace-periods:run"
for j in pglive-generate-invoices pglive-check-grace-periods; do
  g run jobs add-iam-policy-binding "$j" --region "$REGION" --member "serviceAccount:$(sa sa-scheduler)" --role roles/run.invoker >/dev/null
done

if [[ "$ENVIRONMENT" == prod ]]; then
  echo "== weekly export Workflow (Wednesday 22:30 IST, outside the Sunday maintenance window)"
  g workflows deploy pglive-weekly-export --location "$REGION" --service-account "$(sa sa-export)" \
    --source "$(dirname "$0")/workflows/weekly-export.yaml"
  g run jobs add-iam-policy-binding pglive-export-verify --region "$REGION" --member "serviceAccount:$(sa sa-export)" --role roles/run.invoker >/dev/null
  sched pglive-weekly-export "30 22 * * 3" \
    "https://workflowexecutions.googleapis.com/v1/projects/$PROJECT/locations/$REGION/workflows/pglive-weekly-export/executions"
fi
echo "Done. Candidate revisions have NO traffic: pglive-smoke, then shift traffic (infra/deploy.sh does both)."
