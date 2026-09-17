from django.conf import settings
from django.core.mail import send_mail

from .base import NotificationChannel


class EmailChannel(NotificationChannel):
    """Same send behavior as the original Module 14 MVP
    (`services.send_and_log`, now folded into this handler) — never raises,
    a broken SMTP server is reported back as (FAILED, str(exc))."""

    def send(self, *, recipient_email='', recipient_user=None, subject='', body=''):
        from apps.notifications.models import NotificationLog

        if not recipient_email:
            return NotificationLog.Status.SKIPPED, 'No email address on file.'
        try:
            send_mail(
                subject=subject, message=body, from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient_email], fail_silently=False,
            )
        except Exception as exc:
            return NotificationLog.Status.FAILED, str(exc)
        return NotificationLog.Status.SENT, ''
