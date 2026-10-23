"""API exception handler ensuring a machine-readable, uppercase `code` field.

The frontend switches on codes (SUBSCRIPTION_SUSPENDED, EMAIL_NOT_VERIFIED,
PLAN_LIMIT_REACHED, ...) instead of parsing translated messages. simplejwt
exceptions already ship a `code` key; DRF ones carry it on the ErrorDetail.
"""
from django.db import IntegrityError
from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class Conflict(APIException):
    """409 — the request is well-formed but conflicts with the resource's
    current state (a forbidden bed transition, a reused idempotency key...).
    Pass a string detail plus a specific `code`; the handler below upper-cases
    it into the `code` field clients switch on."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = _('This request conflicts with the current state of the resource.')
    default_code = 'conflict'


def api_exception_handler(exc, context):
    if isinstance(exc, IntegrityError):
        constraint = getattr(getattr(exc.__cause__, 'diag', None), 'constraint_name', None)
        if constraint == 'unique_active_email_lower':
            return Response(
                {
                    'email': [_('An account with this email already exists.')],
                    'code': 'EMAIL_TAKEN',
                },
                status=status.HTTP_409_CONFLICT,
            )
        elif constraint == 'unique_active_phone':
            return Response(
                {
                    'phone': [_('An account with this phone number already exists.')],
                    'code': 'PHONE_TAKEN',
                },
                status=status.HTTP_409_CONFLICT,
            )
        elif constraint == 'user_staff_requires_phone':
            return Response(
                {
                    'phone': [_('Phone number is required for staff accounts.')],
                    'code': 'PHONE_REQUIRED',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        elif constraint == 'user_requires_email_or_phone':
            return Response(
                {
                    'phone': [_('At least one of email or phone is required.')],
                    'code': 'IDENTIFIER_REQUIRED',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return None

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


class PayloadTooLarge(APIException):
    status_code = 413
    default_detail = _('Request body too large.')
    default_code = 'payload_too_large'
