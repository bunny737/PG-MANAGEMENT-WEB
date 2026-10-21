#!/usr/bin/env bash
# On the pglive-worker VM:  sudo API_HOST=... WEB_HOST=... LE_EMAIL=... [HSTS_MAX_AGE=300] /opt/pglive/edge/setup-edge.sh
# Installs nginx + certbot, gets one Let's Encrypt certificate for pglive.in, www and api (HTTP-01, so the GoDaddy
# A records must already point at this VM), and renders the edge config. Re-run it to change hosts or HSTS.
# API_HOST / WEB_HOST: the Cloud Run hostnames, e.g. pglive-api-<project-number>.asia-south1.run.app.
# STATUS: not yet run on a real VM (see infra/env.sh).
set -euo pipefail
: "${API_HOST:?}" "${WEB_HOST:?}" "${LE_EMAIL:?}"
HSTS_MAX_AGE="${HSTS_MAX_AGE:-300}"   # ramp: 300 -> 86400 -> 604800 -> 31536000 (re-run to change)
HERE="$(cd "$(dirname "$0")" && pwd)"
DOMAINS=(-d pglive.in -d www.pglive.in -d api.pglive.in)

if ! command -v nginx >/dev/null || ! command -v certbot >/dev/null; then
  apt-get update
  apt-get install -y nginx certbot gettext-base
fi
rm -f /etc/nginx/sites-enabled/default
mkdir -p /var/www/certbot /etc/nginx/snippets

# The admin allowlist is kept across re-runs; it starts closed.
if [[ ! -f /etc/nginx/pglive-admin-allow.conf ]]; then
  printf '# allow 203.0.113.10;   # one line per address allowed to reach /admin/\ndeny all;\n' \
    > /etc/nginx/pglive-admin-allow.conf
fi

cat > /etc/nginx/snippets/pglive-tls.conf <<EOF
ssl_certificate     /etc/letsencrypt/live/pglive.in/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/pglive.in/privkey.pem;
ssl_protocols TLSv1.2 TLSv1.3;
ssl_session_cache shared:pglive_tls:10m;
add_header Strict-Transport-Security "max-age=$HSTS_MAX_AGE" always;
EOF

cat > /etc/nginx/snippets/pglive-proxy.conf <<'EOF'
proxy_pass https://$upstream_host;          # no URI part: the original request URI goes through byte for byte
proxy_http_version 1.1;
proxy_ssl_server_name on;
proxy_ssl_name $upstream_host;
proxy_set_header Host $upstream_host;       # Cloud Run routes on Host
proxy_set_header X-Forwarded-Host $host;
proxy_set_header X-Forwarded-Proto https;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-PGLive-Client-IP $remote_addr;   # overwrites anything the client sent
proxy_set_header Connection "";
proxy_connect_timeout 10s;
proxy_read_timeout 70s;                     # Cloud Run request timeout is 60 s
proxy_send_timeout 70s;
client_max_body_size 25m;
EOF

if [[ ! -f /etc/letsencrypt/live/pglive.in/fullchain.pem ]]; then
  # Port-80-only config first: the full config refers to the certificate that doesn't exist yet.
  cat > /etc/nginx/conf.d/pglive.conf <<'EOF'
server {
    listen 80 default_server;
    server_name _;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 404; }
}
EOF
  nginx -t && systemctl reload nginx
  certbot certonly --webroot -w /var/www/certbot "${DOMAINS[@]}" --cert-name pglive.in \
    --email "$LE_EMAIL" --agree-tos --non-interactive
fi
# Renewals (certbot's systemd timer) reload nginx so the new certificate is used.
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
printf '#!/bin/sh\nsystemctl reload nginx\n' > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

# shellcheck disable=SC2016  # envsubst takes the variable NAMES, literally; only these two are replaced
API_HOST="$API_HOST" WEB_HOST="$WEB_HOST" envsubst '${API_HOST} ${WEB_HOST}' \
  < "$HERE/pglive.conf.template" > /etc/nginx/conf.d/pglive.conf
nginx -t
systemctl reload nginx
echo "Edge ready. Check: curl -sI https://www.pglive.in ; curl -s https://api.pglive.in/health/ready/"
