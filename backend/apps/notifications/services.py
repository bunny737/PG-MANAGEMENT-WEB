"""Low-level send+log helper, and the trial-expiry-reminder scan (PRD Module
18 MVP; Module 20's trial state). Actual dispatch happens in tasks.py so it
runs off the request/command thread via Celery."""
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import NotificationLog


def send_and_log(*, tenant_id, notification_type, recipient_email, subject, body, reference=''):
    """Sends one email and records the outcome. Never raises — a broken SMTP
    server must not fail the request/task that triggered the notification
    (invoice issuance, payment recording, ...); the failure is captured in
    NotificationLog instead (visible via Django admin)."""
    if not recipient_email:
        return NotificationLog.objects.create(
            tenant_id=tenant_id, notification_type=notification_type,
            status=NotificationLog.Status.SKIPPED, reference=reference,
            note='No email address on file.',
        )
    try:
        send_mail(
            subject=subject, message=body, from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email], fail_silently=False,
        )
    except Exception as exc:
        return NotificationLog.objects.create(
            tenant_id=tenant_id, notification_type=notification_type,
            recipient_email=recipient_email, subject=subject,
            status=NotificationLog.Status.FAILED, reference=reference, note=str(exc),
        )
    return NotificationLog.objects.create(
        tenant_id=tenant_id, notification_type=notification_type,
        recipient_email=recipient_email, subject=subject,
        status=NotificationLog.Status.SENT, reference=reference, sent_at=timezone.now(),
    )


def record_sent(*, tenant_id, notification_type, recipient_email, subject, reference=''):
    """Logs a notification that was already sent by other means (e.g. the
    signup welcome notification, fulfilled by apps.accounts.emails'
    send_verification_email — see apps.accounts.tasks). Does NOT send mail
    itself; use send_and_log when this module should own the actual send."""
    return NotificationLog.objects.create(
        tenant_id=tenant_id, notification_type=notification_type,
        recipient_email=recipient_email, subject=subject,
        status=NotificationLog.Status.SENT, reference=reference, sent_at=timezone.now(),
    )


def due_trial_reminders():
    """Tenants whose trial hits a configured reminder offset today, paired
    with the offset that matched. A tenant can match at most one offset per
    day since the two configured values are expected to differ; if a Super
    Admin sets them equal, both fire once each (deduped separately by
    reference in the caller)."""
    from apps.accounts.models import Tenant
    from apps.core.models import PlatformConfig

    config = PlatformConfig.get()
    offsets = [config.trial_reminder_first_days_before, config.trial_reminder_second_days_before]
    today = timezone.localdate()

    due = []
    tenants = Tenant.objects.filter(status=Tenant.Status.TRIAL)
    for tenant in tenants:
        trial_end_date = timezone.localtime(tenant.trial_ends_at).date()
        days_remaining = (trial_end_date - today).days
        for offset in offsets:
            if days_remaining == offset:
                due.append((tenant, offset))
    return due
