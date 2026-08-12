from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import Tenant
from apps.core.tenancy import tenant_context
from apps.subscriptions.models import BedLedgerEntry, SubscriptionInvoice
from apps.subscriptions.services import generate_invoice_for_subscription
from apps.subscriptions.tests.base import SubscriptionAPITestCase


def _backdate_ledger_entries(tenant_id, when):
    """`Bed` creation stamps `BedLedgerEntry.occurred_at` at real wall-clock
    `now()` (see `signals.record_bed_added`), which falls outside any
    billing cycle a test constructs in the past/future. Tests that need
    beds "present throughout the cycle" backdate the entries here rather
    than depending on when the test happens to run."""
    with tenant_context(tenant_id):
        BedLedgerEntry.objects.filter(tenant_id=tenant_id).update(
            occurred_at=datetime(when.year, when.month, when.day, tzinfo=dt_timezone.utc)
        )


class GenerateInvoiceForSubscriptionTests(SubscriptionAPITestCase):
    def setUp(self):
        self.tenant = self.create_tenant(status=Tenant.Status.TRIAL)
        self.plan = self.create_bed_plan(bed_tiers=[(50, '0.00'), (300, '2.00'), (None, '1.50')])
        self.subscription = self.create_subscription(
            self.tenant, plan=self.plan,
            current_period_start=date(2026, 7, 1), current_period_end=date(2026, 8, 1),
        )
        prop = self.create_property(self.tenant)
        floor = self.create_floor(prop)
        room = self.create_room(floor)
        for i in range(100):
            self.create_bed(room, bed_number=f'bed-{i}')
        _backdate_ledger_entries(self.tenant.id, date(2026, 7, 1))

    def test_generates_invoice_with_line_items_summing_to_total(self):
        invoice = generate_invoice_for_subscription(self.subscription, today=date(2026, 8, 1))
        self.assertIsNotNone(invoice)
        # 100 beds: 50 free + 50 @ ₹2 = ₹100.
        self.assertEqual(invoice.total_amount, Decimal('100.00'))
        with tenant_context(self.tenant.id):
            lines = list(invoice.lines.all())
        self.assertGreater(len(lines), 0)
        self.assertEqual(sum(line.amount for line in lines), invoice.total_amount)

    def test_returns_none_before_cycle_closes(self):
        invoice = generate_invoice_for_subscription(self.subscription, today=date(2026, 7, 15))
        self.assertIsNone(invoice)

    def test_running_twice_for_the_same_cycle_is_a_no_op(self):
        first = generate_invoice_for_subscription(self.subscription, today=date(2026, 8, 1))
        self.assertIsNotNone(first)
        # The subscription has already advanced to the next cycle, so
        # re-running against the original (now stale, already-refreshed) row
        # for the same period_start must not create a second invoice.
        second = generate_invoice_for_subscription(self.subscription, today=date(2026, 8, 1))
        with tenant_context(self.tenant.id):
            count = SubscriptionInvoice.objects.filter(
                subscription=self.subscription, period_start=date(2026, 7, 1),
            ).count()
        self.assertEqual(count, 1)
        self.assertIsNone(second)

    def test_advances_subscription_to_next_cycle(self):
        generate_invoice_for_subscription(self.subscription, today=date(2026, 8, 1))
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.current_period_start, date(2026, 8, 1))
        self.assertEqual(self.subscription.current_period_end, date(2026, 9, 1))

    def test_zero_amount_cycle_is_marked_paid_without_razorpay_call(self):
        # Free-allowance-only plan: everything stays under min_billable_amount.
        free_plan = self.create_bed_plan(name='Free Tier', bed_tiers=[(None, '0.00')])
        tenant = self.create_tenant(name='Small PG')
        subscription = self.create_subscription(
            tenant, plan=free_plan,
            current_period_start=date(2026, 7, 1), current_period_end=date(2026, 8, 1),
        )
        invoice = generate_invoice_for_subscription(subscription, today=date(2026, 8, 1))
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.PAID)
        self.assertEqual(invoice.total_amount, Decimal('0.00'))
        self.assertEqual(invoice.razorpay_invoice_id, '')

    def test_billable_cycle_is_issued_with_a_razorpay_invoice_id(self):
        invoice = generate_invoice_for_subscription(self.subscription, today=date(2026, 8, 1))
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.ISSUED)
        self.assertNotEqual(invoice.razorpay_invoice_id, '')

    def test_flat_monthly_plan_is_not_touched(self):
        flat_plan = self.create_plan()
        tenant = self.create_tenant(name='Flat PG')
        subscription = self.create_subscription(
            tenant, plan=flat_plan,
            current_period_start=date(2026, 7, 1), current_period_end=date(2026, 8, 1),
        )
        invoice = generate_invoice_for_subscription(subscription, today=date(2026, 8, 1))
        self.assertIsNone(invoice)


class GenerateSubscriptionInvoicesCommandTests(SubscriptionAPITestCase):
    def setUp(self):
        # Exactly one cycle due "today" — not a backlog of years of cycles —
        # so that after the command closes it, the subscription's new
        # current_period_end lands in the future and a second run is a
        # true no-op, not "closes the next backlogged cycle".
        today = timezone.now().date()
        period_start = today - timedelta(days=30)
        self.tenant = self.create_tenant()
        self.plan = self.create_bed_plan(bed_tiers=[(50, '0.00'), (300, '2.00'), (None, '1.50')])
        self.subscription = self.create_subscription(
            self.tenant, plan=self.plan,
            current_period_start=period_start, current_period_end=today,
        )
        prop = self.create_property(self.tenant)
        floor = self.create_floor(prop)
        room = self.create_room(floor)
        self.create_bed(room)
        _backdate_ledger_entries(self.tenant.id, period_start)

    def test_command_generates_and_is_idempotent(self):
        call_command('generate_subscription_invoices')
        with tenant_context(self.tenant.id):
            count_after_first = SubscriptionInvoice.objects.filter(subscription=self.subscription).count()
        call_command('generate_subscription_invoices')
        with tenant_context(self.tenant.id):
            count_after_second = SubscriptionInvoice.objects.filter(subscription=self.subscription).count()
        self.assertEqual(count_after_first, 1)
        self.assertEqual(count_after_second, 1)
