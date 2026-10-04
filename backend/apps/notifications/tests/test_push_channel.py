from unittest.mock import patch

from apps.accounts.tests.base import AuthAPITestCase
from apps.core.tenancy import tenant_context

from apps.notifications.channels.push import PushChannel
from apps.notifications.models import NotificationLog, PushSubscription


class PushChannelTests(AuthAPITestCase):
    """channels/push.py must fail open at every stage — no Firebase
    credentials configured (dev/test default), a recipient with no login
    account (most Resident-facing types today), and a provider error must
    all degrade to a clean (SKIPPED/FAILED, note) rather than raise, since a
    broken push provider must never fail the request/task that triggered
    the notification."""

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)

    def test_skips_when_recipient_has_no_login_account(self):
        status, note = PushChannel().send(recipient_user=None, subject='Hi', body='Body')
        self.assertEqual(status, NotificationLog.Status.SKIPPED)
        self.assertIn('no linked login account', note)

    def test_skips_when_firebase_not_configured(self):
        # settings.FIREBASE_CREDENTIALS_PATH/JSON are blank by default in
        # dev/test — same fail-open discipline as email with no SMTP host.
        status, note = PushChannel().send(recipient_user=self.owner, subject='Hi', body='Body')
        self.assertEqual(status, NotificationLog.Status.SKIPPED)
        self.assertIn('not configured', note)

    def test_skips_when_no_registered_devices(self):
        with patch('apps.notifications.channels.push._get_firebase_app', return_value=object()):
            status, note = PushChannel().send(recipient_user=self.owner, subject='Hi', body='Body')
        self.assertEqual(status, NotificationLog.Status.SKIPPED)
        self.assertIn('No registered push devices', note)

    def test_sends_to_every_registered_token(self):
        with tenant_context(self.tenant.id):
            PushSubscription.objects.create(
                tenant_id=self.tenant.id, user=self.owner, fcm_token='token-a', device_type='web',
            )
            PushSubscription.objects.create(
                tenant_id=self.tenant.id, user=self.owner, fcm_token='token-b', device_type='android',
            )
            with patch('apps.notifications.channels.push._get_firebase_app', return_value=object()):
                with patch('firebase_admin.messaging.send') as mock_send:
                    status, note = PushChannel().send(recipient_user=self.owner, subject='Hi', body='Body')

        self.assertEqual(status, NotificationLog.Status.SENT)
        self.assertEqual(mock_send.call_count, 2)

    def test_prunes_unregistered_token_and_reports_skipped_if_none_left(self):
        from firebase_admin import messaging

        with tenant_context(self.tenant.id):
            PushSubscription.objects.create(
                tenant_id=self.tenant.id, user=self.owner, fcm_token='stale-token', device_type='web',
            )
            with patch('apps.notifications.channels.push._get_firebase_app', return_value=object()):
                with patch('firebase_admin.messaging.send', side_effect=messaging.UnregisteredError('gone')):
                    status, note = PushChannel().send(recipient_user=self.owner, subject='Hi', body='Body')

            self.assertEqual(status, NotificationLog.Status.SKIPPED)
            self.assertFalse(PushSubscription.objects.filter(fcm_token='stale-token').exists())

    def test_includes_notification_type_and_reference_as_data_for_deep_linking(self):
        with tenant_context(self.tenant.id):
            PushSubscription.objects.create(
                tenant_id=self.tenant.id, user=self.owner, fcm_token='token-a', device_type='web',
            )
            with patch('apps.notifications.channels.push._get_firebase_app', return_value=object()):
                with patch('firebase_admin.messaging.send') as mock_send:
                    PushChannel().send(
                        recipient_user=self.owner, subject='Hi', body='Body',
                        notification_type='invoice_issued', reference='invoice:abc-123',
                    )

        sent_message = mock_send.call_args[0][0]
        self.assertEqual(sent_message.data, {'notification_type': 'invoice_issued', 'reference': 'invoice:abc-123'})

    def test_provider_error_reports_failed(self):
        with tenant_context(self.tenant.id):
            PushSubscription.objects.create(
                tenant_id=self.tenant.id, user=self.owner, fcm_token='token-a', device_type='web',
            )
            with patch('apps.notifications.channels.push._get_firebase_app', return_value=object()):
                with patch('firebase_admin.messaging.send', side_effect=RuntimeError('network down')):
                    status, note = PushChannel().send(recipient_user=self.owner, subject='Hi', body='Body')

        self.assertEqual(status, NotificationLog.Status.FAILED)
        self.assertIn('network down', note)
