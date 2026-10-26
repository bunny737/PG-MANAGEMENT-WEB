#!/usr/bin/env bash
# Proves the edge keeps the API host out of search engines: api.pglive.in answers every request (even an nginx
# error page) with X-Robots-Tag: noindex, nofollow, and www.pglive.in does not (it is the indexed website).
# Renders the real pglive.conf.template in the nginx version the worker VM runs (1.22).
#   infra/edge/test-robots-header.sh          (needs docker and network for one apk package; ~15 s)
set -euo pipefail
export MSYS2_ARG_CONV_EXCL='*'    # Git Bash on Windows: pass container:path arguments through untouched
hp() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else echo "$1"; fi; }   # host path as docker.exe wants it
HERE="$(cd "$(dirname "$0")" && pwd)"
IMAGE="${NGINX_IMAGE:-nginx:1.22-alpine}"
NAME="pglive-edge-robots-test-$$"
PORT="${TEST_PORT:-18443}"
WORK="$(mktemp -d)"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT

mkdir -p "$WORK/snippets"

# Same snippets setup-edge.sh writes (TLS paths point at the throwaway certificate).
cat > "$WORK/snippets/pglive-tls.conf" <<'EOF'
ssl_certificate     /etc/letsencrypt/live/pglive.in/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/pglive.in/privkey.pem;
ssl_protocols TLSv1.2 TLSv1.3;
add_header Strict-Transport-Security "max-age=300" always;
EOF
# Upstream is a closed local port, so every proxied request is an nginx-generated 502: the header must
# still be there ("always"), and that is the case that matters for error bodies.
cat > "$WORK/snippets/pglive-proxy.conf" <<'EOF'
proxy_pass https://$upstream_host;
proxy_ssl_server_name on;
proxy_set_header Host $upstream_host;
proxy_connect_timeout 2s;
EOF
printf '"testkey" 1;\n' > "$WORK/edge-key.map"
printf 'allow all;\n' > "$WORK/admin-allow.conf"

# nginx 1.22: `envsubst` is in the image; the resolver line is harmless with IP-literal upstreams.
API_HOST="127.0.0.1:9" WEB_HOST="127.0.0.1:9" envsubst '${API_HOST} ${WEB_HOST}' \
  < "$HERE/pglive.conf.template" > "$WORK/pglive.conf" 2>/dev/null \
  || sed -e 's|\${API_HOST}|127.0.0.1:9|g' -e 's|\${WEB_HOST}|127.0.0.1:9|g' "$HERE/pglive.conf.template" > "$WORK/pglive.conf"

# nginx image has no openssl: the container makes the throwaway certificate itself, then runs nginx.
docker create --name "$NAME" -p "$PORT:443" --entrypoint sh "$IMAGE" -c '
  apk add --no-cache openssl >/dev/null 2>&1 &&
  mkdir -p /etc/letsencrypt/live/pglive.in &&
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=pglive.in" \
    -keyout /etc/letsencrypt/live/pglive.in/privkey.pem -out /etc/letsencrypt/live/pglive.in/fullchain.pem 2>/dev/null &&
  exec nginx -g "daemon off;"' >/dev/null
docker cp "$(hp "$WORK/pglive.conf")" "$NAME:/etc/nginx/conf.d/pglive.conf"
docker cp "$(hp "$HERE/limits.conf")" "$NAME:/etc/nginx/conf.d/00-pglive-limits.conf"
docker cp "$(hp "$WORK/snippets")" "$NAME:/etc/nginx/"
docker cp "$(hp "$WORK/edge-key.map")" "$NAME:/etc/nginx/pglive-edge-key.map"
docker cp "$(hp "$WORK/admin-allow.conf")" "$NAME:/etc/nginx/pglive-admin-allow.conf"
docker start "$NAME" >/dev/null
for _ in $(seq 1 60); do
  curl -skI --resolve "api.pglive.in:$PORT:127.0.0.1" "https://api.pglive.in:$PORT/" >/dev/null && break
  sleep 0.5
done

if ! curl -skI --resolve "api.pglive.in:$PORT:127.0.0.1" "https://api.pglive.in:$PORT/" >/dev/null; then
  echo "FAIL nginx did not come up:"; docker logs "$NAME" 2>&1 | tail -20; exit 1
fi
failures=0
headers() { curl -skI --resolve "$1:$PORT:127.0.0.1" "https://$1:$PORT$2"; }
for path in / /health/ /api/v1/auth/login/ /admin/ /api/schema/ /does-not-exist; do
  if headers api.pglive.in "$path" | grep -qi '^x-robots-tag: noindex, nofollow'; then
    echo "ok   api.pglive.in$path sends X-Robots-Tag"
  else
    echo "FAIL api.pglive.in$path has no X-Robots-Tag"; failures=$((failures + 1))
  fi
done
if headers www.pglive.in / | grep -qi '^x-robots-tag'; then
  echo "FAIL www.pglive.in must not send X-Robots-Tag (it is the indexed site)"; failures=$((failures + 1))
else
  echo "ok   www.pglive.in sends no X-Robots-Tag"
fi
if headers api.pglive.in / | grep -qi '^strict-transport-security'; then
  echo "ok   HSTS still present next to X-Robots-Tag"
else
  echo "FAIL HSTS missing on api.pglive.in"; failures=$((failures + 1))
fi
exit "$failures"
