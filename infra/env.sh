#!/usr/bin/env bash
# Shared settings for the infra scripts. Source it, don't run it:  source infra/env.sh prod|staging
#
# STATUS: written from the plan, NOT yet run against a real project. Run in pglive-staging first and
# fix what the first run finds. Every script is meant to be re-runnable (create-if-missing).
set -euo pipefail

ENVIRONMENT="${1:-${ENVIRONMENT:-}}"
case "$ENVIRONMENT" in
  prod|staging) ;;
  *) echo "usage: source infra/env.sh prod|staging" >&2; return 1 2>/dev/null || exit 1 ;;
esac

export ENVIRONMENT
export PROJECT="${PROJECT:-pglive-$ENVIRONMENT}"
export REGION="${REGION:-asia-south1}"
export BACKUP_REGION="${BACKUP_REGION:-asia-south2}"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)' 2>/dev/null || true)"
export PROJECT_NUMBER

# Cloud SQL: lean tier during the trial, custom-1-3840 for real load (docs/deployment.md, cost section).
export SQL_INSTANCE="${SQL_INSTANCE:-pglive-pg-$ENVIRONMENT}"
export SQL_TIER="${SQL_TIER:-db-custom-1-3840}"
export SQL_CONNECTION="$PROJECT:$REGION:$SQL_INSTANCE"
export DB_NAME="${DB_NAME:-pg_platform}"

# Cloud Run: 1 on db-g1-small, 3 on db-custom-1-3840 (connection budget, docs/deployment.md).
export API_MAX_INSTANCES="${API_MAX_INSTANCES:-3}"
export API_CONCURRENCY=8            # = gunicorn 2 workers x 4 threads (backend/gunicorn.conf.py)

export MEDIA_BUCKET="${MEDIA_BUCKET:-$PROJECT-media}"
export BACKUP_BUCKET="${BACKUP_BUCKET:-$PROJECT-backups}"
export AR_REPO="$REGION-docker.pkg.dev/$PROJECT/pglive"

export NETWORK="${NETWORK:-pglive}"
export SUBNET="${SUBNET:-pglive-$REGION}"
export SUBNET_RANGE="${SUBNET_RANGE:-10.20.0.0/24}"
export WORKER_VM="pglive-worker"
export WORKER_IP="${WORKER_IP:-10.20.0.10}"

sa() { echo "$1@$PROJECT.iam.gserviceaccount.com"; }
secret_exists() { gcloud secrets describe "$1" --project "$PROJECT" >/dev/null 2>&1; }
