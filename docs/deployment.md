# Deployment — GCP production (pglive.in)

Owner decisions 2026-10-20: Google Cloud Platform, region **asia-south1**; Cloud Run for Next.js and Django;
Cloud SQL PostgreSQL 16; one small Compute Engine VM for Celery worker, a single Celery beat and Redis; storage
moved from AWS S3 to **Google Cloud Storage**. Frontend contract: [frontend-plan.md](frontend-plan.md).

Status: the application changes (Phase 1 of the plan) are built and tested locally. The `infra/` scripts and
GitHub workflows are written but **have not been run against a real GCP project yet** — treat the first run in
`pglive-staging` as their test.

## 1. Architecture

Owner decision 2026-10-21: **no load balancer, no Cloud DNS.** GoDaddy points straight at the worker VM, where
nginx + Let's Encrypt is the edge ([infra/edge/](../infra/edge/)); Cloud Run ingress is `internal`, which admits
that VM (same project network) and nothing on the internet. The load-balancer design (`infra/40-edge.sh`) is kept for
the scale path. Trade-offs accepted: the VM is a single point of failure for the site; no Cloud Armor (nginx
rate-limits login); `/admin/` is an nginx IP allowlist + Django password, not IAP + Google 2-Step Verification
(`IAP_REQUIRED=False`). Step-by-step: [deployment-manual.md](deployment-manual.md).

```
GoDaddy DNS: A @, www, api → the worker VM's static IP
nginx on the worker VM (Let's Encrypt cert for all three names)
  every request: X-PGLive-Client-IP: $remote_addr   (overwrites a client-sent value)
                 Strict-Transport-Security          (the only place HSTS is set)
                 Host = the run.app name (Cloud Run routes on it), X-Forwarded-Host = the public name
  pglive.in                → 301 → https://www.pglive.in
  www.pglive.in            → Cloud Run pglive-web   (Next.js standalone, BFF)
  api.pglive.in            → Cloud Run pglive-api   (gunicorn, Django/DRF)
  api.pglive.in/admin/*,
  api.pglive.in/api/schema|docs/* → same, only from /etc/nginx/pglive-admin-allow.conf
  /api/auth/*, /api/v1/auth/* rate-limited (api.pglive.in splits direct clients vs the BFF — §3a)
pglive-web → https://api.pglive.in (BFF; signed X-PGLive-Origin-*)      Razorpay webhook → api.pglive.in
pglive-api → Cloud SQL (/cloudsql socket)                                pglive-api → worker VM :6379 (Direct VPC egress)
Worker VM (e2-small, IAP-only SSH): nginx edge · redis · celery worker · celery beat (exactly one) · cloud-sql-proxy
Cloud Run Jobs (fixed commands): pglive-migrate · pglive-check-roles · pglive-bootstrap · pglive-generate-invoices ·
  pglive-check-grace-periods · pglive-smoke · pglive-export-verify
GCS: pglive-prod-media (private) · pglive-prod-backups (asia-south2)
```

One backend image (`backend/Dockerfile.prod`) serves the API, worker, beat and every job; one frontend image
(`frontend/Dockerfile.prod`) per environment, because `NEXT_PUBLIC_*` values are inlined at build time.

## 2. What the code now does (and the tests that prove it)

| Concern | Where | Tests |
|---|---|---|
| Trusted client IP, signed BFF origin | `apps/core/net.py`, `ClientIPMiddleware`, `apps/core/throttles.py`, `frontend/src/lib/server/originSignature.ts` | `core/test_net.py`, `originSignature.test.ts`, `ci/integration/run.sh` |
| Health probes | `apps/core/health.py` → `/health/`, `/health/ready/`; `frontend/src/app/api/health` | `core/test_deployment.py` |
| IAP check on `/admin/` | `apps/core/iap.py` | `core/test_deployment.py` |
| GCS signed URLs (5 min) | `apps/core/storage.py`, `settings/base.py` | `core/test_deployment.py` (`X-Goog-Expires=300`) |
| DB role check | `manage.py check_db_roles` | run in CI and in the migrate job |
| Bootstrap | `manage.py bootstrap_platform` | `core/test_deployment.py` |
| Redis fails open | `apps/core/cache.py`, `apps/core/tasks.py`, `settings/prod.py` | `core/test_deployment.py` |
| JSON logs with PII scrubbing | `apps/core/log_format.py` | `core/test_deployment.py` |
| CSP + nonce on every document | `frontend/src/proxy.ts`, `lib/csp.ts` | `src/__tests__/proxy.test.ts`, `ci/integration/run.sh` |
| Telugu PDF fonts | `backend/Dockerfile.prod` | `billing/tests/test_receipt_pdf_fonts.py` (`REQUIRE_PDF_FONTS=1`) |

