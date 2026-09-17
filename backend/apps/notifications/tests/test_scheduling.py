from datetime import timedelta

from django.core import mail
from django.utils import timezone

from apps.accounts.tests.base import AuthAPITestCase
from apps.core.models import PlatformConfig
from apps.core.tenancy import tenant_context

from apps.notifications.models import NotificationLog, NotificationTemplate, ScheduledNotification
from apps.notifications.tasks import dispatch_scheduled_notifications, run_due_sweep


class RecurringSweepTests(AuthAPITestCase):
    """run_due_sweep is the django-celery-beat PeriodicTask entry point that
    replaces the original MVP's "external cron only" trial-reminder sweep —
    verify it drives the exact same dispatch as the (still-kept)
    send_trial_expiry_reminders management command."""

    def setUp(self):
        super().setUp()
        config = PlatformConfig.get()
        config.trial_reminder_first_days_before = 15
        config.trial_reminder_second_days_before = 5
        config.save()

    def test_sweep_sends_reminders_for_due_tenants(self):
        tenant = self.create_tenant('Sunrise PG', trial_ends_at=timezone.now() + timedelta(days=15))
        self.create_owner(tenant, email='owner@sunrise.example.com')

        run_due_sweep('trial_expiry_reminders')

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('owner@sunrise.example.com', mail.outbox[0].to)

    def test_unknown_sweep_key_is_a_no_op(self):
        run_due_sweep('does_not_exist')
        self.assertEqual(len(mail.outbox), 0)


class ScheduledNotificationTests(AuthAPITestCase):
    """dispatch_scheduled_notifications is polled every minute by a
    django-celery-beat IntervalSchedule (see the seeded PeriodicTask in
    0004_seed_periodic_tasks.py)."""

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        # invoice_issued/email/en already exists via the 0003 seed migration.
        NotificationTemplate.objects.update_or_create(
            notification_type='invoice_issued', channel='email', language='en',
            defaults={'subject': 'Notice', 'body': 'Hello {{ name }}', 'is_active': True},
        )

    def test_sends_a_due_scheduled_notification(self):
        with tenant_context(self.tenant.id):
            scheduled = ScheduledNotification.objects.create(
                tenant_id=self.tenant.id, notification_type='invoice_issued',
                recipient_user=self.owner, context={'name': 'Owner'},
                channels=['email'], send_at=timezone.now() - timedelta(minutes=1),
            )

        dispatch_scheduled_notifications()

        with tenant_context(self.tenant.id):
            scheduled.refresh_from_db()
            self.assertEqual(scheduled.status, ScheduledNotification.Status.SENT)
            self.assertTrue(
                NotificationLog.objects.filter(reference=f'scheduled:{scheduled.id}', status='sent').exists()
            )

    def test_does_not_send_a_future_scheduled_notification(self):
        with tenant_context(self.tenant.id):
            scheduled = ScheduledNotification.objects.create(
                tenant_id=self.tenant.id, notification_type='invoice_issued',
                recipient_user=self.owner, context={'name': 'Owner'},
                channels=['email'], send_at=timezone.now() + timedelta(hours=1),
            )

        dispatch_scheduled_notifications()

        with tenant_context(self.tenant.id):
            scheduled.refresh_from_db()
            self.assertEqual(scheduled.status, ScheduledNotification.Status.PENDING)

    def test_does_not_resend_an_already_sent_notification(self):
        with tenant_context(self.tenant.id):
            scheduled = ScheduledNotification.objects.create(
                tenant_id=self.tenant.id, notification_type='invoice_issued',
                recipient_user=self.owner, context={'name': 'Owner'},
                channels=['email'], send_at=timezone.now() - timedelta(minutes=1),
                status=ScheduledNotification.Status.SENT,
            )

        dispatch_scheduled_notifications()

        with tenant_context(self.tenant.id):
            self.assertFalse(
                NotificationLog.objects.filter(reference=f'scheduled:{scheduled.id}').exists()
            )
