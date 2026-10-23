# Manual deployment — step by step (GCP, pglive.in)

Written for one operator creating everything by hand. It builds exactly the architecture in
[deployment.md](deployment.md) §1; the `infra/*.sh` scripts are the same steps automated, so read them when you
want the exact flags. Run the commands in **Google Cloud Shell** (gcloud, docker, psql and git are installed and
already signed in) or on your own machine with the gcloud CLI. Console clicks are given where they are easier
than the CLI.

> Status: none of this has been run against a real project yet. Expect small corrections on the first pass and
> record them in this file. Do the whole thing once in `pglive-staging` first (see the last section for what
> differs), then repeat for `pglive-prod`.

## 0. Variables used throughout

Paste once per Cloud Shell session. Change `ENV` to `staging` for the rehearsal.

```bash
export ENV=prod
export PROJECT=pglive-$ENV
export REGION=asia-south1
export ZONE=asia-south1-a
export SQL_INSTANCE=pglive-pg-$ENV
export SQL_CONN=$PROJECT:$REGION:$SQL_INSTANCE
export DB_NAME=pg_platform
export MEDIA_BUCKET=$PROJECT-media
export BACKUP_BUCKET=$PROJECT-backups
export AR=$REGION-docker.pkg.dev/$PROJECT/pglive
export WORKER_IP=10.20.0.10
gcloud config set project $PROJECT
sa() { echo "sa-$1@$PROJECT.iam.gserviceaccount.com"; }   # sa api -> sa-api@...
```

Get the code at the commit you are releasing, so the images are reproducible:

```bash
git clone https://github.com/bunny737/PG-MANAGEMENT-WEB.git pglive && cd pglive
# Private repo: at the prompt, username = your GitHub user, password = a fine-grained token limited to this
# repository with Contents: read-only (delete it afterwards). Never put the token in the URL.
git checkout feature/gcp-deployment  # the branch must be pushed first; a fresh clone only has what GitHub has
git checkout <commit-sha>            # write the SHA down, it is your image tag
export SHA=$(git rev-parse --short=12 HEAD)
```

Don't `git pull` in this checkout until the release is fully deployed: `$SHA` and the images must stay on the
same commit. If a later fix is needed only in an `infra/` file you are about to run, apply it to that file.

## 1. Project, billing, budget, APIs  (Console)

1. Console → *Create project* → ID `pglive-prod` (and later `pglive-staging`). Billing → link the billing account.
2. Billing → *Budgets & alerts* → create a budget with alerts at 50 %, 80 %, 100 %, emailing you.
3. Enable the APIs:

```bash
gcloud services enable run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com \
  artifactregistry.googleapis.com compute.googleapis.com certificatemanager.googleapis.com \
  cloudscheduler.googleapis.com workflows.googleapis.com workflowexecutions.googleapis.com \
  iamcredentials.googleapis.com iap.googleapis.com logging.googleapis.com monitoring.googleapis.com \
  fcm.googleapis.com cloudresourcemanager.googleapis.com
```

4. IAM & Admin → *Organization policies* (only if you have an organisation): enforce
   `iam.disableServiceAccountKeyCreation`. No service-account keys are ever created in this setup.

## 2. Network and firewall  (Console: VPC network)

```bash
gcloud compute networks create pglive --subnet-mode=custom
gcloud compute networks subnets create pglive-$REGION --network pglive --region $REGION \
  --range 10.20.0.0/24 --enable-private-ip-google-access
gcloud compute firewall-rules create pglive-allow-iap-ssh --network pglive --allow tcp:22 \
  --source-ranges 35.235.240.0/20 --target-tags worker
gcloud compute firewall-rules create pglive-allow-redis --network pglive --allow tcp:6379 \
  --source-ranges 10.20.0.0/24 --target-tags worker
```

Cloud Run reaches Redis over *Direct VPC egress* from this subnet; nothing else may reach port 6379 and SSH is
IAP-only (no public SSH).

New projects also get a `default` network whose firewall allows SSH (22) and RDP (3389) from the whole internet.
Nothing in this setup uses it; delete it so a VM created there by mistake isn't exposed:

```bash
for r in default-allow-icmp default-allow-internal default-allow-rdp default-allow-ssh; do
  gcloud compute firewall-rules delete $r --quiet; done
gcloud compute networks delete default --quiet
```

## 3. Artifact Registry and the two images

```bash
gcloud artifacts repositories create pglive --repository-format docker --location $REGION
gcloud auth configure-docker $REGION-docker.pkg.dev --quiet

docker build -f backend/Dockerfile.prod -t $AR/pglive-api:$SHA backend
docker push $AR/pglive-api:$SHA
```

The web image bakes `NEXT_PUBLIC_*` and company details in at build time, so build it with this environment's
values (`SITE_URL=https://www.pglive.in`; `APP_STATUS=comingSoon` and `SIGNUP_ENABLED=false` until launch day):

```bash
docker build -f frontend/Dockerfile.prod -t $AR/pglive-web:$SHA \
  --build-arg SITE_URL=https://www.pglive.in --build-arg SITE_ENV=production \
  --build-arg COMPANY_NAME="…" --build-arg COMPANY_ADDRESS="…" \
  --build-arg APP_STATUS=comingSoon --build-arg SIGNUP_ENABLED=false --build-arg PLAY_STORE_URL= \
  --build-arg NEXT_PUBLIC_FIREBASE_API_KEY=… --build-arg NEXT_PUBLIC_FIREBASE_PROJECT_ID=… \
  --build-arg NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=… --build-arg NEXT_PUBLIC_FIREBASE_APP_ID=… \
  --build-arg NEXT_PUBLIC_FIREBASE_VAPID_KEY=… --build-arg NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=… \
  --build-arg NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID=… frontend
docker push $AR/pglive-web:$SHA
```

Leave the Firebase/Maps values empty for now if those aren't created yet (section 14) and rebuild later — the
site works without them, push notifications and the map picker do not.

**If `docker push` fails with `connection refused`** (it did for the API image from Cloud Shell on the first run,
while the web image pushed fine), build in Cloud Build instead; it pushes from inside Google's network. New
projects run builds as the Compute Engine default account, which needs these roles first. A `PERMISSION_DENIED`
straight after enabling the API is propagation: wait two minutes and resubmit.