## 3. Client IP

`X-Forwarded-For` is never trusted (Google's LB keeps what the client sent and appends to it).

1. The LB sets `X-PGLive-Client-IP` on **all three** backend services. Django reads it when `CLIENT_IP_HEADER`
   is set (prod default), otherwise `REMOTE_ADDR` (dev).
2. Browser traffic reaches Django through the BFF, so Django's LB sees the BFF. The BFF forwards the browser's
   address as `X-PGLive-Origin-IP`, `-Ts`, `-Sig`.
3. Canonical string (UTF-8): `v1\n{ip}\n{ts}\n{METHOD}\n{path}\n{query}`
   - `ip`: IPv4 dotted quad; IPv6 RFC 5952 (compressed, lowercase); IPv4-mapped IPv6 → IPv4.
   - `ts`: integer Unix seconds, base 10. Allowed skew ±60 s.
   - `METHOD`: upper case. `path`: **raw, still percent-encoded** request path; trailing slash preserved.
   - `query`: raw query string without `?`, not re-sorted; empty if none.
   - `sig`: lower-case hex HMAC-SHA256 with `BFF_ORIGIN_SECRET`; compared in constant time.
4. Django takes the raw path from gunicorn's `RAW_URI` (WSGI `PATH_INFO` is already decoded and must not be
   used). Origin headers that don't verify → `400 INVALID_ORIGIN_SIGNATURE`; there is no silent fallback.
   `/health/ready/` reports 503 unless `RAW_URI` is present, so a non-gunicorn server never goes live.
5. Rotation: bump the `v1` prefix and accept both for one rollout.

Vectors shared by both test suites: `backend/apps/core/tests_fixtures/origin_signature_vectors.json`.

## 3a. Edge rate limiting (`infra/edge/limits.conf`)

`api.pglive.in/api/v1/auth/` sees two kinds of caller, and a single per-peer-IP limit fits only one of them:
every browser request arrives through the BFF (Next.js on Cloud Run), so its peer address is Cloud Run's own
egress IP, shared by every user — a per-peer limit there would throttle the whole site together. Direct
clients (future mobile apps, scripts) are exactly what a peer-IP limit is for.

- The web service sends `X-PGLive-Edge-Key` (the `BFF_EDGE_KEY` secret) on every call to the API. nginx checks
  it against `/etc/nginx/pglive-edge-key.map` (exact match only) and strips the header before proxying —
  Django never sees it.
- A request with a **verified** key is limited per **browser** IP (`X-PGLive-Origin-IP`, zone
  `pglive_auth_bff`, 600 r/min — refresh and `/auth/me/` ride this path). Anything else — no key, a wrong key,
  or a forged key with spoofed origin headers — is limited per **peer** IP (zone `pglive_auth_direct`,
  60 r/min), same as `www.pglive.in/api/auth/`. Spoofing the signature or origin-IP headers cannot move a
  request into the generous zone; only the exact edge key does, and Django independently verifies the signed
  origin on every request regardless of which zone counted it.
- Rotation: add a new `BFF_EDGE_KEY` secret version, run `setup-edge.sh` with the new value as `BFF_EDGE_KEY`
  and the old one as `BFF_EDGE_KEY_PREVIOUS` (both are accepted), redeploy `pglive-web`, then run it once more
  without the previous key.
- Test locally: `infra/edge/test-limits.sh` (needs Docker; builds the real `limits.conf` into a throwaway
  nginx and bursts requests through each path).
- The schema/docs routes (`/api/schema/`, `/api/docs/`) share the `/admin/` IP allowlist; Django itself also
  requires an admin session for them (`prod.py`, `SPECTACULAR_SETTINGS`).

## 4. Database roles

Two roles, created by `infra/sql/roles-1-roles.sql` (not with `gcloud sql users create`, which would add them to
`cloudsqlsuperuser`):

- `migration_user` owns the database, schema `public` and every table/sequence. Used **only** by `pglive-migrate`.
- `app_user` is the runtime role: `SELECT/INSERT/UPDATE/DELETE` and sequence `USAGE` only, via
  `ALTER DEFAULT PRIVILEGES FOR ROLE migration_user` so future migrations grant automatically. It owns nothing, cannot
  `CREATE` in `public`, is `NOSUPERUSER NOBYPASSRLS`, and is a member of no other role.

