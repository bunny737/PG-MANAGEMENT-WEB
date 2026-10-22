# infra/

Idempotent `gcloud` scripts for the GCP deployment described in [docs/deployment.md](../docs/deployment.md).

> **Status: written, not yet run.** Everything under `infra/` (and the deploy workflows) was written from the
> plan and checked with `bash -n`, shellcheck and YAML parsing only. The application code they deploy is tested;
> these scripts are not, because no GCP project exists yet. Run them in `pglive-staging` first and expect to fix
> what the first run finds (flag names, IAM propagation delays, the first-deploy ordering below).

## Order

| Step | Script | Notes |
|---|---|---|
| 0 | by hand | create projects, link billing, budgets + alerts, Cloud Identity group `pglive-admins@` with 2-Step Verification enforced |
| 1 | `10-foundation.sh <env>` | APIs, network, Artifact Registry, service accounts and per-secret access, secret shells |
| 2 | add secret values | `gcloud secrets versions add NAME --data-file=-` (`REDIS_URL` / `REDIS_CACHE_URL` are full URLs with the password) |
| 3 | `20-data.sh <env>` | Cloud SQL (backups, PITR, SSL only), database roles, buckets |
| 4 | `worker/create-vm.sh <env>` | the worker VM; then copy `worker/{docker-compose.yml,deploy.sh}` to `/opt/pglive` |
| 5 | `deploy.sh <env> <sha>` | build, push, (prod) backup, services + jobs, migrate, smoke, canary, worker VM |
| 5a | first deploy only | run `30-services.sh` twice (the candidate hostname is derived from the service URL); after the first `migrate`, apply `sql/roles-2-grants.sql` once; run `pglive-bootstrap` per docs/deployment.md |
| 6 | `edge/setup-edge.sh` on the worker VM | nginx + Let's Encrypt edge (owner decision 2026-10-21: no load balancer); prints the GoDaddy DNS records to enter |

`40-edge.sh` (load balancer, Cloud Armor, IAP) is kept for the scale path but is **not used today** — see
docs/deployment.md §1.

`rotate-db-password.sh` and `dr/restore-drill.sh` are operational (docs/deployment.md, sections 7-8).
`sql/roles-1-roles.sql` / `roles-2-grants.sql` define the database role model; CI and
`ci/integration/run.sh` run them against a real Postgres, which is the part of this directory that **is** tested.

Staging is the same scripts with `staging` (smaller tier, no load balancer, Razorpay **test** keys); the isolated
`pglive-dr-test` project is used only by `dr/restore-drill.sh`.
