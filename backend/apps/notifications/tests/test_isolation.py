from django.utils import timezone

from apps.accounts.tests.base import AuthAPITestCase
from apps.core.tenancy import tenant_context

from apps.notifications.models import NotificationLog, NotificationPreference, PushSubscription, ScheduledNotification


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


class PushSubscriptionIsolationTests(AuthAPITestCase):
    def test_tenant_cannot_see_another_tenants_push_subscriptions(self):
        tenant_a = self.create_tenant('Tenant A')
        tenant_b = self.create_tenant('Tenant B')
        owner_a = self.create_owner(tenant_a, email='a@example.com')
        owner_b = self.create_owner(tenant_b, email='b@example.com')

        with tenant_context(tenant_a.id):
            PushSubscription.objects.create(tenant_id=tenant_a.id, user=owner_a, fcm_token='token-a', device_type='web')
        with tenant_context(tenant_b.id):
            PushSubscription.objects.create(tenant_id=tenant_b.id, user=owner_b, fcm_token='token-b', device_type='web')

        with tenant_context(tenant_a.id):
            self.assertEqual(list(PushSubscription.objects.values_list('fcm_token', flat=True)), ['token-a'])
        with tenant_context(None, is_super_admin=True):
            self.assertEqual(PushSubscription.objects.count(), 2)


class NotificationPreferenceIsolationTests(AuthAPITestCase):
    def test_tenant_cannot_see_another_tenants_preferences(self):
        tenant_a = self.create_tenant('Tenant A')
        tenant_b = self.create_tenant('Tenant B')
        owner_a = self.create_owner(tenant_a, email='a@example.com')
        owner_b = self.create_owner(tenant_b, email='b@example.com')

        with tenant_context(tenant_a.id):
            NotificationPreference.objects.create(
                tenant_id=tenant_a.id, user=owner_a, notification_type='invoice_issued',
                channel='email', enabled=False,
            )
        with tenant_context(tenant_b.id):
            NotificationPreference.objects.create(
                tenant_id=tenant_b.id, user=owner_b, notification_type='invoice_issued',
                channel='email', enabled=False,
            )

        with tenant_context(tenant_a.id):
            self.assertEqual(NotificationPreference.objects.count(), 1)
        with tenant_context(None, is_super_admin=True):
            self.assertEqual(NotificationPreference.objects.count(), 2)


class ScheduledNotificationIsolationTests(AuthAPITestCase):
    def test_tenant_cannot_see_another_tenants_scheduled_notifications(self):
        tenant_a = self.create_tenant('Tenant A')
        tenant_b = self.create_tenant('Tenant B')
        owner_a = self.create_owner(tenant_a, email='a@example.com')
        owner_b = self.create_owner(tenant_b, email='b@example.com')

        with tenant_context(tenant_a.id):
            ScheduledNotification.objects.create(
                tenant_id=tenant_a.id, notification_type='trial_expiry_reminder',
                recipient_user=owner_a, send_at=timezone.now(),
            )
        with tenant_context(tenant_b.id):
            ScheduledNotification.objects.create(
                tenant_id=tenant_b.id, notification_type='trial_expiry_reminder',
                recipient_user=owner_b, send_at=timezone.now(),
            )

        with tenant_context(tenant_a.id):
            self.assertEqual(ScheduledNotification.objects.count(), 1)
        with tenant_context(None, is_super_admin=True):
            self.assertEqual(ScheduledNotification.objects.count(), 2)
