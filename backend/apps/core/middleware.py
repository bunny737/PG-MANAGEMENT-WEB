import logging

from django.http import JsonResponse
from django.utils.translation import gettext as _

from . import net
from .tenancy import clear_tenant_context

security_logger = logging.getLogger('apps.security')


class TenantContextMiddleware:
    """Clears the Postgres tenant GUCs after every request so persistent
    connections can never carry one request's tenant context into the next."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        finally:
            clear_tenant_context()


class ClientIPMiddleware:
    """Resolves the trusted client IP once per request (see apps.core.net).
    Requests carrying BFF origin headers that do not verify are rejected —
    never silently attributed to the BFF's own address."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if net.has_origin_headers(request):
            try:
                net.set_client_ip(request, net.verify_origin(request))
            except net.OriginSignatureError as exc:
                security_logger.warning(
                    'Rejected request with unverifiable origin headers: %s (path=%s edge_ip=%s)',
                    exc.reason, request.path, net.get_client_ip(request),
                )
                return JsonResponse(
                    {'detail': _('The request could not be verified.'), 'code': 'INVALID_ORIGIN_SIGNATURE'},
                    status=400,
                )
        return self.get_response(request)
