"""Trusted client IP (invariant 9: audit logs record the caller's IP).

`X-Forwarded-For` is never trusted: Google's load balancer keeps whatever the
client sent and appends to it. Instead:

1. The load balancer sets `X-PGLive-Client-IP: {client_ip_address}` on every
   backend service, overwriting any client-supplied value. Django trusts that
   header only when `CLIENT_IP_HEADER` names it (prod); otherwise REMOTE_ADDR.
2. Browser traffic reaches Django through the Next BFF, so the load balancer in
   front of Django sees the BFF, not the browser. The BFF forwards the browser's
   address as `X-PGLive-Origin-IP` with an HMAC signature
   (`BFF_ORIGIN_SECRET`) over a canonical string — see `canonical_string()`
   and frontend/src/lib/server/originSignature.ts, which must stay identical
   (shared vectors: backend/apps/core/fixtures/origin-sig-vectors.json).

A request that carries origin headers which do not verify is rejected by
`ClientIPMiddleware` (fail closed) rather than silently attributed to the BFF.
"""
import hashlib
import hmac
import ipaddress
import logging
import time

from django.conf import settings

logger = logging.getLogger(__name__)

SIGNATURE_VERSION = 'v1'
ORIGIN_IP_META = 'HTTP_X_PGLIVE_ORIGIN_IP'
ORIGIN_TS_META = 'HTTP_X_PGLIVE_ORIGIN_TS'
ORIGIN_SIG_META = 'HTTP_X_PGLIVE_ORIGIN_SIG'
ORIGIN_META = (ORIGIN_IP_META, ORIGIN_TS_META, ORIGIN_SIG_META)
MAX_SKEW_SECONDS = 60

_CACHE_ATTR = '_pglive_client_ip'


class OriginSignatureError(Exception):
    """Origin headers were sent but cannot be trusted. `reason` is for logs only."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def normalize_ip(value):
    """Canonical text form, or None: IPv4 dotted quad, IPv6 RFC 5952
    (compressed, lowercase), IPv4-mapped IPv6 collapsed to IPv4."""
    try:
        ip = ipaddress.ip_address((value or '').strip())
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return str(ip)


def canonical_string(ip, ts, method, path, query):
    """`path` and `query` are raw (still percent-encoded) exactly as sent upstream;
    `query` has no leading '?' and is not re-sorted."""
    return f'{SIGNATURE_VERSION}\n{ip}\n{ts}\n{method.upper()}\n{path}\n{query}'


def sign(secret, ip, ts, method, path, query):
    message = canonical_string(ip, ts, method, path, query)
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def raw_path_and_query(request):
    """(path, query) from the server's raw request target, or None. Gunicorn exposes
    it as RAW_URI; WSGI PATH_INFO is already percent-decoded, so it can't be used."""
    raw = request.META.get('RAW_URI')
    if raw is None:
        return None
    path, _, query = raw.partition('?')
    return path, query


def has_origin_headers(request):
    return any(request.META.get(name) for name in ORIGIN_META)


def verify_origin(request, now=None):
    """Return the signed browser IP, or raise OriginSignatureError."""
    secret = getattr(settings, 'BFF_ORIGIN_SECRET', '')
    if not secret:
        raise OriginSignatureError('no BFF_ORIGIN_SECRET configured')
    raw_ip = request.META.get(ORIGIN_IP_META, '')
    ts = request.META.get(ORIGIN_TS_META, '')
    sig = request.META.get(ORIGIN_SIG_META, '')
    if not (raw_ip and ts and sig):
        raise OriginSignatureError('incomplete origin headers')
    ip = normalize_ip(raw_ip)
    if ip is None or ip != raw_ip:
        raise OriginSignatureError('origin IP not in canonical form')
    if not ts.isdigit():
        raise OriginSignatureError('malformed timestamp')
    now = int(time.time()) if now is None else now
    if abs(now - int(ts)) > MAX_SKEW_SECONDS:
        raise OriginSignatureError('timestamp outside the allowed window')
    target = raw_path_and_query(request)
    if target is None:
        raise OriginSignatureError('raw request URI unavailable (server is not gunicorn?)')
    expected = sign(secret, ip, ts, request.method, *target)
    if not hmac.compare_digest(expected, sig.lower()):
        raise OriginSignatureError('signature mismatch')
    return ip


def _edge_ip(request):
    header = getattr(settings, 'CLIENT_IP_HEADER', '')
    if header:
        meta_key = 'HTTP_' + header.upper().replace('-', '_')
        ip = normalize_ip(request.META.get(meta_key))
        if ip:
            return ip
    return normalize_ip(request.META.get('REMOTE_ADDR'))


def get_client_ip(request):
    """The caller's IP, or None. Unwraps DRF requests; cached per request.
    `ClientIPMiddleware` has already rejected requests whose origin headers
    don't verify, so a verified origin IP is set before views run."""
    if request is None:
        return None
    request = getattr(request, '_request', request)
    cached = getattr(request, _CACHE_ATTR, None)
    if cached is not None:
        return cached or None
    ip = _edge_ip(request)
    setattr(request, _CACHE_ATTR, ip or '')
    return ip


def set_client_ip(request, ip):
    setattr(request, _CACHE_ATTR, ip or '')