```bash
gcloud services enable cloudbuild.googleapis.com
PN=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
for r in roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectViewer; do
  gcloud projects add-iam-policy-binding $PROJECT --member "serviceAccount:$PN-compute@developer.gserviceaccount.com" \
    --role $r --condition=None >/dev/null
done
cat > /tmp/cb-api.yaml <<EOF
steps:
- name: gcr.io/cloud-builders/docker
  args: ['build','-f','Dockerfile.prod','-t','$AR/pglive-api:$SHA','.']
images: ['$AR/pglive-api:$SHA']
options:
  logging: CLOUD_LOGGING_ONLY
EOF
gcloud builds submit backend --config /tmp/cb-api.yaml
```

Check both images are there before going on: `gcloud artifacts docker images list $AR --format='value(package,tags)'`.

## 4. Service accounts and roles  (Console: IAM → Service accounts)

One account per job, so a leaked credential can do only that job:

```bash
# IAM allows only a few creations per minute per project (429 RESOURCE_EXHAUSTED); the pause avoids it.
for n in api web worker migrate bootstrap scheduler export export-verify smoke; do
  gcloud iam service-accounts create sa-$n --display-name "PGLive $n"; sleep 10
done
gcloud iam service-accounts list --format='value(email)' | grep -c '^sa-'     # must print 9 before going on

bind() { gcloud projects add-iam-policy-binding $PROJECT --member "serviceAccount:$(sa $1)" --role "$2" --condition=None >/dev/null; }
for n in api worker migrate bootstrap; do bind $n roles/cloudsql.client; done
for n in api web worker migrate bootstrap scheduler export export-verify smoke; do bind $n roles/logging.logWriter; done
bind worker roles/artifactregistry.reader
bind api roles/firebasecloudmessaging.admin; bind worker roles/firebasecloudmessaging.admin

# Keyless GCS URL signing: api and worker sign as themselves.
for n in api worker; do
  gcloud iam service-accounts add-iam-policy-binding $(sa $n) \
    --member "serviceAccount:$(sa $n)" --role roles/iam.serviceAccountTokenCreator
done
```

Custom roles for the weekly export (only needed once you set up section 13):

```bash
gcloud iam roles create pglive.sqlExporter --project $PROJECT --title "PGLive SQL exporter" \
  --permissions cloudsql.instances.export,cloudsql.instances.get
gcloud iam roles create pglive.backupObjectReader --project $PROJECT --title "PGLive backup object reader" \
  --permissions storage.objects.get,storage.objects.list,storage.objects.update
bind export projects/$PROJECT/roles/pglive.sqlExporter
```

You, as the human, deploy with your own Owner login, so no deployer account is needed. (`sa-deployer` exists only
for the GitHub workflows, if you adopt them later.)

## 5. Secrets  (Console: Security → Secret Manager)

Create each secret with the *Secret Manager* page or CLI, region-restricted to `asia-south1`. Generate values
with `openssl` and keep them out of shell history files and chat. Hex passwords avoid quoting trouble in URLs
and psql.

```bash
mk() { gcloud secrets create $1 --replication-policy=user-managed --locations $REGION; }
put() { printf '%s' "$2" | gcloud secrets versions add $1 --data-file=-; }

for s in DJANGO_SECRET_KEY JWT_SIGNING_KEY DB_PASSWORD DB_MIGRATION_PASSWORD REDIS_PASSWORD REDIS_URL \
  REDIS_CACHE_URL BFF_ORIGIN_SECRET RAZORPAY_KEY_ID RAZORPAY_KEY_SECRET RAZORPAY_WEBHOOK_SECRET \
  EMAIL_HOST_PASSWORD SENTRY_DSN APP_MAINTENANCE_BYPASS_TOKEN SMOKE_USER_CREDENTIALS; do mk $s; done

put DJANGO_SECRET_KEY        "$(openssl rand -base64 64 | tr -d '\n')"
put JWT_SIGNING_KEY          "$(openssl rand -base64 64 | tr -d '\n')"   # different from the line above
put DB_PASSWORD              "$(openssl rand -hex 24)"
put DB_MIGRATION_PASSWORD    "$(openssl rand -hex 24)"
RP=$(openssl rand -hex 24)
put REDIS_PASSWORD           "$RP"
put REDIS_URL                "redis://:$RP@$WORKER_IP:6379/0"
put REDIS_CACHE_URL          "redis://:$RP@$WORKER_IP:6379/1"
unset RP
put BFF_ORIGIN_SECRET        "$(openssl rand -hex 32)"
put APP_MAINTENANCE_BYPASS_TOKEN "$(openssl rand -hex 24)"
```

Values you supply yourself: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` (live keys only —
test keys and test-mode Plan IDs must never reach the production DB), `EMAIL_HOST_PASSWORD` (your SMTP provider),
`SENTRY_DSN` (or a single space if you have none), `SMOKE_USER_CREDENTIALS` (later, section 12).

**Every secret needs at least one version** or Cloud Run refuses to deploy anything that references it. Until you
have the real values, store a placeholder and add the real one as a new version later (then redeploy, section 17):

```bash
for s in RAZORPAY_KEY_ID RAZORPAY_KEY_SECRET RAZORPAY_WEBHOOK_SECRET EMAIL_HOST_PASSWORD; do put $s placeholder; done
put SENTRY_DSN " "
put SMOKE_USER_CREDENTIALS placeholder
```

With placeholders, payments and email simply don't work, and every Razorpay webhook is rejected (bad signature).
Settings refuse to boot in prod with the development `SECRET_KEY`, so don't leave a placeholder there.

Who may read what — nothing gets project-wide Secret Accessor:

```bash
allow() { gcloud secrets add-iam-policy-binding $1 --member "serviceAccount:$(sa $2)" --role roles/secretmanager.secretAccessor >/dev/null; }
for s in DJANGO_SECRET_KEY JWT_SIGNING_KEY DB_PASSWORD REDIS_PASSWORD REDIS_URL REDIS_CACHE_URL BFF_ORIGIN_SECRET \
  RAZORPAY_KEY_ID RAZORPAY_KEY_SECRET RAZORPAY_WEBHOOK_SECRET EMAIL_HOST_PASSWORD SENTRY_DSN APP_MAINTENANCE_BYPASS_TOKEN; do
  allow $s api; allow $s worker
