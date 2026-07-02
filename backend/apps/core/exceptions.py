"""API exception handler ensuring a machine-readable, uppercase `code` field.

The frontend switches on codes (SUBSCRIPTION_SUSPENDED, EMAIL_NOT_VERIFIED,
PLAN_LIMIT_REACHED, ...) instead of parsing translated messages. simplejwt
exceptions already ship a `code` key; DRF ones carry it on the ErrorDetail.
"""
from rest_framework.views import exception_handler as drf_exception_handler


def api_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None and isinstance(response.data, dict):
        existing = response.data.get('code')
        if existing:
            response.data['code'] = str(existing).upper()
        else:
            detail = response.data.get('detail')
            code = getattr(detail, 'code', None) or getattr(exc, 'default_code', None)
            if code:
                response.data['code'] = str(code).upper()
    return response
