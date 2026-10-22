#!/usr/bin/env bash
# Phase 2: APIs, network, Artifact Registry, service accounts and their (narrow) roles, secrets shells.
#   infra/10-foundation.sh prod|staging
# Prerequisites done by hand: project created and billing linked; Cloud Identity group pglive-admins@ with
# 2-Step Verification enforced (admin MFA, docs/deployment.md); budgets and alerts created.
set -euo pipefail
source "$(dirname "$0")/env.sh" "$1"
g() { gcloud --project "$PROJECT" "$@"; }

echo "== APIs"
g services enable run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com \
  artifactregistry.googleapis.com compute.googleapis.com certificatemanager.googleapis.com \
  cloudscheduler.googleapis.com workflows.googleapis.com workflowexecutions.googleapis.com \
  iamcredentials.googleapis.com iap.googleapis.com logging.googleapis.com monitoring.googleapis.com \
  firebase.googleapis.com fcm.googleapis.com cloudresourcemanager.googleapis.com

echo "== Network (Direct VPC egress for Cloud Run + the worker VM)"
g compute networks describe "$NETWORK" >/dev/null 2>&1 || g compute networks create "$NETWORK" --subnet-mode=custom
g compute networks subnets describe "$SUBNET" --region "$REGION" >/dev/null 2>&1 || \
  g compute networks subnets create "$SUBNET" --network "$NETWORK" --region "$REGION" \
    --range "$SUBNET_RANGE" --enable-private-ip-google-access
fw() { g compute firewall-rules describe "$1" >/dev/null 2>&1 || g compute firewall-rules create "$@"; }
fw pglive-allow-iap-ssh --network "$NETWORK" --direction INGRESS --allow tcp:22 --source-ranges 35.235.240.0/20 --target-tags worker
# Cloud Run Direct VPC egress sources from the subnet itself.
fw pglive-allow-redis --network "$NETWORK" --direction INGRESS --allow tcp:6379 --source-ranges "$SUBNET_RANGE" --target-tags worker
fw pglive-deny-other-ingress --network "$NETWORK" --direction INGRESS --action DENY --rules all --source-ranges 0.0.0.0/0 --priority 65000

echo "== Artifact Registry"
g artifacts repositories describe pglive --location "$REGION" >/dev/null 2>&1 || \
  g artifacts repositories create pglive --repository-format docker --location "$REGION" \
    --description "PGLive images"
# Keep the 15 newest versions of each image; delete untagged leftovers after a day.
g artifacts repositories set-cleanup-policies pglive --location "$REGION" --policy=<(cat <<'JSON'
[{"name":"keep-recent","action":{"type":"Keep"},"mostRecentVersions":{"keepCount":15}},
 {"name":"drop-untagged","action":{"type":"Delete"},"condition":{"tagState":"untagged","olderThan":"86400s"}}]
JSON
) 2>/dev/null || true

echo "== Service accounts"
# IAM allows only a few account creations per minute per project (429 RESOURCE_EXHAUSTED): retry after a pause.
for name in api web worker migrate bootstrap scheduler export export-verify smoke deployer; do
  for attempt in 1 2 3 4; do
    g iam service-accounts describe "$(sa "sa-$name")" >/dev/null 2>&1 && break
    g iam service-accounts create "sa-$name" --display-name "PGLive $name" && break
    echo "  retrying sa-$name in 65s (attempt $attempt)"; sleep 65
  done
  g iam service-accounts describe "$(sa "sa-$name")" >/dev/null   # fail here, not at the first binding
