from apps.accounts.tests.base import AuthAPITestCase
from apps.core.tenancy import tenant_context

from apps.notifications.models import NotificationLog


class NotificationLogIsolationTests(AuthAPITestCase):
    def test_tenant_cannot_see_another_tenants_notification_logs(self):
        tenant_a = self.create_tenant('Tenant A')
        tenant_b = self.create_tenant('Tenant B')

        with tenant_context(tenant_a.id):
            NotificationLog.objects.create(
                tenant_id=tenant_a.id, notification_type='welcome',
                recipient_email='a@example.com', status='sent', reference=f'user:{tenant_a.id}',
            )
        with tenant_context(tenant_b.id):
            NotificationLog.objects.create(
                tenant_id=tenant_b.id, notification_type='welcome',
                recipient_email='b@example.com', status='sent', reference=f'user:{tenant_b.id}',
            )

        with tenant_context(tenant_a.id):
            visible = list(NotificationLog.objects.all())
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0].recipient_email, 'a@example.com')

        with tenant_context(tenant_b.id):
            visible = list(NotificationLog.objects.all())
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0].recipient_email, 'b@example.com')

        with tenant_context(None, is_super_admin=True):
            self.assertEqual(NotificationLog.objects.count(), 2)
