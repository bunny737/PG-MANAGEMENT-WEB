"""Nightly housekeeping for resident app access (Module 26).

Nothing here decides who has access. Access ends at `access_expires_at` itself: the scope check
(apps.residents.access.residency_scope) compares it to now() on every request, so a late or failed
run of this task cannot extend anyone's access. The task only makes the stored status say what is
already true, so lists and reports read correctly.
"""
import logging

from celery import shared_task
from django.utils import timezone

from apps.core.tenancy import tenant_context

from .models import ResidentAccess, ResidentInvite

logger = logging.getLogger(__name__)


@shared_task
def tidy_resident_access():
    """Mark links past their expiry `expired`, and invites past theirs `expired`."""
    now = timezone.now()
    with tenant_context(is_super_admin=True):
        links = ResidentAccess.objects.filter(
            status=ResidentAccess.Status.ACTIVE, access_expires_at__lte=now,
        ).update(status=ResidentAccess.Status.EXPIRED, updated_at=now)
        invites = ResidentInvite.objects.filter(
            status=ResidentInvite.Status.PENDING, expires_at__lte=now,
        ).update(status=ResidentInvite.Status.EXPIRED, updated_at=now)
    logger.info('resident access tidy: %s link(s) and %s invite(s) marked expired', links, invites)
    return {'links_expired': links, 'invites_expired': invites}