done
bind() { g projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$1" --role "$2" --condition=None >/dev/null; }
for name in api worker migrate bootstrap; do bind "$(sa sa-$name)" roles/cloudsql.client; done
for name in api web worker migrate bootstrap scheduler export export-verify smoke; do bind "$(sa sa-$name)" roles/logging.logWriter; done
bind "$(sa sa-worker)" roles/artifactregistry.reader
bind "$(sa sa-deployer)" roles/artifactregistry.writer
# What infra/deploy.sh and 30-services.sh actually do (docs/deployment.md, "Release pipeline"):
#   run.admin             deploy services/jobs AND set the job IAM policy (run.developer cannot setIamPolicy)
#   secretmanager.viewer  list secret versions before deploying (never reads a value)
#   cloudscheduler.admin  create/update the scheduled jobs
#   workflows.editor      deploy the weekly export workflow
#   logging.viewer        read 5xx logs during the canary watch
#   compute.viewer, iap.tunnelResourceAccessor, compute.osAdminLogin   ssh to the worker VM through IAP
# It deliberately has no project IAM admin: the one runtime binding that needed it is made below.
bind "$(sa sa-deployer)" roles/run.admin
bind "$(sa sa-deployer)" roles/secretmanager.viewer
bind "$(sa sa-deployer)" roles/cloudscheduler.admin
bind "$(sa sa-deployer)" roles/workflows.editor
bind "$(sa sa-deployer)" roles/logging.viewer
bind "$(sa sa-deployer)" roles/compute.viewer
bind "$(sa sa-deployer)" roles/iap.tunnelResourceAccessor
bind "$(sa sa-deployer)" roles/compute.osAdminLogin
# The weekly-export scheduler starts the export workflow (moved here from 30-services.sh).
bind "$(sa sa-scheduler)" roles/workflows.invoker
# FCM send via Application Default Credentials (WP8).
bind "$(sa sa-api)" roles/firebasecloudmessaging.admin
bind "$(sa sa-worker)" roles/firebasecloudmessaging.admin
# Keyless GCS URL signing: each runtime SA signs as itself.
for name in api worker; do
  g iam service-accounts add-iam-policy-binding "$(sa sa-$name)" \
    --member "serviceAccount:$(sa sa-$name)" --role roles/iam.serviceAccountTokenCreator >/dev/null
done
# The deployer may deploy revisions that run as the runtime accounts.
for name in api web worker migrate bootstrap export-verify smoke; do
  g iam service-accounts add-iam-policy-binding "$(sa sa-$name)" \
    --member "serviceAccount:$(sa sa-deployer)" --role roles/iam.serviceAccountUser >/dev/null
done
# Backup operator: create + poll on-demand backups before every migration (CI waits for SUCCESSFUL).
g iam roles describe pglive.backupOperator >/dev/null 2>&1 || g iam roles create pglive.backupOperator \
  --title "PGLive backup operator" \
  --permissions cloudsql.backupRuns.create,cloudsql.backupRuns.get,cloudsql.backupRuns.list,cloudsql.instances.get
bind "$(sa sa-deployer)" "projects/$PROJECT/roles/pglive.backupOperator"
g iam roles describe pglive.sqlExporter >/dev/null 2>&1 || g iam roles create pglive.sqlExporter \
  --title "PGLive SQL exporter" --permissions cloudsql.instances.export,cloudsql.instances.get
bind "$(sa sa-export)" "projects/$PROJECT/roles/pglive.sqlExporter"

echo "== Secret shells (values are added with: gcloud secrets versions add NAME --data-file=-)"
# REDIS_PASSWORD starts redis on the worker VM; REDIS_URL / REDIS_CACHE_URL are the full URLs (password
# included, e.g. redis://:PASSWORD@10.20.0.10:6379/0 and .../1) because Django and Celery read URLs.
for s in DJANGO_SECRET_KEY JWT_SIGNING_KEY DB_PASSWORD DB_MIGRATION_PASSWORD REDIS_PASSWORD REDIS_URL \
         REDIS_CACHE_URL BFF_ORIGIN_SECRET BFF_EDGE_KEY RAZORPAY_KEY_ID RAZORPAY_KEY_SECRET RAZORPAY_WEBHOOK_SECRET \
         EMAIL_HOST_PASSWORD SENTRY_DSN APP_MAINTENANCE_BYPASS_TOKEN SMOKE_USER_CREDENTIALS; do
  secret_exists "$s" || g secrets create "$s" --replication-policy=user-managed --locations "$REGION"
done
# Per-secret access: nothing gets project-wide secretAccessor.
allow() { g secrets add-iam-policy-binding "$1" --member "serviceAccount:$(sa "sa-$2")" --role roles/secretmanager.secretAccessor >/dev/null; }
for s in DJANGO_SECRET_KEY JWT_SIGNING_KEY DB_PASSWORD REDIS_PASSWORD REDIS_URL REDIS_CACHE_URL \
         BFF_ORIGIN_SECRET RAZORPAY_KEY_ID RAZORPAY_KEY_SECRET RAZORPAY_WEBHOOK_SECRET EMAIL_HOST_PASSWORD SENTRY_DSN APP_MAINTENANCE_BYPASS_TOKEN; do
  allow "$s" api; allow "$s" worker
done
allow DB_MIGRATION_PASSWORD migrate; allow DJANGO_SECRET_KEY migrate; allow JWT_SIGNING_KEY migrate
allow DB_PASSWORD bootstrap; allow DJANGO_SECRET_KEY bootstrap; allow JWT_SIGNING_KEY bootstrap
allow BFF_ORIGIN_SECRET web
# BFF_EDGE_KEY: the web service sends it, the edge (nginx on the worker VM) checks it, so it can tell BFF traffic
# from direct API clients for rate limiting (docs/deployment.md). Generate: openssl rand -hex 32
allow BFF_EDGE_KEY web; allow BFF_EDGE_KEY worker
allow SMOKE_USER_CREDENTIALS smoke
echo "Done. Next: infra/20-data.sh $ENVIRONMENT"
