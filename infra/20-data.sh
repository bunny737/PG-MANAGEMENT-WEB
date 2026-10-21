#!/usr/bin/env bash
# Phase 3: Cloud SQL (PostgreSQL 16), the two database roles, and the GCS buckets.
#   infra/20-data.sh prod|staging
# STATUS: not yet run against a real project (see env.sh).
set -euo pipefail
source "$(dirname "$0")/env.sh" "$1"
g() { gcloud --project "$PROJECT" "$@"; }

echo "== Cloud SQL $SQL_INSTANCE ($SQL_TIER)"
if ! g sql instances describe "$SQL_INSTANCE" >/dev/null 2>&1; then
  g sql instances create "$SQL_INSTANCE" \
    --database-version POSTGRES_16 --edition ENTERPRISE --tier "$SQL_TIER" --region "$REGION" \
    --availability-type ZONAL --storage-type SSD --storage-size 20GB --storage-auto-increase \
    --ssl-mode ENCRYPTED_ONLY \
    --backup --backup-start-time 20:30 --retained-backups-count 14 \
    --enable-point-in-time-recovery --retained-transaction-log-days 7 \
    --maintenance-window-day SUN --maintenance-window-hour 20 --maintenance-release-channel production \
    --database-flags log_min_duration_statement=500,log_connections=on,log_disconnections=on \
    --deletion-protection
fi
# No authorized networks are ever added: clients use the Cloud Run /cloudsql socket or the Auth Proxy.

echo "== Database roles (docs/deployment.md, 'Database roles')"
# The built-in `postgres` password is only used here, through the Auth Proxy, and never stored in the app.
if [[ -z "${POSTGRES_ADMIN_PASSWORD:-}" || -z "${DB_MIGRATION_PASSWORD:-}" || -z "${DB_PASSWORD:-}" ]]; then
  cat >&2 <<EOF
Set POSTGRES_ADMIN_PASSWORD, DB_MIGRATION_PASSWORD and DB_PASSWORD in this shell (and store the last two with
'gcloud secrets versions add DB_MIGRATION_PASSWORD|DB_PASSWORD --data-file=-'), start the proxy:
  cloud-sql-proxy $SQL_CONNECTION --port 5432 &
then re-run. Skipping role creation.
EOF
else
  g sql users set-password postgres --instance "$SQL_INSTANCE" --password "$POSTGRES_ADMIN_PASSWORD"
  export PGPASSWORD="$POSTGRES_ADMIN_PASSWORD"
  psql "host=127.0.0.1 port=5432 user=postgres dbname=postgres" \
    -v migration_password="$DB_MIGRATION_PASSWORD" -v app_password="$DB_PASSWORD" -v db_name="$DB_NAME" \
    -f "$(dirname "$0")/sql/roles-1-roles.sql"
  echo "Roles created. After the first pglive-migrate run: psql ... -f infra/sql/roles-2-grants.sql"
fi

echo "== Buckets"
mk() { gcloud storage buckets describe "gs://$1" --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://$1" --project "$PROJECT" --location "$2" --default-storage-class STANDARD \
    --uniform-bucket-level-access --public-access-prevention; }
mk "$MEDIA_BUCKET" "$REGION"
gcloud storage buckets update "gs://$MEDIA_BUCKET" --project "$PROJECT" --versioning --soft-delete-duration=14d
lifecycle="$(mktemp)"; cat >"$lifecycle" <<'JSON'
{"rule":[{"action":{"type":"Delete"},"condition":{"daysSinceNoncurrentTime":60,"isLive":false}}]}
JSON
gcloud storage buckets update "gs://$MEDIA_BUCKET" --project "$PROJECT" --lifecycle-file="$lifecycle"
for name in api worker; do
  gcloud storage buckets add-iam-policy-binding "gs://$MEDIA_BUCKET" --project "$PROJECT" \
    --member "serviceAccount:$(sa sa-$name)" --role roles/storage.objectUser >/dev/null
done

mk "$BACKUP_BUCKET" "$BACKUP_REGION"
# 90-day retention, deliberately NOT locked: locking is irreversible and puts a lien on the project.
# Prove export -> restore -> lifecycle -> deletion first, then lock only with explicit owner approval.
gcloud storage buckets update "gs://$BACKUP_BUCKET" --project "$PROJECT" --retention-period=90d
lifecycle="$(mktemp)"; cat >"$lifecycle" <<'JSON'
{"rule":[{"action":{"type":"Delete"},"condition":{"age":91,"matchesPrefix":["sql/"]}}]}
JSON
gcloud storage buckets update "gs://$BACKUP_BUCKET" --project "$PROJECT" --lifecycle-file="$lifecycle"
# The Cloud SQL service agent writes exports; the Workflow only verifies and labels them.
SQL_AGENT="$(g sql instances describe "$SQL_INSTANCE" --format='value(serviceAccountEmailAddress)')"
gcloud storage buckets add-iam-policy-binding "gs://$BACKUP_BUCKET" --project "$PROJECT" \
  --member "serviceAccount:$SQL_AGENT" --role roles/storage.objectCreator >/dev/null
g iam roles describe pglive.backupObjectReader >/dev/null 2>&1 || g iam roles create pglive.backupObjectReader \
  --title "PGLive backup object reader" --permissions storage.objects.get,storage.objects.list,storage.objects.update
for name in export export-verify; do
  gcloud storage buckets add-iam-policy-binding "gs://$BACKUP_BUCKET" --project "$PROJECT" \
    --member "serviceAccount:$(sa sa-$name)" --role projects/"$PROJECT"/roles/pglive.backupObjectReader >/dev/null
done
echo "Done. Next: build+push images, then infra/30-services.sh $ENVIRONMENT"
