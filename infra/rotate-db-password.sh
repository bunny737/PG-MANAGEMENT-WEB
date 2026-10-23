#!/usr/bin/env bash
# Rotate the runtime (app_user) or owner (migration_user) database password.
#   infra/rotate-db-password.sh prod app_user|migration_user
#
# NOT zero-downtime: old and new revisions share one role, so there is a short window (~1-2 min) in which new
# connections fail between ALTER ROLE and the redeploy. Existing pooled connections keep working. Run it in a
# low-traffic window, never while a deploy is running. (Later upgrade: two runtime roles, or Cloud SQL IAM auth.)
# STATUS: not yet run against a real project (see env.sh).
set -euo pipefail
source "$(dirname "$0")/env.sh" "$1"
ROLE="${2:?app_user|migration_user}"
case "$ROLE" in
  app_user) SECRET=DB_PASSWORD ;;
  migration_user) SECRET=DB_MIGRATION_PASSWORD ;;
  *) echo "role must be app_user or migration_user" >&2; exit 1 ;;
esac
g() { gcloud --project "$PROJECT" "$@"; }
: "${POSTGRES_ADMIN_PASSWORD:?needed to ALTER ROLE through the proxy (cloud-sql-proxy $SQL_CONNECTION --port 5432 &)}"

NEW="$(head -c 36 /dev/urandom | base64 | tr -d '\n/+=')"
printf '%s' "$NEW" | g secrets versions add "$SECRET" --data-file=-
PGPASSWORD="$POSTGRES_ADMIN_PASSWORD" psql "host=127.0.0.1 port=5432 user=postgres dbname=postgres" \
  -v ON_ERROR_STOP=1 -v role="$ROLE" -v pw="$NEW" -c "ALTER ROLE :\"role\" PASSWORD :'pw'"

if [[ "$ROLE" == app_user ]]; then
  # Restart everything that holds the old password: new revisions pick up :latest.
  g run services update pglive-api --region "$REGION" --update-labels "rotated=$(date +%s)"
  for job in pglive-check-roles pglive-generate-invoices pglive-check-grace-periods pglive-bootstrap; do
    g run jobs describe "$job" --region "$REGION" >/dev/null 2>&1 && g run jobs update "$job" --region "$REGION" --update-labels "rotated=$(date +%s)" || true
  done
  echo "Now redeploy the worker VM:  gcloud compute ssh $WORKER_VM --tunnel-through-iap --command 'sudo /opt/pglive/deploy.sh <current-tag>'"
else
  g run jobs update pglive-migrate --region "$REGION" --update-labels "rotated=$(date +%s)"
fi
echo "Rotated $ROLE. Verify: pglive-check-roles job, /health/ready/, a login."