done
allow DB_MIGRATION_PASSWORD migrate; allow DJANGO_SECRET_KEY migrate; allow JWT_SIGNING_KEY migrate
allow DB_PASSWORD bootstrap; allow DJANGO_SECRET_KEY bootstrap; allow JWT_SIGNING_KEY bootstrap
allow BFF_ORIGIN_SECRET web
allow SMOKE_USER_CREDENTIALS smoke
```

## 6. Cloud SQL (PostgreSQL 16) and the two database roles  (Console: SQL)

Create the instance (console: *Create instance → PostgreSQL → Enterprise*, or):

```bash
gcloud sql instances create $SQL_INSTANCE --database-version POSTGRES_16 --edition ENTERPRISE \
  --tier db-custom-1-3840 --region $REGION --availability-type ZONAL \
  --storage-type SSD --storage-size 20GB --storage-auto-increase \
  --ssl-mode ENCRYPTED_ONLY \
  --backup --backup-start-time 20:30 --retained-backups-count 14 \
  --enable-point-in-time-recovery --retained-transaction-log-days 7 \
  --maintenance-window-day SUN --maintenance-window-hour 20 --maintenance-release-channel production \
  --database-flags log_min_duration_statement=500,log_connections=on,log_disconnections=on \
  --deletion-protection
```

- Public IP stays on, but **add no authorized networks, ever**: the app uses the `/cloudsql` socket and you use
  the Auth Proxy.
- `db-g1-small` (~$30/mo instead of ~$60) is an option during the trial; it then has no SLA. If you pick it, set
  `--max-instances 1` for the API in section 9 (connection budget in deployment.md).
- Times are UTC: `20:30` = 02:00 IST backups, Sunday `20` = Monday 01:30 IST window; adjust to taste.

Create the roles **with the SQL file, not `gcloud sql users create`** — that command makes the user a member of
`cloudsqlsuperuser`, which `check_db_roles` rejects.

```bash
# The postgres password lives only in this shell; set a new one whenever you need it again.
export PGPASSWORD=$(openssl rand -hex 24)
gcloud sql users set-password postgres --instance $SQL_INSTANCE --password "$PGPASSWORD"
# Cloud Shell: install the proxy once
curl -fso cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.1/cloud-sql-proxy.linux.amd64
chmod +x cloud-sql-proxy
./cloud-sql-proxy $SQL_CONN --port 5432 &        # keep running; Ctrl-C / kill %1 when done

psql "host=127.0.0.1 port=5432 user=postgres dbname=postgres" \
  -v migration_password="$(gcloud secrets versions access latest --secret DB_MIGRATION_PASSWORD)" \
  -v app_password="$(gcloud secrets versions access latest --secret DB_PASSWORD)" \
  -v db_name=$DB_NAME -f infra/sql/roles-1-roles.sql
```

(Pin whichever proxy version is current; check the release page.) `postgres` is only used here; the app never
gets its password. Grants (`roles-2-grants.sql`) are applied *after* the first migration, in section 10.

## 7. Buckets  (Console: Cloud Storage)

```bash
mkb() { gcloud storage buckets create gs://$1 --location $2 --default-storage-class STANDARD \
          --uniform-bucket-level-access --public-access-prevention; }
mkb $MEDIA_BUCKET  $REGION
gcloud storage buckets update gs://$MEDIA_BUCKET --versioning --soft-delete-duration=14d
cat > media-lifecycle.json <<'JSON'
{"rule":[{"action":{"type":"Delete"},"condition":{"daysSinceNoncurrentTime":60,"isLive":false}}]}
JSON
gcloud storage buckets update gs://$MEDIA_BUCKET --lifecycle-file=media-lifecycle.json
for n in api worker; do
  gcloud storage buckets add-iam-policy-binding gs://$MEDIA_BUCKET \
    --member "serviceAccount:$(sa $n)" --role roles/storage.objectUser
done

mkb $BACKUP_BUCKET asia-south2
gcloud storage buckets update gs://$BACKUP_BUCKET --retention-period=90d      # do NOT lock it yet
cat > backup-lifecycle.json <<'JSON'
{"rule":[{"action":{"type":"Delete"},"condition":{"age":91,"matchesPrefix":["sql/"]}}]}
JSON
gcloud storage buckets update gs://$BACKUP_BUCKET --lifecycle-file=backup-lifecycle.json
SQL_AGENT=$(gcloud sql instances describe $SQL_INSTANCE --format='value(serviceAccountEmailAddress)')
gcloud storage buckets add-iam-policy-binding gs://$BACKUP_BUCKET \
  --member "serviceAccount:$SQL_AGENT" --role roles/storage.objectCreator
for n in export export-verify; do
  gcloud storage buckets add-iam-policy-binding gs://$BACKUP_BUCKET \
    --member "serviceAccount:$(sa $n)" --role projects/$PROJECT/roles/pglive.backupObjectReader
done
```

Locking a retention policy is irreversible and puts a lien on the project: leave it unlocked until export →
restore → deletion has been proven.

## 8. The worker VM: Celery worker, one beat, Redis, and the nginx edge  (Console: Compute Engine)

Owner decision 2026-10-21: **no load balancer and no Cloud DNS.** GoDaddy's A records point straight at this VM's
static IP; nginx with a Let's Encrypt certificate on the VM forwards to Cloud Run (section 11). Cloud Run ingress is
`internal`, which admits this VM (same project's network) and nothing on the internet.

Reserve the static IP, open 80/443 for the edge only, and create the VM with that IP:

```bash
gcloud compute addresses create pglive-edge-ip --region $REGION
EDGE_IP=$(gcloud compute addresses describe pglive-edge-ip --region $REGION --format='value(address)'); echo $EDGE_IP
gcloud compute firewall-rules create pglive-allow-web --network pglive --allow tcp:80,tcp:443 \
  --source-ranges 0.0.0.0/0 --target-tags edge

