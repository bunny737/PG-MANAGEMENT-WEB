#!/usr/bin/env bash
# Restore drill: import the newest production export into a throwaway instance and prove it is usable.
#   infra/dr/restore-drill.sh            (needs: gcloud authenticated as the drill operator, cloud-sql-proxy, psql)
#
# Runs ONLY in the isolated pglive-dr-test project, never in staging or prod: the export holds real resident,
# Aadhaar/PAN and payment data. That project has no developer access, no Cloud Run, no Firebase/Razorpay/email,
# and Data Access audit logs on. The instance is deleted at the end (and on any failure).
# STATUS: not yet run against a real project (see ../env.sh).
set -euo pipefail
cd "$(dirname "$0")/../.."
DR_PROJECT="${DR_PROJECT:-pglive-dr-test}"
PROD_PROJECT="${PROD_PROJECT:-pglive-prod}"
REGION="${REGION:-asia-south1}"
BUCKET="${BACKUP_BUCKET:-$PROD_PROJECT-backups}"
INSTANCE="drill-$(date +%Y%m%d%H%M)"
DB=pg_platform
started="$(date +%s)"
g() { gcloud --project "$DR_PROJECT" "$@"; }
[[ "$DR_PROJECT" != "$PROD_PROJECT" && "$DR_PROJECT" != pglive-staging ]] || { echo "refusing: use the isolated DR project" >&2; exit 1; }

cleanup() {
  [[ -n "${PROXY_PID:-}" ]] && kill "$PROXY_PID" 2>/dev/null || true
  g sql instances delete "$INSTANCE" --quiet 2>/dev/null && echo "Deleted $INSTANCE"
  [[ -n "${GRANTED_AGENT:-}" ]] && gcloud storage objects remove-iam-policy-binding "gs://$BUCKET/$OBJECT" --project "$PROD_PROJECT" \
    --member "serviceAccount:$GRANTED_AGENT" --role roles/storage.objectViewer >/dev/null 2>&1 && echo "Revoked bucket grant"
}
trap cleanup EXIT

OBJECT="$(gcloud storage ls "gs://$BUCKET/sql/" --project "$PROD_PROJECT" | grep '\.sql\.gz$' | sort | tail -1 | sed "s|gs://$BUCKET/||")"
echo "== newest export: $OBJECT"

echo "== temporary instance $INSTANCE"
g sql instances create "$INSTANCE" --database-version POSTGRES_16 --edition ENTERPRISE --tier db-g1-small \
  --region "$REGION" --ssl-mode ENCRYPTED_ONLY --no-backup --labels purpose=restore-drill,delete-after=1d
ADMIN_PW="$(head -c 24 /dev/urandom | base64 | tr -d '\n/+=')"
MIG_PW="$(head -c 24 /dev/urandom | base64 | tr -d '\n/+=')"; APP_PW="$(head -c 24 /dev/urandom | base64 | tr -d '\n/+=')"
g sql users set-password postgres --instance "$INSTANCE" --password "$ADMIN_PW"

echo "== let the new instance read that one export (revoked on exit)"
GRANTED_AGENT="$(g sql instances describe "$INSTANCE" --format='value(serviceAccountEmailAddress)')"
gcloud storage objects add-iam-policy-binding "gs://$BUCKET/$OBJECT" --project "$PROD_PROJECT" \
  --member "serviceAccount:$GRANTED_AGENT" --role roles/storage.objectViewer >/dev/null

echo "== roles part 1 (a logical export carries no server-level roles)"
cloud-sql-proxy "$DR_PROJECT:$REGION:$INSTANCE" --port 5433 >/dev/null 2>&1 &
PROXY_PID=$!; sleep 8
export PGPASSWORD="$ADMIN_PW"
psql "host=127.0.0.1 port=5433 user=postgres dbname=postgres" -v migration_password="$MIG_PW" -v app_password="$APP_PW" \
  -v db_name="$DB" -f infra/sql/roles-1-roles.sql

echo "== import as migration_user so imported objects are owned correctly"
# (migration_user is a Postgres role made by roles-1 above, not a Cloud SQL user, so there is no
# `gcloud sql users` step. If the Admin API refuses a non-built-in import user, the first drill will say so.)
g sql import sql "$INSTANCE" "gs://$BUCKET/$OBJECT" --database "$DB" --user migration_user --quiet

echo "== roles part 2 (ownership + default privileges; idempotent)"
psql "host=127.0.0.1 port=5433 user=postgres dbname=$DB" -f infra/sql/roles-2-grants.sql

echo "== verify as app_user: owns nothing, DML only, forced RLS, and the isolation tests"
IMAGE="${API_IMAGE:?API_IMAGE=<registry>/pglive-api:<tag> (the production image)}"
docker run --rm --network host -e DB_HOST=127.0.0.1 -e DB_PORT=5433 -e DB_USER=app_user -e DB_PASSWORD="$APP_PW" -e DB_SSLMODE=require \
  -e SECRET_KEY="$(head -c 48 /dev/urandom | base64 | tr -d '\n/+=')$(head -c 48 /dev/urandom | base64 | tr -d '\n/+=')" \
  -e JWT_SIGNING_KEY="$(head -c 48 /dev/urandom | base64 | tr -d '\n/+=')$(head -c 48 /dev/urandom | base64 | tr -d '\n/+=')" \
  "$IMAGE" python manage.py check_db_roles --role app_user
psql "host=127.0.0.1 port=5433 user=postgres dbname=$DB" -At -c \
  "SELECT 'tenants', count(*) FROM tenants UNION ALL SELECT 'residents (as postgres)', count(*) FROM residents"

echo "== done in $(( $(date +%s) - started )) s - record this in docs/deployment.md (it feeds the RTO)."
