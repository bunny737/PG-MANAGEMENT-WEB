from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.subscriptions.models import Plan, Subscription
from apps.subscriptions.services import generate_invoice_for_subscription


class Command(BaseCommand):
    """Daily sweep that closes out any PER_BED_MONTHLY billing cycle whose
    `current_period_end` has passed (PRD/owner decision: arrears billing,
    invoice generated at month end). Not wired to Celery beat, matching
    `check_subscription_grace_periods` — see the Module 13 spec's Decisions.

    Safe to re-run: `generate_invoice_for_subscription` is a no-op for any
    cycle that already has a `SubscriptionInvoice` row."""

    help = 'Generate arrears invoices for PER_BED_MONTHLY subscriptions whose billing cycle has closed.'

    def handle(self, *args, **options):
        today = timezone.now().date()
        due = Subscription.objects.filter(
            plan__pricing_type=Plan.PricingType.PER_BED_MONTHLY,
            current_period_end__lte=today,
        ).select_related('plan', 'tenant')

        generated = 0
        failed = 0
        for subscription in due:
            try:
                invoice = generate_invoice_for_subscription(subscription, today=today)
                if invoice is not None:
                    generated += 1
            except Exception as e:
                failed += 1
                self.stderr.write(
                    self.style.ERROR(
                        f'Failed to generate invoice for subscription {subscription.id} '
                        f'(tenant: {subscription.tenant.name}): {e}'
                    )
                )

        if failed > 0:
            self.stdout.write(
                self.style.WARNING(f'Generated {generated} invoice(s) with {failed} failure(s).')
            )
        else:
            self.stdout.write(self.style.SUCCESS(f'Generated {generated} invoice(s).'))