`manage.py check_db_roles --role app_user` fails the deploy if any of that stops being true, or if a table with a
`tenant_id` column lacks *forced* RLS. Documented exceptions (`RLS_EXEMPT_TABLES`): `users` (module 01) and
`subscriptions` and `razorpay_webhook_events` (module 13).

Order on a fresh instance: `roles-1-roles.sql` → `pglive-migrate` (as `migration_user`) → `roles-2-grants.sql` →
`check_db_roles`. Part 2 is idempotent and is re-run after every restore. Local development still uses the single
`app_user` from `docker/postgres/init.sql` (it owns its tables there); only CI and the integration test exercise the
split. Never connect the app as `postgres`/`cloudsqlsuperuser`.

RLS uses session-level `set_config`, so **never put a transaction-mode pooler in front of this database**.

## 5. Bootstrap (first deploy only)

1. Create secret `INITIAL_SUPERADMIN_PASSWORD` (strong; the command validates it).
2. Run `pglive-bootstrap` (`manage.py bootstrap_platform`): seeds app-version policies, creates the Super Admin if
   none exists (audited as `platform.superadmin_bootstrapped`), never prints the password, and never resets an
   existing admin.
3. Verify the Super Admin can log in; change the password in-app.
4. Verify IAP-protected `/admin/` works for a member of `pglive-admins@`.
5. **Only then** destroy the secret version, delete the secret, and delete the `pglive-bootstrap` job.

Admin MFA is **IAP + enforced Google 2-Step Verification** for `pglive-admins@`. Django admin has no MFA of its
own and `apps/accounts/otp.py` is phone-code login, not TOTP.

Then, in Super Admin: PlatformConfig (trial days, grace days, caps — invariant 10) and the live Plans. Never run
`seed_data` in production.

## 6. Releases

- Production deploys come from annotated tags `vX.Y.Z` whose commit is reachable from `main`
  (`deploy-prod.yml` checks `git merge-base --is-ancestor`). A GitHub ruleset restricts who can create `v*` tags and
  forbids moving or deleting them; the `production` Environment accepts only `v*` tags and needs a reviewer.
- Pipeline: build → on-demand Cloud SQL backup (wait for success) → `pglive-migrate` → candidate revision with
  `--no-traffic --tag candidate` → `pglive-smoke` (in-VPC) → 10 % → watch → 100 % → web → worker VM.
- **Start-up deploy check.** The API image starts through `backend/bin/start-api.sh`, which runs
  `manage.py check --deploy --fail-level ERROR` before gunicorn. A revision with blank, malformed or placeholder
  Razorpay keys (`apps/subscriptions/checks.py`), an `http`/default `FRONTEND_BASE_URL` (`apps/core/checks.py`) or
  unsigned webhooks allowed never becomes ready, so the deploy aborts before any traffic moves. Production
  settings also forbid the Razorpay stub client. Jobs and the Celery worker override the command and are not
  affected. CI runs the same check with production settings and placeholder keys that are valid in shape but not
  functional (no live secret is used in CI).
- `sa-deployer` (created by `infra/10-foundation.sh`) holds exactly what the pipeline does: Artifact Registry
  writer, Cloud Run admin (it sets job IAM), Secret Manager viewer (lists versions only), Cloud Scheduler admin,
  Workflows editor, Logging viewer, and compute viewer + IAP tunnel + OS Admin Login for the worker SSH. It has no
  project IAM admin. The **Workload Identity Federation** pool/provider that `WIF_PROVIDER` names is not scripted
  in `infra/`: create a pool and a GitHub OIDC provider restricted to this repository, allow the pool principal
  to impersonate `sa-deployer` (`roles/iam.workloadIdentityUser`), and store the provider name and the deployer's
  email as the `WIF_PROVIDER` / `DEPLOYER_SERVICE_ACCOUNT` Environment variables.
- Staging: `deploy-staging.yml` is manual-only (the owner launches without a staging environment, and
  `30-services.sh` still hard-codes the production API host for both environments).
- Releases are labelled: `APP_RELEASE` (git sha) and `SENTRY_ENVIRONMENT` (`production`/`staging`) are set on the
  API, the jobs and the worker, so errors carry the right environment and release.
