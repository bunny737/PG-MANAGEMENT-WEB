"""Push notifications via Firebase Cloud Messaging (FCM). Covers both Web
Push (the Serwist service worker planned in docs/frontend-plan.md §5.2) and
native Android push later (Android's locked stack is Kotlin + FCM-compatible
by default), from one backend integration — see the module spec's Decisions.

Only recipients that are a real login account (`accounts.User`) can receive
push: `PushSubscription.user` is a User FK, but most notification recipients
today are `apps.residents.models.Resident` rows, which have no linked User
account yet (see that model's docstring — "No linked login (User) account
yet"). Until residents get login accounts, push resolves for
Owner/Manager/Receptionist recipients only (e.g. trial-expiry reminders);
resident-facing types (invoice_issued, payment_receipt) are skipped with an
explicit note, not silently dropped."""
import json
import logging

from django.conf import settings

from .base import NotificationChannel

logger = logging.getLogger(__name__)

_firebase_app = None
_firebase_init_attempted = False


def _get_firebase_app():
    """Lazy, memoized init — importing this module must never require
    Firebase credentials to exist (dev/test runs with push simply
    unconfigured, same fail-open discipline as every other channel)."""
    global _firebase_app, _firebase_init_attempted
    if _firebase_init_attempted:
        return _firebase_app
    _firebase_init_attempted = True
    if not (settings.FIREBASE_CREDENTIALS_JSON or settings.FIREBASE_CREDENTIALS_PATH):
        return None
    try:
        import firebase_admin
        from firebase_admin import credentials

        if settings.FIREBASE_CREDENTIALS_PATH:
            cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
        else:
            cred = credentials.Certificate(json.loads(settings.FIREBASE_CREDENTIALS_JSON))
        _firebase_app = firebase_admin.initialize_app(cred)
    except Exception:
        logger.exception('Failed to initialize Firebase app; push notifications disabled.')
        _firebase_app = None
    return _firebase_app


class PushChannel(NotificationChannel):
    def send(self, *, recipient_email='', recipient_user=None, subject='', body=''):
        from django.contrib.auth import get_user_model

        from apps.notifications.models import NotificationLog, PushSubscription

        user_model = get_user_model()
        if not isinstance(recipient_user, user_model):
            return (
                NotificationLog.Status.SKIPPED,
                'Recipient has no linked login account (push requires a User).',
            )

        app = _get_firebase_app()
        if app is None:
            return NotificationLog.Status.SKIPPED, 'Push not configured (no Firebase credentials).'

        tokens = list(
            PushSubscription.objects.filter(user=recipient_user).values_list('fcm_token', flat=True)
        )
        if not tokens:
            return NotificationLog.Status.SKIPPED, 'No registered push devices for this user.'

        from firebase_admin import messaging

        sent_count = 0
        invalid_tokens = []
        errors = []
        for token in tokens:
            message = messaging.Message(
                notification=messaging.Notification(title=subject, body=body),
                token=token,
            )
            try:
                messaging.send(message, app=app)
                sent_count += 1
            except messaging.UnregisteredError:
                invalid_tokens.append(token)
            except Exception as exc:
                errors.append(str(exc))

        if invalid_tokens:
            # Token pruning — a stale/uninstalled-app token must not keep
            # being retried forever.
            PushSubscription.objects.filter(fcm_token__in=invalid_tokens).delete()

        if sent_count:
            return NotificationLog.Status.SENT, ''
        if errors:
            return NotificationLog.Status.FAILED, '; '.join(errors)
        return NotificationLog.Status.SKIPPED, 'All registered devices were unregistered.'
