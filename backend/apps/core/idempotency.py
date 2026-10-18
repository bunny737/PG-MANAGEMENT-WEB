"""`Idempotency-Key` request header for money-creating POSTs (payments,
expenses). A retried request (flaky mobile network, double tap) carrying the
same key returns the record the first attempt created instead of creating a
second one. Keys are unique per tenant per resource, enforced by a partial
unique constraint on the resource's own `idempotency_key` column — so the
guarantee holds across workers without a separate key store.
"""
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from .exceptions import Conflict

HEADER = 'HTTP_IDEMPOTENCY_KEY'
MAX_LENGTH = 100


def idempotency_key(request):
    """The request's key, or None when the header is absent/blank."""
    key = request.META.get(HEADER, '').strip()
    if not key:
        return None
    if len(key) > MAX_LENGTH or not key.isprintable():
        raise ValidationError(
            {'idempotency_key': [_('Idempotency-Key must be at most %(max)s printable characters.')
                                 % {'max': MAX_LENGTH}]},
            code='invalid_idempotency_key',
        )
    return key


def key_reused():
    """The key was already used for a request with a different body."""
    return Conflict(
        _('This Idempotency-Key was already used for a different request.'),
        code='idempotency_key_reused',
    )
