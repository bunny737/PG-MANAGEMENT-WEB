from django.core import mail
from django.urls import reverse

from apps.accounts.models import Tenant, User
from apps.accounts.tests.base import STRONG_PASSWORD, AuthAPITestCase
from apps.core.tenancy import tenant_context

from apps.notifications.models import NotificationLog


class WelcomeEmailNotificationTests(AuthAPITestCase):
    def test_signup_logs_a_welcome_notification(self):
        payload = {
            'business_name': 'Sunrise PG', 'first_name': 'Ramesh', 'last_name': 'Kumar',
            'email': 'ramesh@example.com', 'phone': '+919876543210', 'password': STRONG_PASSWORD,
        }
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('auth-signup'), payload)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)  # one email — no duplicate "welcome" send
        tenant = Tenant.objects.get(name='Sunrise PG')
        user = User.objects.get(email='ramesh@example.com')
        with tenant_context(tenant.id):
            logs = list(NotificationLog.objects.filter(notification_type='welcome'))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].status, 'sent')
        self.assertEqual(logs[0].recipient_email, user.email)
        self.assertEqual(logs[0].reference, f'user:{user.id}')