gcloud compute instances create pglive-worker --zone $ZONE --machine-type e2-small \
  --network pglive --subnet pglive-$REGION --private-network-ip $WORKER_IP --address $EDGE_IP --tags worker,edge \
  --service-account $(sa worker) --scopes cloud-platform \
  --image-family debian-12 --image-project debian-cloud --boot-disk-size 20GB --boot-disk-type pd-balanced \
  --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
  --metadata region=$REGION,sql-connection=$SQL_CONN,enable-oslogin=TRUE
```

Write `$EDGE_IP` down: it is what GoDaddy points at. SSH stays IAP-only; Redis is bound to the private address and
firewalled to the subnet. Log in over IAP and install Docker (from Docker's own repository — Debian 12's has no
Compose v2 plugin), nginx and certbot:

```bash
gcloud compute ssh pglive-worker --zone $ZONE --tunnel-through-iap
# --- on the VM ---
sudo apt-get update && sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin \
  nginx certbot gettext-base unattended-upgrades
sudo mkdir -p /opt/pglive/edge && sudo chown -R $USER /opt/pglive
curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh && sudo bash add-google-cloud-ops-agent-repo.sh --also-install
exit
```

Copy the files and run the first worker deploy (it reads the secrets with the VM's own identity and writes a
root-only `.env`). The database must be migrated first (section 10):

```bash
gcloud compute scp infra/worker/docker-compose.yml infra/worker/deploy.sh pglive-worker:/opt/pglive/ \
  --zone $ZONE --tunnel-through-iap
gcloud compute scp infra/edge/pglive.conf.template infra/edge/setup-edge.sh pglive-worker:/opt/pglive/edge/ \
  --zone $ZONE --tunnel-through-iap
gcloud compute ssh pglive-worker --zone $ZONE --tunnel-through-iap \
  --command "chmod +x /opt/pglive/deploy.sh /opt/pglive/edge/setup-edge.sh && sudo /opt/pglive/deploy.sh $SHA"
```

Check: `sudo docker compose -f /opt/pglive/docker-compose.yml ps` shows redis, cloud-sql-proxy, worker, beat —
**exactly one `beat`**. The edge (nginx) is set up in section 11, once DNS points here.

## 9. Cloud Run services and jobs  (Console: Cloud Run)

Common values:

```bash
PN=$(gcloud projects describe $PROJECT --format='value(projectNumber)')   # used in the run.app hostnames
VPC="--network pglive --subnet pglive-$REGION --vpc-egress private-ranges-only"
SQLENV="DB_HOST=/cloudsql/$SQL_CONN;DB_NAME=$DB_NAME"
COMMON="DJANGO_SETTINGS_MODULE=config.settings.prod;GS_BUCKET_NAME=$MEDIA_BUCKET;GS_PROJECT_ID=$PROJECT;FIREBASE_USE_ADC=True;FIREBASE_PROJECT_ID=$PROJECT;FRONTEND_BASE_URL=https://www.pglive.in"
API_SECRETS="SECRET_KEY=DJANGO_SECRET_KEY:latest,JWT_SIGNING_KEY=JWT_SIGNING_KEY:latest,DB_PASSWORD=DB_PASSWORD:latest,BFF_ORIGIN_SECRET=BFF_ORIGIN_SECRET:latest,RAZORPAY_KEY_ID=RAZORPAY_KEY_ID:latest,RAZORPAY_KEY_SECRET=RAZORPAY_KEY_SECRET:latest,RAZORPAY_WEBHOOK_SECRET=RAZORPAY_WEBHOOK_SECRET:latest,EMAIL_HOST_PASSWORD=EMAIL_HOST_PASSWORD:latest,SENTRY_DSN=SENTRY_DSN:latest,APP_MAINTENANCE_BYPASS_TOKEN=APP_MAINTENANCE_BYPASS_TOKEN:latest,REDIS_URL=REDIS_URL:latest,REDIS_CACHE_URL=REDIS_CACHE_URL:latest"
```

The `^;^` prefix tells gcloud to separate env vars with `;`, because values contain commas (`ALLOWED_HOSTS`) and
`@` (`GS_SA_EMAIL`, email addresses). Don't put `;` in any value (e.g. `COMPANY_ADDRESS`).
These shell variables are lost when Cloud Shell restarts; re-paste this block (and section 0) after a restart.
`jobs create` fails if the job already exists — to change one, use `gcloud run jobs update` with the same flags.
SMTP settings are added later (section 14), not here.

**9.1 Jobs first** (they need no traffic and are what you use to migrate):

```bash
job() {   # name service-account db-user secrets command-args [--clear-cloudsql-instances]
  gcloud run jobs create "$1" --region $REGION --image $AR/pglive-api:$SHA --service-account "$(sa $2)" \
    --max-retries 0 --task-timeout 1800 --set-cloudsql-instances $SQL_CONN $VPC \
    --set-env-vars "^;^$COMMON;$SQLENV;DB_USER=$3;ALLOWED_HOSTS=api.pglive.in" \
    --set-secrets "$4" --command python --args "$5"
}
job pglive-migrate           migrate    migration_user "SECRET_KEY=DJANGO_SECRET_KEY:latest,JWT_SIGNING_KEY=JWT_SIGNING_KEY:latest,DB_PASSWORD=DB_MIGRATION_PASSWORD:latest" "manage.py,migrate,--noinput"
job pglive-check-roles       api        app_user       "$API_SECRETS" "manage.py,check_db_roles,--role,app_user"
job pglive-generate-invoices api        app_user       "$API_SECRETS" "manage.py,generate_subscription_invoices"
job pglive-check-grace-periods api      app_user       "$API_SECRETS" "manage.py,check_subscription_grace_periods"
```

(`migrate` uses `migration_user`'s password under the name `DB_PASSWORD` — the code only knows `DB_PASSWORD`.)

**9.2 API service.** The first deploy of a new service cannot use `--no-traffic`, so on this first pass it takes
traffic; that is safe because ingress is internal and nothing routes to it yet.

```bash
gcloud run deploy pglive-api --region $REGION --image $AR/pglive-api:$SHA --service-account $(sa api) \
  --ingress internal --allow-unauthenticated \
  --cpu 1 --memory 1Gi --concurrency 8 --timeout 60 --min-instances 1 --max-instances 3 \
  --set-cloudsql-instances $SQL_CONN $VPC \
  --startup-probe tcpSocket.port=8080,initialDelaySeconds=0,periodSeconds=3,failureThreshold=20 \
  --set-env-vars "^;^$COMMON;$SQLENV;DB_USER=app_user;ALLOWED_HOSTS=api.pglive.in,pglive-api-$PN.$REGION.run.app;CSRF_TRUSTED_ORIGINS=https://www.pglive.in,https://api.pglive.in;APP_VERSION_ENFORCEMENT=log;GS_SA_EMAIL=$(sa api);IAP_REQUIRED=False;SECURE_HSTS_SECONDS=0" \
  --set-secrets "$API_SECRETS"
