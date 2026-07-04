from datetime import timedelta

from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import Tenant
from apps.accounts.tests.base import AuthAPITestCase
from apps.core.models import PlatformConfig
from apps.core.roles import Role
from apps.core.tenancy import tenant_context

from apps.notifications.models import NotificationLog


class TrialExpiryReminderTests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        config = PlatformConfig.get()
        config.trial_reminder_first_days_before = 15
        config.trial_reminder_second_days_before = 5
        config.save()

    def _tenant_with_days_remaining(self, days):
        tenant = self.create_tenant(
            'Sunrise PG', trial_ends_at=timezone.now() + timedelta(days=days),
        )
        self.create_owner(tenant, email='owner@sunrise.example.com')
        return tenant

    def _logs(self, tenant_id):
        with tenant_context(tenant_id):
            return list(NotificationLog.objects.filter(notification_type='trial_expiry_reminder'))

    def test_sends_reminder_at_first_offset(self):
        tenant = self._tenant_with_days_remaining(15)

        call_command('send_trial_expiry_reminders')

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('owner@sunrise.example.com', mail.outbox[0].to)
        logs = self._logs(tenant.id)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].reference, f'tenant_trial:{tenant.id}:15')

    def test_sends_reminder_at_second_offset(self):
        tenant = self._tenant_with_days_remaining(5)

        call_command('send_trial_expiry_reminders')

        self.assertEqual(len(mail.outbox), 1)
        logs = self._logs(tenant.id)
        self.assertEqual(logs[0].reference, f'tenant_trial:{tenant.id}:5')

    def test_no_reminder_when_days_remaining_does_not_match_an_offset(self):
        self._tenant_with_days_remaining(10)

        call_command('send_trial_expiry_reminders')

        self.assertEqual(len(mail.outbox), 0)

    def test_ignores_non_trial_tenants(self):
        tenant = self._tenant_with_days_remaining(15)
        tenant.status = Tenant.Status.ACTIVE
        tenant.save()

        call_command('send_trial_expiry_reminders')

        self.assertEqual(len(mail.outbox), 0)

    def test_running_command_twice_does_not_resend(self):
        self._tenant_with_days_remaining(15)

        call_command('send_trial_expiry_reminders')
        call_command('send_trial_expiry_reminders')

        self.assertEqual(len(mail.outbox), 1)
