#!/usr/bin/env bash
# The release sequence, shared by the staging and production workflows (docs/deployment.md, "Releases").
#   infra/deploy.sh <prod|staging> <git-sha>
# Expects gcloud already authenticated (Workload Identity Federation) and these env vars from the workflow:
#   PROJECT, REGION, COMPANY_NAME, COMPANY_ADDRESS, plus optional SITE_URL, APP_STATUS, PLAY_STORE_URL,
#   SIGNUP_ENABLED, CSP_MODE, CSP_REPORT_URI, NEXT_PUBLIC_* (build args), TRAFFIC_STEPS.
# STATUS: not yet run against a real project (see env.sh).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/env.sh" "$1"
SHA="${2:?git sha}"
g() { gcloud --project "$PROJECT" "$@"; }
export API_IMAGE="$AR_REPO/pglive-api:$SHA" WEB_IMAGE="$AR_REPO/pglive-web:$SHA"

echo "== build + push"
gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
docker build -f backend/Dockerfile.prod -t "$API_IMAGE" backend
docker build -f frontend/Dockerfile.prod -t "$WEB_IMAGE" \
  --build-arg SITE_URL="${SITE_URL:-https://www.pglive.in}" --build-arg SITE_ENV="$([[ $ENVIRONMENT == prod ]] && echo production || echo staging)" \
  --build-arg COMPANY_NAME="${COMPANY_NAME:?}" --build-arg COMPANY_ADDRESS="${COMPANY_ADDRESS:?}" \
  --build-arg APP_STATUS="${APP_STATUS:-comingSoon}" --build-arg PLAY_STORE_URL="${PLAY_STORE_URL:-}" \
  --build-arg SIGNUP_ENABLED="${SIGNUP_ENABLED:-false}" \
  --build-arg NEXT_PUBLIC_FIREBASE_API_KEY="${NEXT_PUBLIC_FIREBASE_API_KEY:-}" \
  --build-arg NEXT_PUBLIC_FIREBASE_PROJECT_ID="${NEXT_PUBLIC_FIREBASE_PROJECT_ID:-}" \
  --build-arg NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID="${NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID:-}" \
  --build-arg NEXT_PUBLIC_FIREBASE_APP_ID="${NEXT_PUBLIC_FIREBASE_APP_ID:-}" \
  --build-arg NEXT_PUBLIC_FIREBASE_VAPID_KEY="${NEXT_PUBLIC_FIREBASE_VAPID_KEY:-}" \
  --build-arg NEXT_PUBLIC_GOOGLE_MAPS_API_KEY="${NEXT_PUBLIC_GOOGLE_MAPS_API_KEY:-}" frontend
docker push "$API_IMAGE"; docker push "$WEB_IMAGE"

if [[ "$ENVIRONMENT" == prod ]]; then
  echo "== on-demand Cloud SQL backup (migrate only after it SUCCEEDED)"
  g sql backups create --instance "$SQL_INSTANCE" --description "pre-release $SHA"
  for _ in $(seq 1 60); do
    state="$(g sql backups list --instance "$SQL_INSTANCE" --limit 1 --format='value(status)')"
    [[ "$state" == SUCCESSFUL ]] && break
    [[ "$state" == FAILED ]] && { echo "backup FAILED, aborting before migrate" >&2; exit 1; }
    sleep 10
  done
  [[ "$state" == SUCCESSFUL ]] || { echo "backup did not finish in 10 minutes, aborting" >&2; exit 1; }
fi

echo "== services + jobs (new revisions get NO traffic yet)"
"$here/30-services.sh" "$ENVIRONMENT"

echo "== migrate, grants, role check"
g run jobs execute pglive-migrate --region "$REGION" --wait
# roles-2-grants.sql was applied once after the first migrate (docs/deployment.md); from then on
# ALTER DEFAULT PRIVILEGES FOR ROLE migration_user grants app_user access to every new table and sequence.
# This job proves it: it fails the release if app_user owns anything or a new tenant table lacks forced RLS.
g run jobs execute pglive-check-roles --region "$REGION" --wait

echo "== pre-traffic smoke test from inside the VPC (candidate revisions)"
g run jobs execute pglive-smoke --region "$REGION" --wait

shift_traffic() { # service percent
  g run services update-traffic "$1" --region "$REGION" --to-tags "candidate=$2"
}
rollback() {
  echo "!! smoke or post-deploy check failed: sending traffic back to the previous revisions" >&2
  for svc in pglive-api pglive-web; do
    prev="$(g run revisions list --service "$svc" --region "$REGION" --format='value(name)' --limit 2 | tail -1)"
    [[ -n "$prev" ]] && g run services update-traffic "$svc" --region "$REGION" --to-revisions "$prev=100" || true
  done
}
trap rollback ERR

echo "== canary 10% -> watch -> 100%"
for svc in pglive-api pglive-web; do shift_traffic "$svc" 10; done
sleep "${CANARY_WATCH_SECONDS:-600}"
errors="$(g logging read 'resource.type="cloud_run_revision" AND severity>=ERROR AND httpRequest.status>=500' \
  --freshness "${CANARY_WATCH_SECONDS:-600}s" --limit 50 --format='value(timestamp)' | wc -l)"
(( errors < ${CANARY_MAX_5XX:-5} )) || { echo "$errors 5xx during canary" >&2; false; }
for svc in pglive-api pglive-web; do shift_traffic "$svc" 100; done

if [[ "$ENVIRONMENT" == prod ]]; then
  echo "== worker VM"
  gcloud --project "$PROJECT" compute ssh "$WORKER_VM" --zone "${REGION}-a" --tunnel-through-iap \
    --command "sudo /opt/pglive/deploy.sh $SHA"
fi
trap - ERR
echo "Released $SHA to $ENVIRONMENT"