```

`--allow-unauthenticated` here only means Cloud Run's own IAM check is off; the app does its own authentication
and the ingress setting keeps it off the open internet.

There is deliberately **no HTTP liveness probe** on the API: Cloud Run probes are plain HTTP with the container
address as `Host`, which production Django rejects (400 `DisallowedHost`), so the container would be restarted in a
loop. The TCP startup probe is enough; `/health/ready/` is checked through nginx (sections 11 and 16).

`ALLOWED_HOSTS` includes the `run.app` name because nginx must send it as `Host` (Cloud Run routes on Host);
`https://api.pglive.in` is in `CSRF_TRUSTED_ORIGINS` for the Django admin login; `IAP_REQUIRED=False` because
`/admin/` is guarded by the nginx allowlist (section 15), not IAP.

**9.3 Web service:**

```bash
gcloud run deploy pglive-web --region $REGION --image $AR/pglive-web:$SHA --service-account $(sa web) \
  --ingress internal --allow-unauthenticated \
  --cpu 1 --memory 512Mi --concurrency 40 --timeout 60 --min-instances 0 --max-instances 5 \
  --startup-probe tcpSocket.port=8080,periodSeconds=3,failureThreshold=20 \
  --liveness-probe httpGet.path=/api/health,httpGet.port=8080,periodSeconds=30 \
  --set-env-vars "^;^INTERNAL_API_URL=https://api.pglive.in;SITE_URL=https://www.pglive.in;COMPANY_NAME=…;COMPANY_ADDRESS=…;APP_STATUS=comingSoon;SIGNUP_ENABLED=false;CSP_MODE=report-only" \
  --set-secrets "BFF_ORIGIN_SECRET=BFF_ORIGIN_SECRET:latest"
```

`COMPANY_*` must equal what you built into the image. Keep `CSP_MODE=report-only` until a clean week of reports.

Cost note: `--min-instances 1` on the API is what keeps logins fast; `0` saves ~$10/mo at the price of cold
starts.

## 10. First database migration, grants, bootstrap

1. **Migrate** (as the owner role), then apply the grants once, then verify:

```bash
gcloud run jobs execute pglive-migrate --region $REGION --wait
# proxy still running from section 6:
psql "host=127.0.0.1 port=5432 user=postgres dbname=$DB_NAME" -f infra/sql/roles-2-grants.sql
gcloud run jobs execute pglive-check-roles --region $REGION --wait      # must succeed
```

From now on every migration auto-grants to `app_user` (`ALTER DEFAULT PRIVILEGES FOR ROLE migration_user`);
`pglive-check-roles` after each migrate proves it. If `check-roles` fails, read its log (Cloud Run → Jobs → Logs):
it names the exact table or ownership problem.

2. **Create the first Super Admin** with a temporary job and a temporary secret:

```bash
printf '%s' "$(openssl rand -base64 18)" | gcloud secrets create INITIAL_SUPERADMIN_PASSWORD \
  --replication-policy=user-managed --locations $REGION --data-file=-
gcloud secrets add-iam-policy-binding INITIAL_SUPERADMIN_PASSWORD \
  --member "serviceAccount:$(sa bootstrap)" --role roles/secretmanager.secretAccessor
gcloud run jobs create pglive-bootstrap --region $REGION --image $AR/pglive-api:$SHA \
  --service-account $(sa bootstrap) --max-retries 0 --task-timeout 600 --set-cloudsql-instances $SQL_CONN $VPC \
  --set-env-vars "^;^$COMMON;$SQLENV;DB_USER=app_user;ALLOWED_HOSTS=api.pglive.in;INITIAL_SUPERADMIN_EMAIL=you@yourdomain.com" \
  --set-secrets "SECRET_KEY=DJANGO_SECRET_KEY:latest,JWT_SIGNING_KEY=JWT_SIGNING_KEY:latest,DB_PASSWORD=DB_PASSWORD:latest,INITIAL_SUPERADMIN_PASSWORD=INITIAL_SUPERADMIN_PASSWORD:latest" \
  --command python --args "manage.py,bootstrap_platform"
gcloud run jobs execute pglive-bootstrap --region $REGION --wait
gcloud secrets versions access latest --secret INITIAL_SUPERADMIN_PASSWORD      # read it once to log in
```

The Super Admin signs in to **Django admin at `https://api.pglive.in/admin/`**, not the web app: the web login
deliberately rejects `super_admin` ("This account is not an Owner") because the Super Admin web screens (FE-13) aren't
built yet. So allowlist your IP first (section 15). The order matters — do not skip ahead: **log in to
`/admin/` → change the password (top right) → only then**:

```bash
gcloud run jobs delete pglive-bootstrap --region $REGION
gcloud secrets delete INITIAL_SUPERADMIN_PASSWORD
```

3. In Django admin set the platform config (trial days, grace days, property/resident
   caps — invariant 10) and create the live **Plans**. Never run `seed_data` here.

4. Start (or restart) the worker: re-run the `deploy.sh $SHA` command from section 8.

## 11. Domain and HTTPS: GoDaddy → VM → nginx → Cloud Run

