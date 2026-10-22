#!/usr/bin/env bash
# Proves the rate-limit routing in limits.conf with a real nginx (the version on the worker VM, 1.22):
# which counter a request lands in depends on a VERIFIED edge key, never on headers a caller can forge.
#   infra/edge/test-limits.sh          (needs docker; ~20 s)
# Also checks that the full edge template and the key map are syntactically valid (nginx -t).
set -euo pipefail
export MSYS_NO_PATHCONV=1
HERE="$(cd "$(dirname "$0")" && pwd)"
IMAGE="${NGINX_IMAGE:-nginx:1.22-alpine}"
NAME="pglive-edge-limits-test-$$"
PORT="${TEST_PORT:-18399}"
KEY="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"    # 48 hex chars
failures=0
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; rm -rf "$WORK"; }
WORK="$(mktemp -d)"; trap cleanup EXIT

mkdir -p "$WORK/html/api/v1/auth"
echo ok > "$WORK/html/api/v1/auth/login"
cat > "$WORK/server.conf" <<'EOF'
server {
    listen 80 default_server;
    server_name _;
    root /srv/pglive-test;
    # Same limit_req lines as the api.pglive.in auth location in pglive.conf.template. A static file, not
    # `return`, stands in for proxy_pass: `return` is a rewrite-phase directive and finalizes the request
    # before limit_req's preaccess-phase check ever runs, which would make this test pass for the wrong reason.
    location /api/v1/auth/ {
        limit_req zone=pglive_auth_direct burst=20 nodelay;
        limit_req zone=pglive_auth_bff burst=100 nodelay;
    }
}
EOF
: > "$WORK/blank.conf"   # overwrites the image's conf.d/default.conf, which would otherwise outrank ours
printf '# test\n"%s" 1;\n' "$KEY" > "$WORK/pglive-edge-key.map"

hostpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else echo "$1"; fi; }   # docker.exe wants Windows paths under Git Bash
start() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker create --name "$NAME" -p "$PORT:80" "$IMAGE" >/dev/null
  docker cp "$(hostpath "$HERE/limits.conf")" "$NAME:/etc/nginx/conf.d/00-pglive-limits.conf"
  docker cp "$(hostpath "$WORK/server.conf")" "$NAME:/etc/nginx/conf.d/zz-server.conf"
  docker cp "$(hostpath "$WORK/pglive-edge-key.map")" "$NAME:/etc/nginx/pglive-edge-key.map"
  docker cp "$(hostpath "$WORK/blank.conf")" "$NAME:/etc/nginx/conf.d/default.conf"
  docker cp "$(hostpath "$WORK/html")" "$NAME:/srv/pglive-test"
  docker start "$NAME" >/dev/null
  for _ in $(seq 1 30); do curl -s -o /dev/null "http://localhost:$PORT/" && break; sleep 0.3; done
}

# Send N requests over one keep-alive connection (curl URL ranges), echo "<200-count> <429-count>".
burst() { # count [curl args...]
  local n=$1; shift
  local out
  out=$(curl -s -o /dev/null -w '%{http_code}\n' "$@" "http://localhost:$PORT/api/v1/auth/login?n=[1-$n]" || true)
  echo "$(grep -c '^200$' <<<"$out" || true) $(grep -c '^429$' <<<"$out" || true)"
}
check() { # name expectation(shell test on $1=ok $2=limited) ok limited
  local name=$1 expr=$2 ok=$3 limited=$4
  if (( $(eval "echo \$(( $expr ))") )); then echo "ok   $name (ok=$ok limited=$limited)"; else echo "FAIL $name (ok=$ok limited=$limited)"; failures=$((failures + 1)); fi
}

echo "--- config syntax"
start
docker exec "$NAME" nginx -t >/dev/null 2>&1 && echo "ok   nginx -t with limits.conf + key map" || { echo "FAIL nginx -t"; docker exec "$NAME" nginx -t || true; failures=$((failures + 1)); }

echo "--- direct clients are limited per peer IP"
start
read -r ok limited < <(burst 45)
check "no key: 45 rapid requests are throttled" "limited >= 15" "$ok" "$limited"

echo "--- forged or wrong headers do not escape the direct limit"
start
read -r ok limited < <(burst 45 -H "X-PGLive-Edge-Key: not-the-key" -H "X-PGLive-Origin-IP: 198.51.100.$((RANDOM % 200 + 1))")
check "wrong edge key + origin IP header: still throttled" "limited >= 15" "$ok" "$limited"
start
read -r ok limited < <(burst 45 -H "X-PGLive-Origin-Sig: deadbeef" -H "X-PGLive-Origin-Ts: 1" -H "X-PGLive-Origin-IP: 203.0.113.9")
check "bogus signature headers without the key: still throttled" "limited >= 15" "$ok" "$limited"
start
read -r ok limited < <(burst 45 -H "X-PGLive-Edge-Key: ${KEY}x")
check "a key with extra characters is not the key" "limited >= 15" "$ok" "$limited"

echo "--- the BFF (valid key) is limited per browser, not per peer"
# Two browsers, each bursting through the BFF: each must get its own allowance (not share one), proving the
# key really is the browser IP and not the shared edge-key/peer address. One curl process per browser
# (burst()'s URL-range, reusing one connection) — a sequential loop of many separate curl processes is
# unreliable under Docker Desktop's Windows networking and was the cause of an earlier flaky result here.
start
read -r ok limited < <(burst 45 -H "X-PGLive-Edge-Key: $KEY" -H "X-PGLive-Origin-IP: 203.0.113.201")
check "browser A's burst through the BFF all pass" "limited == 0" "$ok" "$limited"
read -r ok limited < <(burst 45 -H "X-PGLive-Edge-Key: $KEY" -H "X-PGLive-Origin-IP: 203.0.113.202")
check "browser B gets its own allowance, unaffected by browser A" "limited == 0" "$ok" "$limited"

start
read -r ok limited < <(burst 160 -H "X-PGLive-Edge-Key: $KEY" -H "X-PGLive-Origin-IP: 203.0.113.77")
check "one browser hammering through the BFF is eventually throttled" "limited >= 15 && ok >= 100" "$ok" "$limited"

start
read -r ok limited < <(burst 160 -H "X-PGLive-Edge-Key: $KEY")
check "BFF call without a browser IP falls back to its own address, still bounded" "limited >= 15" "$ok" "$limited"

if (( failures )); then echo "$failures check(s) failed"; exit 1; fi
echo "All edge limit checks passed."
