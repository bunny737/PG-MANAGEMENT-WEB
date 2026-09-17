import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModelMixin


class Channel(models.TextChoices):
    EMAIL = 'email', _('Email')
    SMS = 'sms', _('SMS')
    WHATSAPP = 'whatsapp', _('WhatsApp')
    PUSH = 'push', _('Push')


class NotificationLog(TenantModelMixin):
    """Audit trail of every notification the platform has attempted to send,
    across every channel (PRD Module 18). Written by the channel handler
    dispatched from `services.notify()`, whether it succeeds, fails, or is
    skipped (e.g. resident has no email on file, or a channel isn't
    configured yet) — this plus the resident/owner-facing history endpoint
    is the visibility into the notification system (see spec Decisions)."""

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
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.EMAIL)
    recipient_email = models.EmailField(blank=True)
    # Set whenever the recipient is a real login account (an `accounts.User`
    # — e.g. an Owner getting a trial reminder), regardless of channel, so
    # the /notifications/history/ endpoint can find "logs about me" even for
    # non-email channels. Null for Resident recipients (no login account —
    # see PushSubscription's docstring) and for the pre-V2 rows migrated
    # before this field existed.
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='notification_logs',
    )
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
        return f'{self.get_notification_type_display()} [{self.channel}] -> {self.recipient_email or "(no recipient)"} [{self.status}]'


class NotificationTemplate(models.Model):
    """Platform-wide, Super-Admin-editable wording for one
    (notification_type, channel, language) combination — see
    `apps.notifications.registry` for the type catalog and each type's
    documented context variables. Not tenant-scoped (no RLS): every tenant's
    residents get the same wording in this pass; per-tenant overrides are
    out of scope (see the module spec's Decisions).

    `body` is rendered with Django's template engine with autoescape off
    (these are plain-text emails/SMS/push bodies, not HTML) — a Super Admin
    can use `{{ name }}` placeholders and `{% if %}` for optional lines."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification_type = models.CharField(max_length=50, db_index=True)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    language = models.CharField(max_length=8, choices=settings.LANGUAGES)
    # Blank for channels with no subject concept (sms/whatsapp/push use body
    # only; push's "title" is the first line of body by convention).
    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notification_templates'
        ordering = ['notification_type', 'channel', 'language']
        constraints = [
            models.UniqueConstraint(
                fields=['notification_type', 'channel', 'language'],
                name='unique_template_per_type_channel_language',
            ),
        ]

    def __str__(self):
        return f'{self.notification_type} [{self.channel}/{self.language}]'


class NotificationPreference(TenantModelMixin):
    """A recipient's opt-out of one (notification_type, channel) pair. Only
    meaningful for types the registry marks `optional=True` — a non-optional
    type (e.g. a payment receipt) ignores any row here (see
    `services.notify`'s preference-filtering step). Absence of a row means
    "enabled" (opt-out model, not opt-in) so existing users keep receiving
    everything they get today until they actively turn something off."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notification_preferences')
    notification_type = models.CharField(max_length=50)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'notification_preferences'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'notification_type', 'channel'],
                name='unique_preference_per_user_type_channel',
            ),
        ]

    def __str__(self):
        return f'{self.user_id}: {self.notification_type}/{self.channel} = {self.enabled}'


class PushSubscription(TenantModelMixin):
    """One registered FCM device token for a user (web browser via the
    Serwist service worker, or the Flutter app on Android/iOS — see
    `channels/push.py` and `docs/push-notifications-integration.md`).
    `user` is an `accounts.User`, not a `Resident`: residents have no login
    account yet, so they can't register a device (see that limitation
    documented in `channels/push.py`)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='push_subscriptions')

    class DeviceType(models.TextChoices):
        WEB = 'web', _('Web')
        ANDROID = 'android', _('Android')
        IOS = 'ios', _('iOS')

    fcm_token = models.CharField(max_length=255, unique=True)
    device_type = models.CharField(max_length=10, choices=DeviceType.choices)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'push_subscriptions'

    def __str__(self):
        return f'{self.user_id} [{self.device_type}]'


class ScheduledNotification(TenantModelMixin):
    """A one-off notification to send at a specific time (e.g. "notify this
    tenant's Owner at 6pm tomorrow"), as opposed to a recurring sweep (which
    is a django-celery-beat `PeriodicTask` — see
    `apps.notifications.tasks.run_due_sweep`). A minute-cadence beat task
    (`dispatch_scheduled_notifications`) polls for `PENDING` rows past their
    `send_at` and dispatches each through `services.notify()`."""

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        SENT = 'sent', _('Sent')
        CANCELLED = 'cancelled', _('Cancelled')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification_type = models.CharField(max_length=50)
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='scheduled_notifications',
    )
    context = models.JSONField(default=dict, blank=True)
    channels = models.JSONField(default=list, blank=True)  # empty = registry default for the type
    send_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_scheduled_notifications',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'scheduled_notifications'
        ordering = ['send_at']
        indexes = [models.Index(fields=['status', 'send_at'])]

    def __str__(self):
        return f'{self.notification_type} -> {self.recipient_user_id} at {self.send_at} [{self.status}]'
