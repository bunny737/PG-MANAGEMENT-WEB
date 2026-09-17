"""SMS delivery — PRD Module 18 V2 scope. No provider (MSG91, Gupshup,
Twilio — all common for the India market) has been chosen yet; picking one
is a vendor decision for the owner, not something to guess at (see the
module spec's Decisions — matches CLAUDE.md's "stop and ask" rule for a new
external dependency). This handler exists so the channel interface and any
`sms` NotificationTemplate rows can be authored now; it only logs `skipped`
until a provider is wired in here."""
from .base import NotificationChannel


class SMSChannel(NotificationChannel):
    def send(self, *, recipient_email='', recipient_user=None, subject='', body=''):
        from apps.notifications.models import NotificationLog

        return NotificationLog.Status.SKIPPED, 'SMS not configured — no provider selected yet (V2).'
