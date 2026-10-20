#!/usr/bin/env bash
# Creates the worker VM (once):  infra/worker/create-vm.sh prod|staging
# No inbound access except IAP SSH and Redis from the Cloud Run subnet (firewall rules from 10-foundation.sh,
# tag "worker"). It has an ephemeral external IP only so it can reach Razorpay, FCM and SMTP without Cloud NAT.
# STATUS: not yet run against a real project (see ../env.sh).
set -euo pipefail
source "$(dirname "$0")/../env.sh" "$1"
g() { gcloud --project "$PROJECT" "$@"; }

g compute instances describe "$WORKER_VM" --zone "${REGION}-a" >/dev/null 2>&1 && { echo "$WORKER_VM exists"; exit 0; }
g compute instances create "$WORKER_VM" --zone "${REGION}-a" --machine-type "${WORKER_MACHINE:-e2-small}" \
  --network "$NETWORK" --subnet "$SUBNET" --private-network-ip "$WORKER_IP" --tags worker \
  --service-account "$(sa sa-worker)" --scopes cloud-platform \
  --image-family debian-12 --image-project debian-cloud --boot-disk-size 20GB --boot-disk-type pd-balanced \
  --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
  --metadata "region=$REGION,sql-connection=$SQL_CONNECTION,enable-oslogin=TRUE" \
  --metadata-from-file startup-script=<(cat <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
[ -f /opt/pglive/.provisioned ] && exit 0
apt-get update
apt-get install -y ca-certificates curl gnupg docker.io docker-compose-plugin
curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh && bash add-google-cloud-ops-agent-repo.sh --also-install
systemctl enable --now docker
mkdir -p /opt/pglive && touch /opt/pglive/.provisioned
SCRIPT
)
echo "Created. Copy infra/worker/{docker-compose.yml,deploy.sh} to /opt/pglive (gcloud compute scp --tunnel-through-iap), then:"
echo "  sudo /opt/pglive/deploy.sh <image-tag>"
