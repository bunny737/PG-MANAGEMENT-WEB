from django.core.management.base import BaseCommand

from apps.subscriptions.services import process_payment_grace_periods


class Command(BaseCommand):
    """Daily sweep (PRD §4: 'Payment failure grace period: 5 days before
    account suspension'). Not wired to a Celery beat schedule yet — see the
    Module 13 spec's Decisions; run this via cron or a manual ops trigger."""

    help = 'Suspend tenants whose payment-failure grace period has elapsed.'

    def handle(self, *args, **options):
        suspended = process_payment_grace_periods()
        self.stdout.write(self.style.SUCCESS(f'Suspended {len(suspended)} tenant(s).'))
