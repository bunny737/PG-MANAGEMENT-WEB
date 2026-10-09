"""App-client middleware: parses X-App-* headers, tags logs/Sentry, and
enforces maintenance (503) and forced updates (426).

Enforcement is gated by settings.APP_VERSION_ENFORCEMENT = off | log | on and
applies ONLY to requests carrying usable X-App-* headers — web, Postman and
admin traffic is never blocked. Every failure inside this middleware fails
OPEN (the request proceeds): a cache/DB hiccup must not lock users out.
"""
import hmac
import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.utils.translation import gettext as _

from .client import current_app_client, parse_app_client, tag_sentry
from .policy import get_policy, iso_z

logger = logging.getLogger(__name__)

MAINTENANCE_CODE = 'MAINTENANCE'
UPDATE_REQUIRED_CODE = 'APP_UPDATE_REQUIRED'
BYPASS_HEADER = 'HTTP_X_MAINTENANCE_BYPASS'

# Never gated: the app must always be able to ask "do I need to update?" and
# report itself; ops/static paths carry no app headers anyway. Login, OTP and
# refresh are deliberately NOT here — an old build is stopped there too.
EXEMPT_PREFIXES = (
    '/api/v1/app/version-policy/',
    '/api/v1/devices/',
    '/admin/',
    '/static/',
    '/media/',
    '/health',
)


def _is_exempt(path):
    prefixes = EXEMPT_PREFIXES + tuple(getattr(settings, 'APP_VERSION_EXEMPT_PREFIXES', ()))
    return any(path.startswith(p) or path == p.rstrip('/') for p in prefixes)


def _enforcement_mode():
    mode = str(getattr(settings, 'APP_VERSION_ENFORCEMENT', 'log')).strip().lower()
    return mode if mode in ('off', 'log', 'on') else 'off'


def _has_maintenance_bypass(request):
    """QA/staff bypass: a shared secret in X-Maintenance-Bypass. (Not an IP
    allowlist — behind a load balancer REMOTE_ADDR is the balancer and
    X-Forwarded-For is client-controlled.)"""
    secret = getattr(settings, 'APP_MAINTENANCE_BYPASS_TOKEN', '')
    supplied = request.META.get(BYPASS_HEADER, '')
    return bool(secret) and bool(supplied) and hmac.compare_digest(secret, supplied)


class AppClientMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        client = None
        try:
            client = parse_app_client(request)
        except Exception:  # pragma: no cover - parsing is already lenient
            logger.exception('X-App-* header parsing failed')
        request.app_client = client
        if client is None:
            return self.get_response(request)

        token = current_app_client.set(client)
        try:
            tag_sentry(client)
            blocked = self._enforce(request, client)
            if blocked is not None:
                return blocked
            return self.get_response(request)
        finally:
            current_app_client.reset(token)

    def _enforce(self, request, client):
        try:
            mode = _enforcement_mode()
            if mode == 'off' or client.platform is None or _is_exempt(request.path):
                return None
            policy = get_policy(client.platform, client.flavor or 'prod')
            if policy is None:
                return None
            now = timezone.now()

            if policy.maintenance_active(now) and not _has_maintenance_bypass(request):
                if mode == 'on':
                    return self._maintenance_response(policy, now)
                logger.warning('app enforcement (log mode): would block with MAINTENANCE path=%s', request.path)

            if client.build is not None and client.build < policy.min_build:
                if mode == 'on':
                    return self._update_required_response(policy)
                logger.warning(
                    'app enforcement (log mode): would block with APP_UPDATE_REQUIRED build=%s min_build=%s path=%s',
                    client.build, policy.min_build, request.path,
                )
        except Exception:
            logger.exception('app enforcement failed; letting the request through')
        return None

    @staticmethod
    def _maintenance_response(policy, now):
        response = JsonResponse({
            'detail': _('Down for maintenance'),
            'code': MAINTENANCE_CODE,
            'message': policy.maintenance_message or None,
            'expires_at': iso_z(policy.maintenance_expires_at),
        }, status=503)
        # An intentional 503 is not a server error: stop django.request from
        # logging it at ERROR (it would flood Sentry for the whole outage).
        response._has_been_logged = True
        if policy.maintenance_expires_at is not None:
            response['Retry-After'] = str(max(1, int((policy.maintenance_expires_at - now).total_seconds())))
        return response

    @staticmethod
    def _update_required_response(policy):
        return JsonResponse({
            'detail': _('Please update the app'),
            'code': UPDATE_REQUIRED_CODE,
            'min_supported_build': policy.min_build,
            'store_url': policy.store_url or None,
        }, status=426)