- Migrations are expand/contract so the previous revision keeps working; rollback is a traffic shift, never a
  database downgrade.
- Rollback: `gcloud run services update-traffic SERVICE --to-revisions=PREVIOUS=100`; worker VM:
  `deploy.sh PREVIOUS_TAG`.

## 7. Operations cheat sheet

| Task | How |
|---|---|
| Rotate `DJANGO_SECRET_KEY` | new key, old one into `SECRET_KEY_FALLBACKS`, redeploy; JWTs unaffected |
| Rotate `JWT_SIGNING_KEY` | forces everyone to log in again — do off-hours and announce |
| Rotate DB password | `infra/rotate-db-password.sh` (short coordinated restart; not zero-downtime) |
| Rotate Razorpay webhook secret | new secret in dashboard + Secret Manager together, low traffic, replay failed deliveries |
| CSP to enforcing / back | `CSP_MODE=enforce` / `report-only` + new revision of `pglive-web` |
| HSTS ramp | LB response header 300 s → 1 d → 1 wk → 1 y; `includeSubDomains` only at the end; verify apex, www, api each time |
| Operator one-off command | IAP SSH to the worker VM, `docker compose run --rm worker python manage.py …`, with a ticket |

Smoke-test account: user `smoke@pglive.in` in a dedicated `PGLive Smoke Test` tenant with the least-privileged
staff role that exists (no mutations, billing or uploads); if no truly read-only combination exists, smoke checks
stay on GET endpoints. Credentials in `SMOKE_USER_CREDENTIALS`, rotated quarterly and on staff changes.

## 8. Recovery

| Scenario | Response | Target |
|---|---|---|
| Bad deploy | shift traffic back; `deploy.sh PREVIOUS` on the VM | < 5 min |
| Bad migration / corruption | PITR clone to a **new** instance → `check_db_roles` → switch the connection name in `pglive-api`, every job, the VM proxy, the export Workflow, monitoring and `infra/`; keep the old instance stopped 14 days | RPO ≤ 5 min, RTO 1–2 h |
| File deleted | GCS versioning / soft delete | < 1 h |
| Zone / region loss | restore from backup / weekly export in asia-south2 | hours / ~1 day |
| VM lost | recreate, `deploy.sh` (Redis is disposable) | < 30 min |

Restore drills run **only** in the isolated `pglive-dr-test` project (the export holds real resident, Aadhaar/PAN and
payment data), never in staging: `infra/dr/restore-drill.sh`. A logical export carries no roles, so the drill
re-applies `roles-1-roles.sql` and `roles-2-grants.sql` around the import, then runs `check_db_roles` and the RLS
tests, and deletes the instance.

## 9. Launch gates and open items

- **Aadhaar/PAN legal review** (lawful basis, consent text, purpose limitation, retention): until signed off,
  ship with those uploads disabled. This is the `KYC_UPLOADS_ENABLED` setting, which defaults to **off in
  production**: new Aadhaar/PAN files are refused (stored ones stay readable and can be cleared) until
  `KYC_UPLOADS_ENABLED=true` is set on the API service.
- **Razorpay live activation** (KYC, Subscriptions enabled) and **billing upgraded to a paid account before launch**.
- **Stale webhook ordering** is an open decision — see [modules/13-subscription.md](modules/13-subscription.md).
- Cost estimate must be an exported Pricing Calculator file before choosing the launch tier (the lean option leaves
  essentially no margin inside a $300 / 90-day trial).
- Backup-bucket retention stays **unlocked** until export → restore → lifecycle behaviour is proven; locking is
  irreversible.

### Frontend lint baseline

`npm run lint` failed on 13 findings that predate the deployment work, which would have failed the CI/deploy
workflows on their first run. They are recorded in `frontend/eslint-suppressions.json` (ESLint bulk suppressions)
instead of being silenced in the rules: **existing findings are tolerated, any new one fails the build**, and fixing
one makes ESLint ask you to prune the file (`npx eslint --prune-suppressions src next.config.ts`).

Known debt it holds, owned by the feature authors, not part of this work:
- `PropertyMapPicker.tsx`: 8 hard-coded UI strings (titles, placeholders, hints — **invariant 7**, i18n), 3
  `setState`-in-effect, 1 `any`;
- `VacanciesScreen.tsx`: 1 hard-coded string (`back="/dashboard"`).

The i18n ones are product-language gaps (Telugu users see English there) — fix before the Telugu launch, then prune.
