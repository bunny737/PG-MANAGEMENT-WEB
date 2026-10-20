#!/usr/bin/env bash
# On the pglive-worker VM:  sudo /opt/pglive/deploy.sh <image-tag>     (CI: gcloud compute ssh --tunnel-through-iap)
# Pulls secrets from Secret Manager into a root-only .env, then (re)starts the stack. Rollback = run it with
# the previous tag. Needs the VM's service account (sa-worker): secret access + Artifact Registry read.
set -euo pipefail
TAG="${1:?usage: deploy.sh <image-tag>}"
cd /opt/pglive
META='http://metadata.google.internal/computeMetadata/v1'
md() { curl -fs -H 'Metadata-Flavor: Google' "$META/$1"; }
opt() { md "instance/attributes/$1" 2>/dev/null || true; }   # optional VM metadata (gcloud compute instances add-metadata)
PROJECT="$(md project/project-id)"; REGION="$(md instance/attributes/region)"
SQL_CONNECTION="$(md instance/attributes/sql-connection)"; WORKER_IP="$(md instance/network-interfaces/0/ip)"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/pglive/pglive-api:$TAG"

secret() { gcloud secrets versions access latest --secret "$1" --project "$PROJECT"; }
umask 077
{
  echo "DJANGO_SETTINGS_MODULE=config.settings.prod"
  echo "SECRET_KEY=$(secret DJANGO_SECRET_KEY)"
  echo "JWT_SIGNING_KEY=$(secret JWT_SIGNING_KEY)"
  echo "DB_NAME=pg_platform"
  echo "DB_PASSWORD=$(secret DB_PASSWORD)"
  echo "REDIS_URL=$(secret REDIS_URL)"
  echo "REDIS_CACHE_URL=$(secret REDIS_CACHE_URL)"
  echo "BFF_ORIGIN_SECRET=$(secret BFF_ORIGIN_SECRET)"
  echo "RAZORPAY_KEY_ID=$(secret RAZORPAY_KEY_ID)"
  echo "RAZORPAY_KEY_SECRET=$(secret RAZORPAY_KEY_SECRET)"
  echo "RAZORPAY_WEBHOOK_SECRET=$(secret RAZORPAY_WEBHOOK_SECRET)"
  echo "EMAIL_HOST_PASSWORD=$(secret EMAIL_HOST_PASSWORD)"
  echo "SENTRY_DSN=$(secret SENTRY_DSN)"
  echo "GS_BUCKET_NAME=$PROJECT-media"
  echo "GS_PROJECT_ID=$PROJECT"
  echo "GS_SA_EMAIL=$(md instance/service-accounts/default/email)"   # signs media URLs as the VM's own account
  # SMTP settings (non-secret) come from VM metadata; unset ones are left out so settings defaults apply.
  for pair in EMAIL_HOST=email-host EMAIL_PORT=email-port EMAIL_HOST_USER=email-host-user \
              DEFAULT_FROM_EMAIL=default-from-email; do
    value="$(opt "${pair#*=}")"
    if [[ -n "$value" ]]; then echo "${pair%%=*}=$value"; fi
  done
  echo "FIREBASE_USE_ADC=True"
  echo "FIREBASE_PROJECT_ID=$PROJECT"
  echo "ALLOWED_HOSTS=api.pglive.in"
  echo "FRONTEND_BASE_URL=https://www.pglive.in"
  echo "REDIS_PASSWORD=$(secret REDIS_PASSWORD)"
  echo "WORKER_IP=$WORKER_IP"
  echo "SQL_CONNECTION=$SQL_CONNECTION"
  echo "IMAGE=$IMAGE"
} > .env.new
mv .env.new .env

gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
docker compose --env-file .env pull
docker compose --env-file .env up -d --remove-orphans
docker image prune -f >/dev/null
echo "Deployed $IMAGE"