No load balancer, no Cloud DNS (owner decision 2026-10-21). nginx on the VM does what the load balancer would have:
TLS (Let's Encrypt), HSTS, the bare-domain redirect, the client-IP header, login rate limits and the `/admin/`
allowlist. Config: `infra/edge/pglive.conf.template`, installed by `infra/edge/setup-edge.sh`. It was tested
locally against real nginx: encoded paths and queries pass through byte for byte (the BFF signature needs this),
a client-sent `X-PGLive-Client-IP` is overwritten, HSTS/redirects/rate limit/admin deny all behave.

**1. GoDaddy DNS** (*My Products → pglive.in → DNS*). Lower TTL to 600 (GoDaddy's minimum) a day before if records
already exist. Then:

| Type | Name | Value |
|---|---|---|
| A | @ | `$EDGE_IP` |
| A | www | `$EDGE_IP` |
| A | api | `$EDGE_IP` |

Delete any GoDaddy "parked" A record or forwarding for `@`/`www`. Keep MX/TXT records for email. Wait until
`dig +short pglive.in www.pglive.in api.pglive.in` (Cloud Shell) returns `$EDGE_IP` three times.

**2. Certificate and nginx.** The Cloud Run hostnames follow `SERVICE-PROJECTNUMBER.REGION.run.app`:

```bash
PN=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
API_HOST=pglive-api-$PN.$REGION.run.app
WEB_HOST=pglive-web-$PN.$REGION.run.app
gcloud run services describe pglive-api --region $REGION --format='value(metadata.annotations."run.googleapis.com/urls")'   # lists $API_HOST
gcloud compute ssh pglive-worker --zone $ZONE --tunnel-through-iap --command \
  "sudo API_HOST=$API_HOST WEB_HOST=$WEB_HOST LE_EMAIL=you@yourdomain.com HSTS_MAX_AGE=300 /opt/pglive/edge/setup-edge.sh"
```

The script gets one certificate for `pglive.in`, `www` and `api` (HTTP-01 on port 80, which is why DNS must point
here first), installs the config and reloads nginx. Renewal is automatic (certbot's timer) and reloads nginx.

**3. Verify from Cloud Shell:**

```bash
curl -sI https://pglive.in | grep -iE '^(HTTP|location|strict)'          # 301 -> https://www.pglive.in/, HSTS
curl -sI https://www.pglive.in | grep -iE '^(HTTP|strict)'                # 200, HSTS
curl -s  https://api.pglive.in/health/ready/                              # {"status": "ok", ... "raw_uri": "ok"}
curl -s -o /dev/null -w '%{http_code}\n' https://api.pglive.in/admin/     # 403 until you add your IP
curl -sI http://www.pglive.in | grep -i '^location'                       # https://www.pglive.in/
```

**4. HSTS ramp**: re-run the step 2 command with `HSTS_MAX_AGE=86400`, then `604800`, then `31536000`, a few days
apart, checking step 3 each time.

**What this setup gives up compared with a load balancer** (accepted for now; `infra/40-edge.sh` is the way back):
the VM is a single point of failure for the whole site (if it's down, so is pglive.in — alert on it, section 16);
no Cloud Armor WAF (nginx rate-limits the login endpoints); `/admin/` is protected by an IP allowlist + the Django
password instead of IAP + Google 2-Step Verification; every web request makes two hops through the VM, so watch its
CPU and move to `e2-medium` or an LB if it is busy.

## 12. Scheduler (nightly jobs) and the smoke user

```bash
S="--location $REGION --time-zone Asia/Kolkata --http-method POST --oauth-service-account-email $(sa scheduler) --oauth-token-scope https://www.googleapis.com/auth/cloud-platform --max-retry-attempts 3 --min-backoff 60s --max-backoff 600s"
API=https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs
gcloud scheduler jobs create http pglive-generate-invoices --schedule "0 2 * * *"  --uri $API/pglive-generate-invoices:run $S
gcloud scheduler jobs create http pglive-check-grace-periods --schedule "30 2 * * *" --uri $API/pglive-check-grace-periods:run $S
for j in pglive-generate-invoices pglive-check-grace-periods; do
  gcloud run jobs add-iam-policy-binding $j --region $REGION \
    --member "serviceAccount:$(sa scheduler)" --role roles/run.invoker
done
```

Use **OAuth** (not OIDC) here: these are `googleapis.com` endpoints. Run each once by hand
(`gcloud run jobs execute … --wait`) and confirm it succeeds before trusting the schedule. The periodic
tasks stored in the database run on the worker VM's single beat, not here.

Smoke test, optional on the very first pass (you are checking by hand): create the `smoke` job and the dedicated
`smoke@pglive.in` account later, following deployment.md §6, once releases become routine.

## 13. Weekly export (backups outside the project's own backups)

Cloud SQL's automatic backups and PITR cover most failures; the export protects against losing the instance or
region. Minimum viable manual version — run weekly until the Workflow is deployed:

```bash
gcloud sql export sql $SQL_INSTANCE gs://$BACKUP_BUCKET/sql/pg_platform-$(date -u +%Y%m%d-%H%M%S)Z.sql.gz \
  --database=$DB_NAME
```

Automated version: create the `pglive-export-verify` job (same pattern as section 9.1 with `sa-export-verify`,
`--clear-cloudsql-instances`, `EXPORT_BUCKET`, command `manage.py verify_latest_export`), then deploy
`infra/workflows/weekly-export.yaml` as workflow `pglive-weekly-export` running as `sa-export`, grant `sa-export`
`roles/run.invoker` on the job, grant `sa-scheduler` `roles/workflows.invoker`, and add a scheduler job for
`Wed 22:30` pointing at the workflow's `…/executions` URL. **Before launch you must restore one export into a
scratch instance in the separate `pglive-dr-test` project** (never staging) and time it — see `infra/dr/restore-drill.sh`
and deployment.md §8. An export you have never restored is not a backup.

## 14. Third-party configuration

- **Razorpay** (platform subscriptions only — never resident rent). Dashboard → Webhooks → URL
  `https://api.pglive.in/api/v1/subscriptions/webhook/`, subscription events, a new secret; put the same secret in
  `RAZORPAY_WEBHOOK_SECRET`. Create the Plans in the live account through the app/admin so `razorpay_plan_id` is a
  **live-mode** ID — test-mode IDs must never reach the production DB. Add new secret versions, then redeploy
  `pglive-api` and the VM so they pick up `:latest`.
- **Firebase** (FCM only): add Firebase to the project, register a web app for `https://www.pglive.in`, create a
  VAPID key, restrict the web API key to referrer `https://www.pglive.in/*`; put the values in the web image build
  (section 3) and rebuild/redeploy `pglive-web`. The backend uses the service account (no key file).
  Production's Firebase is its **own project, `pglive-prod-e57a1`**, not `pglive-prod`. The backend must send through
  the project the browsers registered with, so: grant `sa-api` and `sa-worker` `roles/firebasecloudmessaging.admin`
  **on `pglive-prod-e57a1`**; set `FIREBASE_PROJECT_ID=pglive-prod-e57a1` on `pglive-api` and the jobs (export it
  before `30-services.sh`, which otherwise defaults to `$PROJECT`); and set VM metadata
  `firebase-project-id=pglive-prod-e57a1`, which `worker/deploy.sh` reads.
- **Google Maps**: new key restricted to HTTP referrer `https://www.pglive.in/*` and to **Maps JavaScript API,
  Places API (New) and Geocoding API** (the location picker uses all three; a key limited to Maps JavaScript only
  breaks address search and reverse geocoding), with a quota cap. Enable those three APIs on the project. Also
  create a **Map ID** (Map Management, JavaScript, vector). The key and the Map ID are build args for the web image
  (`NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`, `NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID`); without a key the picker shows
  "Map unavailable" and manual coordinates still work.
- **Email**: SPF, DKIM, DMARC at GoDaddy. Email is sent by both the API (account emails) and the worker
  (notifications), so both need the SMTP settings; the password is the `EMAIL_HOST_PASSWORD` secret (new version).
  ```bash
  gcloud run services update pglive-api --region $REGION \
    --update-env-vars "EMAIL_HOST=smtp.example.com,EMAIL_PORT=587,EMAIL_HOST_USER=…,DEFAULT_FROM_EMAIL=PGLive <no-reply@pglive.in>"
  for j in pglive-generate-invoices pglive-check-grace-periods; do
    gcloud run jobs update $j --region $REGION --update-env-vars "EMAIL_HOST=smtp.example.com,EMAIL_PORT=587,EMAIL_HOST_USER=…,DEFAULT_FROM_EMAIL=PGLive <no-reply@pglive.in>"
  done
  # The worker VM reads them from instance metadata at each deploy.sh run:
  gcloud compute instances add-metadata pglive-worker --zone $ZONE \
    --metadata "email-host=smtp.example.com,email-port=587,email-host-user=…,default-from-email=PGLive <no-reply@pglive.in>"
  gcloud compute ssh pglive-worker --zone $ZONE --tunnel-through-iap --command "sudo /opt/pglive/deploy.sh $SHA"
  ```
  Leave out any setting you don't need rather than setting it empty (an empty `EMAIL_PORT` stops Django booting).

## 15. Admin access (`/admin/`)

Without a load balancer there is no IAP, so the API runs with `IAP_REQUIRED=False` and nginx admits `/admin/` only
from listed addresses; everyone else gets 403 before Django is reached. Django's own login is the second layer.
This is weaker than IAP + Google 2-Step Verification (no MFA on Django admin) — keep the list short, use a long
unique admin password.

Open `https://api.pglive.in/admin/` once (you get 403), then read the address nginx actually saw — more reliable than
an "what is my IP" site, which may show an IPv6 address while the site is reached over IPv4:

```bash
gcloud compute ssh pglive-worker --zone $ZONE --tunnel-through-iap --command \
  "sudo grep ' /admin/' /var/log/nginx/access.log | tail -3"        # first field of each line = your IP
```

Add it (type the real address; a placeholder or an empty value writes `allow ;`, which nginx rejects — the running
config stays, but delete that line before the next reload):

```bash
gcloud compute ssh pglive-worker --zone $ZONE --tunnel-through-iap --command \
  "sudo sed -i '1i allow 203.0.113.10;' /etc/nginx/pglive-admin-allow.conf && sudo nginx -t && sudo systemctl reload nginx"
```

`allow` lines go above `deny all;`, which must stay last. Home connections often change IP; remove old lines when
they do (`sudo nano /etc/nginx/pglive-admin-allow.conf`, then `sudo nginx -t && sudo systemctl reload nginx`).

## 16. Alerts and the go-live check

- **Monitoring** (Console: Monitoring → Alerting): uptime checks on `https://www.pglive.in/api/health` and
  `https://api.pglive.in/health/ready/` (these go through nginx, so they also cover the VM edge); alerts for the
  uptime checks failing, VM CPU/disk/memory, 5xx rate, Cloud SQL CPU/connections/disk, Cloud Run instances at max,
  and any failed job; notification channel = your email + phone. The VM is now the front door: its uptime alert is
  the one that matters most.
- **Login rate limit**: nginx allows 60 requests/minute per IP (burst 20) on `/api/auth/*` and `/api/v1/auth/*`;
  the app's own throttles stay underneath.
- **Go-live checklist** (every line must be true): billing account upgraded from trial · budgets on · backups and PITR
  on, deletion protection on · one export restored in `pglive-dr-test` and timed · `check_db_roles` green ·
  bootstrap job and password secret deleted · Razorpay live keys + webhook + unsigned webhooks off
  (`RAZORPAY_ALLOW_UNSIGNED_WEBHOOKS` not set) · HSTS verified on all three hosts · `/admin/` returns 403 except from
  your listed IPs · certificate auto-renewal tested (`sudo certbot renew --dry-run` on the VM) · Aadhaar/PAN upload
  either legally signed off or switched off · worker VM shows exactly one beat · `APP_STATUS`/`SIGNUP_ENABLED`
  flipped (rebuild web) on launch day.

## 17. Releasing a new version by hand

```bash
git checkout <new-sha>; export SHA=$(git rev-parse --short=12 HEAD)
# 1. build + push both images (section 3)
# 2. production only: on-demand backup, wait for SUCCESSFUL
gcloud sql backups create --instance $SQL_INSTANCE --description "pre-release $SHA"
gcloud sql backups list --instance $SQL_INSTANCE --limit 1            # status SUCCESSFUL before continuing
# 3. point the jobs at the new image, migrate, verify roles
for j in pglive-migrate pglive-check-roles pglive-generate-invoices pglive-check-grace-periods; do
  gcloud run jobs update $j --region $REGION --image $AR/pglive-api:$SHA
done
gcloud run jobs execute pglive-migrate --region $REGION --wait && \
gcloud run jobs execute pglive-check-roles --region $REGION --wait
# 4. new revisions without traffic, then look at them via the tag
gcloud run deploy pglive-api --region $REGION --image $AR/pglive-api:$SHA --no-traffic --tag candidate
gcloud run deploy pglive-web --region $REGION --image $AR/pglive-web:$SHA --no-traffic --tag candidate
# 5. send 10 %, watch Logs Explorer for 5xx for ten minutes, then 100 %
gcloud run services update-traffic pglive-api --region $REGION --to-tags candidate=10
gcloud run services update-traffic pglive-web --region $REGION --to-tags candidate=10
gcloud run services update-traffic pglive-api --region $REGION --to-latest
gcloud run services update-traffic pglive-web --region $REGION --to-latest
# 6. the worker
gcloud compute ssh pglive-worker --zone $ZONE --tunnel-through-iap --command "sudo /opt/pglive/deploy.sh $SHA"
```

`--set-env-vars`/`--set-secrets` carry over from the previous revision when you only pass `--image`.
The tagged candidate URL is on internal ingress, so you can't open it from a laptop; that is what the
`pglive-smoke` job (deployment.md §6) automates. Until it exists, use the 10 % step and watch the logs.

**Rollback** (application): `gcloud run services update-traffic pglive-api --region $REGION --to-revisions
<previous-revision>=100` (list with `gcloud run revisions list --service pglive-api --region $REGION`); the same
for `pglive-web`; for the VM, `sudo /opt/pglive/deploy.sh <previous-sha>`. Migrations are expand/contract, so the
previous code runs against the new schema. Database recovery from a bad migration is deployment.md §8 (PITR clone).

## Deploying production directly (owner decision 2026-10-20: no staging rehearsal)

Staging was meant to catch first-run mistakes in commands nobody has run yet. Without it, production is the
rehearsal, so make that safe. While there are no users, a mistake costs only time: **delete and recreate anything**
(Cloud SQL deletion protection can be switched off until launch, the database can be dropped and re-migrated).
After the first real tenant signs up, that stops being true. So:

1. **Show only "coming soon" until every check below passes.** Ship as `APP_STATUS=comingSoon`,
   `SIGNUP_ENABLED=false`. The A records have to exist before launch here (Let's Encrypt validates over them,
   section 11), so the domain is reachable early — those two settings are what keep it closed.
2. **Budget alert first** (section 1 step 2), before creating any resource. Upgrade the billing account from trial
   before launch.
3. **Razorpay: live keys only, no test data in this database.** Never create test-mode Plans here — their
   `razorpay_plan_id` would sit in the production DB. Without staging, the stale and out-of-order webhook cases are
   covered by the automated tests (`test_webhook_policy.py`, `test_webhook_ordering.py`, `test_webhook_delivery.py`)
   and `ci/integration/run.sh`, not by a real-infrastructure run. Verify the end-to-end path with one real
   minimum-amount subscription, then cancel and refund it, and watch the `razorpay_webhook_events` rows and
   `subscription.stale_event_ignored` logs. If you want the full conflicting-event rehearsal on real
   infrastructure later, do it in a throwaway project, not here.
4. **Rollback drill before launch, on prod while it is empty:** deploy a second revision of `pglive-api`, shift
   traffic to it, then roll back (section 17). Time it. Do the same for the worker VM with the previous SHA.
5. **Restore drill is still mandatory before signups open**, and still in a separate `pglive-dr-test` project
   (never in prod): export, restore, `check_db_roles`, record the duration (`infra/dr/restore-drill.sh`).
6. **Run each job once by hand** (`gcloud run jobs execute … --wait`) and read its log before trusting a
   schedule: migrate, check-roles, generate-invoices, check-grace-periods.
7. **Test the edge before launch**: certificate renewal (`sudo certbot renew --dry-run`), the `/admin/` 403 from an
   unlisted address, and a 429 after ~80 rapid login attempts from one IP.
8. **Keep a written log** of every command that needed a fix; fold the fixes back into this file and `infra/`.

The table below is only for a future staging project.

## Rehearsal in `pglive-staging`: what differs

| | production | staging |
|---|---|---|
| Project / names | `pglive-prod` | `export ENV=staging` → `pglive-staging`, `pglive-pg-staging`, … |
| nginx edge + certificates | yes (sections 11, 15) | no — skip them |
| Cloud Run ingress | `internal` (only the VM edge) | `all`; add the service's `*.run.app` host to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`, and set the web `INTERNAL_API_URL` to the API's `run.app` URL |
| Razorpay | live | **test** keys (so test webhooks can arrive); exercise duplicated, out-of-order and `cancelled`-then-`charged` events |
| Cloud SQL | `db-custom-1-3840`, deletion protection | `db-g1-small`, `--max-instances 1`; stop it when idle (`gcloud sql instances patch … --activation-policy NEVER`) |
| Weekly export | scheduled | skip |

Do in staging before touching production: the full section 10, one release (section 17), one rollback, one
export + restore into `pglive-dr-test`, and the webhook cases above.

## Things this guide knows are rough

- Every command is unrun; first-run fixes belong in this file and in `infra/`.
- The web service reaches the API at `https://api.pglive.in`, i.e. back through nginx on the VM, so login only
  works once DNS and the certificate are in place (section 11).
- Unverified until the first real run: that Cloud Run passes nginx's `X-Forwarded-Host` through unchanged (the BFF
  rejects logins with 403 "Cross-origin request blocked" if it doesn't — the fix would be in nginx, not the app).
