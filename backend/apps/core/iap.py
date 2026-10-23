"""Identity-Aware Proxy check for Django admin (WP16, docs/deployment.md).

In prod `/admin/*` is routed to a load-balancer backend with IAP enabled, and
IAP plus enforced Google 2-Step Verification is the admin MFA layer (Django
admin has none of its own). Google recommends also verifying IAP's signed
header in the app, so a request that somehow bypasses the IAP backend (e.g.
via the non-admin backend or an internal caller) is still refused.

IAP_AUDIENCE is the backend service's audience:
`/projects/<PROJECT_NUMBER>/global/backendServices/<SERVICE_ID>`.
With IAP_REQUIRED and no audience configured, admin fails closed.
"""
import json
import logging
import threading
import time
import urllib.request

from django.conf import settings
from django.http import HttpResponseForbidden

logger = logging.getLogger('apps.security')

IAP_HEADER = 'HTTP_X_GOOG_IAP_JWT_ASSERTION'
IAP_ISSUER = 'https://cloud.google.com/iap'
IAP_CERTS_URL = 'https://www.gstatic.com/iap/verify/public_key'
CERTS_TTL_SECONDS = 3600
ADMIN_PREFIX = '/admin/'

_certs = {'keys': {}, 'fetched_at': 0.0}
_certs_lock = threading.Lock()


def _fetch_certs():
    with urllib.request.urlopen(IAP_CERTS_URL, timeout=5) as response:
        return json.loads(response.read())


def _certs_for(kid):
    """IAP's ES256 public keys, cached for an hour and refetched on an unknown kid."""
    with _certs_lock:
        stale = time.monotonic() - _certs['fetched_at'] > CERTS_TTL_SECONDS
        if stale or kid not in _certs['keys']:
            _certs['keys'] = _fetch_certs()
            _certs['fetched_at'] = time.monotonic()
        return _certs['keys']


def verify_iap_assertion(assertion, audience):
    """Return the verified claims, or raise ValueError."""
    from google.auth import jwt

    header = jwt.decode_header(assertion)
    if header.get('alg') != 'ES256':
        raise ValueError('unexpected IAP JWT algorithm')
    certs = _certs_for(header.get('kid'))
    claims = jwt.decode(assertion, certs=certs, audience=audience)
    if claims.get('iss') != IAP_ISSUER:
        raise ValueError('unexpected IAP JWT issuer')
    return claims


class IAPAdminMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(ADMIN_PREFIX) and getattr(settings, 'IAP_REQUIRED', False):
            audience = getattr(settings, 'IAP_AUDIENCE', '')
            assertion = request.META.get(IAP_HEADER, '')
            if not audience or not assertion:
                logger.warning('Admin request refused: %s', 'no IAP audience configured' if not audience
                               else 'missing IAP assertion')
                return HttpResponseForbidden()
            try:
                claims = verify_iap_assertion(assertion, audience)
            except Exception as exc:  # signature, expiry, audience, issuer or cert fetch
                logger.warning('Admin request refused: invalid IAP assertion (%s)', exc)
                return HttpResponseForbidden()
            request.iap_email = claims.get('email', '')
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                logger.info('Admin %s %s by IAP identity %s', request.method, request.path, request.iap_email)
        return self.get_response(request)
