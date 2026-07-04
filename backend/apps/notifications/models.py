import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModelMixin


class NotificationLog(TenantModelMixin):
    """Audit trail of every notification the platform has attempted to send
    (PRD Module 18, MVP = email only). Written by the Celery task that
    actually sends the message, whether it succeeds, fails, or is skipped
    (e.g. resident has no email on file) — this is the only visibility into
    the notification system for now (see spec Decisions re: no dedicated API)."""

    class NotificationType(models.TextChoices):
        WELCOME = 'welcome', _('Welcome')
        TRIAL_EXPIRY_REMINDER = 'trial_expiry_reminder', _('Trial Expiry Reminder')
        INVOICE_ISSUED = 'invoice_issued', _('Invoice Issued')
        PAYMENT_RECEIPT = 'payment_receipt', _('Payment Receipt')

    class Status(models.TextChoices):
        SENT = 'sent', _('Sent')
        FAILED = 'failed', _('Failed')
        SKIPPED = 'skipped', _('Skipped')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification_type = models.CharField(max_length=25, choices=NotificationType.choices)
    recipient_email = models.EmailField(blank=True)
    subject = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    # e.g. 'invoice:<uuid>', 'payment:<uuid>', 'user:<uuid>',
    # 'tenant_trial:<uuid>:<days_before>' — also doubles as the idempotency
    # key for trial reminders (see services.check_trial_expiry_reminders).
    reference = models.CharField(max_length=255, blank=True, db_index=True)
    note = models.TextField(blank=True)  # error message, or why it was skipped
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'notification_logs'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_notification_type_display()} -> {self.recipient_email or "(no email)"} [{self.status}]'
