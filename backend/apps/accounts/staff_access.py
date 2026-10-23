"""Locking helper shared by every writer of a staff member's role / module access."""
from contextlib import contextmanager

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework.exceptions import NotFound

from apps.core.roles import STAFF_ROLES

from .models import User


@contextmanager
def locked_staff(pk, tenant):
    """Yield the tenant's staff user `pk`, row-locked and freshly loaded.

    The transaction stays open for the whole `with` body, so validation, the save
    and the audit write commit (or roll back) as one unit. Both the module-access
    endpoints and the role/phone/name PATCH go through here, so a role change and a
    module-access change can never interleave on stale data, and the audit "before"
    values always come from the locked row.
    """
    with transaction.atomic():
        try:
            user = (
                User.objects.select_for_update()
                .get(pk=pk, tenant=tenant, role__in=STAFF_ROLES)
            )
        except (User.DoesNotExist, DjangoValidationError, ValueError):
            raise NotFound()
        yield user
