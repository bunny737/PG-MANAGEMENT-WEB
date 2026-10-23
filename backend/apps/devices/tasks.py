"""Privacy retention for app installs (settings: APP_INSTALLATION_RETENTION_DAYS
and APP_INSTALLATION_HISTORY_RETENTION_DAYS). Scheduled daily by a
django-celery-beat PeriodicTask seeded in migration 0002."""
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.core.tenancy import tenant_context

from .models import AppInstallation, AppInstallationHistory

logger = logging.getLogger(__name__)


@shared_task
def purge_stale_app_data():
    now = timezone.now()
    stale_installs = AppInstallation.objects.filter(
        last_seen_at__lt=now - timedelta(days=settings.APP_INSTALLATION_RETENTION_DAYS),
    )
    # Cascades to their history rows and nulls PushSubscription.installation
    # (SET_NULL). push_subscriptions is under RLS, so without a tenant context
    # that UPDATE would see no rows and the delete would fail the FK check.
    with tenant_context(None, is_super_admin=True):
        installs_deleted = stale_installs.delete()[0]
    history_deleted, _ = AppInstallationHistory.objects.filter(
        recorded_at__lt=now - timedelta(days=settings.APP_INSTALLATION_HISTORY_RETENTION_DAYS),
    ).delete()
    logger.info('app data retention purge: removed %s rows from installs/history cascade, %s old history rows',
                installs_deleted, history_deleted)
    return {'installs_and_cascade': installs_deleted, 'history': history_deleted}
