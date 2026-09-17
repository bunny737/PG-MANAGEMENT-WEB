from django.urls import reverse

from apps.accounts.tests.base import AuthAPITestCase
from apps.core.tenancy import tenant_context

from apps.notifications.models import NotificationTemplate
from apps.notifications.services import notify


class NotificationPreferenceAPITests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.authenticate(self.owner)

    def test_list_defaults_to_enabled_for_every_optional_type_channel(self):
        response = self.client.get(reverse('notification-preference-list'))

        self.assertEqual(response.status_code, 200)
        pairs = {(row['notification_type'], row['channel']) for row in response.data}
        # invoice_issued is the only optional=True type in the registry today.
        self.assertIn(('invoice_issued', 'email'), pairs)
        self.assertIn(('invoice_issued', 'push'), pairs)
        self.assertTrue(all(row['enabled'] for row in response.data))

    def test_non_optional_type_is_not_listed(self):
        response = self.client.get(reverse('notification-preference-list'))

        types = {row['notification_type'] for row in response.data}
        self.assertNotIn('payment_receipt', types)  # optional=False in registry.py

    def test_upsert_disables_a_channel(self):
        response = self.client.post(
            reverse('notification-preference-list'),
            {'notification_type': 'invoice_issued', 'channel': 'email', 'enabled': False},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        row = next(r for r in response.data if r['channel'] == 'email' and r['notification_type'] == 'invoice_issued')
        self.assertFalse(row['enabled'])

    def test_cannot_disable_a_non_optional_type(self):
        response = self.client.post(
            reverse('notification-preference-list'),
            {'notification_type': 'payment_receipt', 'channel': 'email', 'enabled': False},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_disabled_preference_actually_suppresses_the_channel(self):
        # invoice_issued/email/en already exists via the 0003 seed migration.
        NotificationTemplate.objects.update_or_create(
            notification_type='invoice_issued', channel='email', language='en',
            defaults={'subject': 'Invoice', 'body': 'Total {{ total }}', 'is_active': True},
        )
        self.client.post(
            reverse('notification-preference-list'),
            {'notification_type': 'invoice_issued', 'channel': 'email', 'enabled': False},
            format='json',
        )

        with tenant_context(self.tenant.id):
            results = notify(
                tenant_id=self.tenant.id, notification_type='invoice_issued',
                recipient_user=self.owner, context={'total': '100'}, reference='pref-test',
            )
        self.assertNotIn('email', [r.channel for r in results])
