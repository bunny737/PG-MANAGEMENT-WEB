from django.urls import reverse

from apps.accounts.tests.base import AuthAPITestCase
from apps.core.roles import Role
from apps.core.tenancy import tenant_context

from apps.notifications.models import NotificationLog


class NotificationHistoryAPITests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.manager = self.create_user(self.tenant, Role.MANAGER, 'manager@example.com')

    def test_user_sees_only_their_own_notifications(self):
        with tenant_context(self.tenant.id):
            NotificationLog.objects.create(
                tenant_id=self.tenant.id, notification_type='trial_expiry_reminder', channel='email',
                recipient_user=self.owner, recipient_email=self.owner.email, status='sent',
            )
            NotificationLog.objects.create(
                tenant_id=self.tenant.id, notification_type='trial_expiry_reminder', channel='email',
                recipient_user=self.manager, recipient_email=self.manager.email, status='sent',
            )

        self.authenticate(self.owner)
        response = self.client.get(reverse('notification-history-list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['notification_type'], 'trial_expiry_reminder')

    def test_logs_with_no_recipient_user_are_not_visible_to_anyone(self):
        # e.g. a Resident recipient (no login account) — recipient_user is
        # null, so it can only ever appear in the admin-only cross-recipient
        # view, never in a user's own history.
        with tenant_context(self.tenant.id):
            NotificationLog.objects.create(
                tenant_id=self.tenant.id, notification_type='invoice_issued', channel='email',
                recipient_email='resident@example.com', status='sent',
            )

        self.authenticate(self.owner)
        response = self.client.get(reverse('notification-history-list'))

        self.assertEqual(response.data, [])
