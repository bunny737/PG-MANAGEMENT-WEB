"""Generic notification dispatch (PRD Module 18; V2 channels/templates/
scheduling). `notify()` is the one entry point every trigger site and
Celery task calls — it resolves which channels apply, renders each
channel's `NotificationTemplate`, sends, and logs one `NotificationLog` row
per channel attempt. Never raises: a broken channel must not fail the
request/task that triggered it (invoice issuance, payment recording, ...)."""
from django.template import Context, Template
from django.utils import timezone


def _render(text, context):
    if not text:
        return ''
    return Template(text).render(Context(context, autoescape=False))


def render_template(*, notification_type, channel, language, context):
    """Resolves the best-match NotificationTemplate for
    (notification_type, channel, language), falling back to 'en' if that
    language has no active template yet (invariant 7 — a missing
    translation must degrade to English, never crash or send nothing).
    Returns (subject, body) or (None, None) if no template exists in either
    language (channel/type not configured at all)."""
    from .models import NotificationTemplate

    template = NotificationTemplate.objects.filter(
        notification_type=notification_type, channel=channel,
        language=language, is_active=True,
    ).first()
    if template is None and language != 'en':
        template = NotificationTemplate.objects.filter(
            notification_type=notification_type, channel=channel,
            language='en', is_active=True,
        ).first()
    if template is None:
        return None, None
    return _render(template.subject, context), _render(template.body, context)


def notify(*, tenant_id, notification_type, recipient_user, context, channels=None, reference=''):
    """Sends `notification_type` to `recipient_user` (an `accounts.User` or
    an `apps.residents.models.Resident` — anything with `.email` and
    optionally `.language_code`) across its applicable channels, logging one
    NotificationLog row per channel attempt. `channels`, if given, overrides
    the registry's default channel list for this call."""
    from django.contrib.auth import get_user_model

    from . import channels as channel_registry
    from .models import NotificationLog, NotificationPreference
    from .registry import channels_for, is_optional

    user_model = get_user_model()
    recipient_user_fk = recipient_user if isinstance(recipient_user, user_model) else None

    language = getattr(recipient_user, 'language_code', None) or 'en'
    candidate_channels = list(channels) if channels is not None else channels_for(notification_type)

    if is_optional(notification_type) and recipient_user_fk is not None:
        disabled = set(
            NotificationPreference.objects.filter(
                user=recipient_user_fk, notification_type=notification_type, enabled=False,
            ).values_list('channel', flat=True)
        )
        candidate_channels = [c for c in candidate_channels if c not in disabled]

    results = []
    for channel in candidate_channels:
        handler = channel_registry.get(channel)
        if handler is None:
            continue  # channel not wired up yet — not an error, just not built

        subject, body = render_template(
            notification_type=notification_type, channel=channel,
            language=language, context=context,
        )
        if body is None:
            results.append(NotificationLog.objects.create(
                tenant_id=tenant_id, notification_type=notification_type, channel=channel,
                recipient_user=recipient_user_fk,
                status=NotificationLog.Status.SKIPPED, reference=reference,
                note='No active template configured for this type/channel/language.',
            ))
            continue

        recipient_email = getattr(recipient_user, 'email', '') if channel == 'email' else ''
        status, note = handler.send(
            recipient_email=recipient_email,
            recipient_user=recipient_user, subject=subject, body=body,
            notification_type=notification_type, reference=reference,
        )
        results.append(NotificationLog.objects.create(
            tenant_id=tenant_id, notification_type=notification_type, channel=channel,
            recipient_email=recipient_email, recipient_user=recipient_user_fk,
            subject=subject, status=status, reference=reference, note=note,
            sent_at=timezone.now() if status == NotificationLog.Status.SENT else None,
        ))
    return results


def record_sent(*, tenant_id, notification_type, recipient_email, subject, reference='', channel='email', recipient_user=None):
    """Logs a notification that was already sent by other means (e.g. the
    signup welcome notification, fulfilled by apps.accounts.emails'
    send_verification_email — see apps.accounts.tasks). Does NOT send
    anything itself; use notify() when this module should own the actual
    send."""
    from .models import NotificationLog

    return NotificationLog.objects.create(
        tenant_id=tenant_id, notification_type=notification_type, channel=channel,
        recipient_email=recipient_email, recipient_user=recipient_user, subject=subject,
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
