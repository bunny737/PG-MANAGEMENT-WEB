from django.core.management.base import BaseCommand

from apps.notifications.services import due_trial_reminders
from apps.notifications.tasks import send_trial_expiry_reminder_task


class Command(BaseCommand):
    """Daily sweep (PRD Module 18: 'Trial expiry reminders (Day 45, Day 55)').
    Not wired to a Celery beat schedule yet — same reasoning as Module 13's
    check_subscription_grace_periods; run this via cron or a manual ops trigger."""

    help = 'Send trial-expiry reminder emails to tenants hitting a configured offset today.'

    def handle(self, *args, **options):
        due = due_trial_reminders()
        for tenant, days_remaining in due:
            send_trial_expiry_reminder_task.delay(str(tenant.id), days_remaining)
        self.stdout.write(self.style.SUCCESS(f'Dispatched {len(due)} trial-expiry reminder(s).'))
