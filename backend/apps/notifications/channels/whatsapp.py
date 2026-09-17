"""WhatsApp delivery — PRD Module 18 V2 scope. Same open vendor decision as
`sms.py` (WhatsApp Business API via Gupshup/Twilio/Meta directly — not
picked yet). Stubbed the same way: logs `skipped` until a provider is
wired in."""
from .base import NotificationChannel


class WhatsAppChannel(NotificationChannel):
    def send(self, *, recipient_email='', recipient_user=None, subject='', body=''):
        from apps.notifications.models import NotificationLog

        return NotificationLog.Status.SKIPPED, 'WhatsApp not configured — no provider selected yet (V2).'
