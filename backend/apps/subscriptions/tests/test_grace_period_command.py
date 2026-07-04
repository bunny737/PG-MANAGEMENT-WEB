from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone

from .base import SubscriptionAPITestCase


class GracePeriodCommandTests(SubscriptionAPITestCase):
    def test_suspends_tenants_past_grace_period(self):
        tenant = self.create_tenant()
        tenant.status = 'payment_failed'
        tenant.save()
        subscription = self.create_subscription(tenant)
        subscription.payment_failed_at = timezone.now() - timedelta(days=10)
        subscription.save()

        call_command('check_subscription_grace_periods')

        tenant.refresh_from_db()
        self.assertEqual(tenant.status, 'suspended')

    def test_does_not_suspend_tenants_still_within_grace_period(self):
        tenant = self.create_tenant()
        tenant.status = 'payment_failed'
        tenant.save()
        subscription = self.create_subscription(tenant)
        subscription.payment_failed_at = timezone.now() - timedelta(days=1)
        subscription.save()

        call_command('check_subscription_grace_periods')

        tenant.refresh_from_db()
        self.assertEqual(tenant.status, 'payment_failed')

    def test_ignores_tenants_not_in_payment_failed_status(self):
        tenant = self.create_tenant()  # trial
        subscription = self.create_subscription(tenant)
        subscription.payment_failed_at = timezone.now() - timedelta(days=30)
        subscription.save()

        call_command('check_subscription_grace_periods')

        tenant.refresh_from_db()
        self.assertEqual(tenant.status, 'trial')
