#!/usr/bin/env bash
# Creates the worker VM (once):  infra/worker/create-vm.sh prod|staging
# The VM runs Redis, the Celery worker, exactly one beat, and (owner decision 2026-10-21: no load balancer) the
# nginx edge for pglive.in (infra/edge/). Inbound: IAP SSH, Redis from the subnet, and 80/443 from anywhere
# (tag "edge"). It gets a reserved static external IP, which the GoDaddy A records point at.
# STATUS: not yet run against a real project (see ../env.sh).
set -euo pipefail
source "$(dirname "$0")/../env.sh" "$1"
g() { gcloud --project "$PROJECT" "$@"; }

g compute addresses describe pglive-edge-ip --region "$REGION" >/dev/null 2>&1 || \
  g compute addresses create pglive-edge-ip --region "$REGION"
EDGE_IP="$(g compute addresses describe pglive-edge-ip --region "$REGION" --format='value(address)')"
g compute firewall-rules describe pglive-allow-web >/dev/null 2>&1 || \
  g compute firewall-rules create pglive-allow-web --network "$NETWORK" --direction INGRESS \
    --allow tcp:80,tcp:443 --source-ranges 0.0.0.0/0 --target-tags edge

g compute instances describe "$WORKER_VM" --zone "${REGION}-a" >/dev/null 2>&1 && { echo "$WORKER_VM exists"; exit 0; }
g compute instances create "$WORKER_VM" --zone "${REGION}-a" --machine-type "${WORKER_MACHINE:-e2-small}" \
  --network "$NETWORK" --subnet "$SUBNET" --private-network-ip "$WORKER_IP" --address "$EDGE_IP" --tags worker,edge \
  --service-account "$(sa sa-worker)" --scopes cloud-platform \
  --image-family debian-12 --image-project debian-cloud --boot-disk-size 20GB --boot-disk-type pd-balanced \
  --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
  --metadata "region=$REGION,sql-connection=$SQL_CONNECTION,enable-oslogin=TRUE" \
  --metadata-from-file startup-script=<(cat <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
[ -f /opt/pglive/.provisioned ] && exit 0
apt-get update
install -m 0755 -d /etc/apt/keyrings; curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc; echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list; apt-get update; apt-get install -y ca-certificates curl docker-ce docker-ce-cli containerd.io docker-compose-plugin nginx certbot gettext-base unattended-upgrades
curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh && bash add-google-cloud-ops-agent-repo.sh --also-install
systemctl enable --now docker
mkdir -p /opt/pglive && touch /opt/pglive/.provisioned
SCRIPT
)
echo "Created with external IP $EDGE_IP. Point GoDaddy A records @, www, api at it."
echo "Copy infra/worker/{docker-compose.yml,deploy.sh} and infra/edge/ to /opt/pglive (gcloud compute scp --tunnel-through-iap), then:"
echo "  sudo /opt/pglive/deploy.sh <image-tag>"
echo "  sudo API_HOST=... WEB_HOST=... LE_EMAIL=... /opt/pglive/edge/setup-edge.sh   (after DNS points here)"
