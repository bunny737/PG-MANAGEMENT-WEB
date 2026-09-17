class NotificationChannel:
    """Interface every channel module implements. `send` must never raise —
    a broken provider (SMTP down, FCM unreachable, no SMS vendor configured)
    must not fail the request/task that triggered the notification; return
    a (status, note) pair instead, where status is one of
    `NotificationLog.Status` and note explains a failure/skip."""

    def send(self, *, recipient_email='', recipient_user=None, subject='', body=''):
        raise NotImplementedError
