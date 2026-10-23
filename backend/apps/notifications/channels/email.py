from apps.core.email import send_templated_email

from .base import NotificationChannel


class EmailChannel(NotificationChannel):
    """Same send behavior as the original Module 14 MVP
    (`services.send_and_log`, now folded into this handler) — never raises,
    a broken SMTP server is reported back as (FAILED, str(exc)). The editable
    NotificationTemplate text is wrapped in the branded layout; it is escaped
    in the HTML part."""

    def send(self, *, recipient_email='', recipient_user=None, subject='', body='',
              notification_type='', reference=''):
        from apps.notifications.models import NotificationLog

        if not recipient_email:
            return NotificationLog.Status.SKIPPED, 'No email address on file.'
        try:
            send_templated_email(
                to=recipient_email,
                subject=subject,
                template='notification',
                context={'subject': subject, 'body': body},
                language=getattr(recipient_user, 'language_code', None) or 'en',
            )
        except Exception as exc:
            return NotificationLog.Status.FAILED, str(exc)
        return NotificationLog.Status.SENT, ''
