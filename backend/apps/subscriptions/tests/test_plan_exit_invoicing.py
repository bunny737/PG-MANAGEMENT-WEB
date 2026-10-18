"""Leaving a per-bed plan must invoice what it accrued. Per-bed billing is in
arrears, so once the plan and period are overwritten that usage can't be priced."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Tenant
from apps.core.tenancy import tenant_context
from apps.subscriptions.models import SubscriptionInvoice
from apps.subscriptions.services import close_per_bed_period, process_invoice_issuing

from .base import SubscriptionAPITestCase
from .test_invoice_generation import _backdate_ledger_entries
from .test_webhook import webhook_payload

CANCEL = 'apps.subscriptions.razorpay_client.cancel_razorpay_subscription'
CREATE_INVOICE = 'apps.subscriptions.razorpay_client.create_razorpay_invoice'


class PlanExitInvoicingTestCase(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.now().date()
        self.tenant = self.create_tenant(status=Tenant.Status.ACTIVE)
        self.owner = self.create_owner(self.tenant)
        # 10 beds @ ₹30 = ₹300 for a full 30-day cycle.
        self.old_plan = self.create_bed_plan(name='Old Per Bed', bed_tiers=[(None, '30.00')])
        self.new_per_bed = self.create_bed_plan(name='New Per Bed', bed_tiers=[(None, '99.00')])
        self.flat = self.create_plan(
            name='Flat Test', price_per_month='249.00', max_properties=None, max_residents_per_property=None,
        )
        self.period_start = self.today - timedelta(days=10)
        self.period_end = self.today + timedelta(days=20)
        self.subscription = self.create_subscription(
            self.tenant, plan=self.old_plan, razorpay_customer_id='cust_test',
            current_period_start=self.period_start, current_period_end=self.period_end,
        )
        room = self.create_room(self.create_floor(self.create_property(self.tenant)))
        for i in range(10):
            self.create_bed(room, bed_number=f'bed-{i}')
        _backdate_ledger_entries(self.tenant.id, self.period_start)
        self.authenticate(self.owner)

    def select(self, plan):
        # The invoice is sent to Razorpay in an on-commit callback, which a TestCase's
        # wrapping transaction never fires on its own.
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                reverse('subscription-select-plan', args=[self.tenant.id]), {'plan': str(plan.id)}, format='json',
            )

    def invoices(self):
        with tenant_context(self.tenant.id):
            return list(SubscriptionInvoice.objects.filter(subscription=self.subscription).order_by('period_start'))


class SwitchingBetweenPerBedPlansTests(PlanExitInvoicingTestCase):
    def test_the_old_plan_is_invoiced_for_the_days_it_ran_before_the_switch(self):
        with mock.patch(CANCEL):
            response = self.select(self.new_per_bed)
        self.assertEqual(response.status_code, 200, response.data)

        (invoice,) = self.invoices()
        # 10 of the cycle's 30 days at ₹300/month.
        self.assertEqual(invoice.total_amount, Decimal('100.00'))
        self.assertEqual(invoice.period_start, self.period_start)
        self.assertEqual(invoice.period_end, self.today)
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.ISSUED)
        self.assertEqual(invoice.tenant_id, self.tenant.id)
        with tenant_context(self.tenant.id):
            self.assertEqual(sum(line.amount for line in invoice.lines.all()), invoice.total_amount)

    def test_the_new_plan_starts_a_fresh_period_from_today(self):
        with mock.patch(CANCEL):
            self.select(self.new_per_bed)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, self.new_per_bed)
        self.assertEqual(self.subscription.current_period_start, self.today)

    def test_switching_again_the_same_day_bills_nothing_more(self):
        with mock.patch(CANCEL):
            self.select(self.new_per_bed)
            self.select(self.old_plan)
        self.assertEqual(len(self.invoices()), 1)

    def test_nothing_is_invoiced_when_no_day_has_accrued(self):
        self.subscription.current_period_start = self.today
        self.subscription.save(update_fields=['current_period_start'])
        with mock.patch(CANCEL):
            self.select(self.new_per_bed)
        self.assertEqual(self.invoices(), [])

    def test_a_cycle_that_ended_uninvoiced_is_billed_whole_before_the_partial_one(self):
        self.subscription.current_period_start = self.today - timedelta(days=40)
        self.subscription.current_period_end = self.today - timedelta(days=10)
        self.subscription.save(update_fields=['current_period_start', 'current_period_end'])
        _backdate_ledger_entries(self.tenant.id, self.today - timedelta(days=40))
        with mock.patch(CANCEL):
            self.select(self.new_per_bed)

        whole, partial = self.invoices()
        self.assertEqual(whole.period_start, self.today - timedelta(days=40))
        self.assertEqual(whole.period_end, self.today - timedelta(days=10))
        self.assertEqual(whole.total_amount, Decimal('300.00'))
        self.assertEqual(partial.period_start, self.today - timedelta(days=10))
        self.assertEqual(partial.period_end, self.today)
        self.assertGreater(partial.total_amount, Decimal('0'))

    def test_a_razorpay_outage_does_not_block_the_switch_and_the_invoice_is_sent_later(self):
        with mock.patch(CREATE_INVOICE, side_effect=RuntimeError('boom')), mock.patch(CANCEL):
            response = self.select(self.new_per_bed)
        self.assertEqual(response.status_code, 200, response.data)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, self.new_per_bed)

        (invoice,) = self.invoices()
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.DRAFT)
        self.assertEqual(invoice.razorpay_invoice_id, '')
        self.assertEqual(invoice.issue_attempts, 1)
        self.assertIn('boom', invoice.last_issue_error)

        self.assertEqual(process_invoice_issuing(), {'issued': 1, 'failed': 0})
        (invoice,) = self.invoices()
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.ISSUED)
        self.assertNotEqual(invoice.razorpay_invoice_id, '')

    def test_a_later_failure_rolls_everything_back_and_nothing_reaches_razorpay(self):
        # The transaction fails after the invoice was priced: the switch and the invoice
        # both roll back, and no Razorpay invoice was ever created for the retry to duplicate.
        with mock.patch(CREATE_INVOICE) as create, mock.patch(CANCEL), mock.patch(
            'apps.subscriptions.services.audit_log.record', side_effect=RuntimeError('db down'),
        ), self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse('subscription-select-plan', args=[self.tenant.id]),
                    {'plan': str(self.new_per_bed.id)}, format='json',
                )
        create.assert_not_called()
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, self.old_plan)
        self.assertEqual(self.subscription.current_period_start, self.period_start)
        self.assertEqual(self.invoices(), [])


class SwitchingToFlatPlanTests(PlanExitInvoicingTestCase):
    def test_the_paid_promotion_invoices_the_per_bed_arrears_first(self):
        self.select(self.flat)  # pending until Razorpay confirms the first charge
        self.subscription.refresh_from_db()
        pending_id = self.subscription.pending_razorpay_subscription_id
        self.assertEqual(self.invoices(), [])

        with mock.patch(CANCEL), self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('razorpay-webhook'), webhook_payload('subscription.activated', pending_id), format='json',
            )
        self.assertEqual(response.status_code, 200)

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, self.flat)
        (invoice,) = self.invoices()
        self.assertEqual(invoice.total_amount, Decimal('100.00'))
        self.assertEqual(invoice.period_start, self.period_start)
        self.assertEqual(invoice.period_end, self.today)

    def test_selecting_a_flat_plan_does_not_invoice_until_it_is_paid(self):
        self.select(self.flat)
        self.assertEqual(self.invoices(), [])


class CloseHelperTests(PlanExitInvoicingTestCase):
    def test_a_flat_plan_has_nothing_to_close(self):
        self.subscription.plan = self.flat
        self.subscription.save(update_fields=['plan'])
        self.assertEqual(close_per_bed_period(self.subscription), [])

    def test_closing_twice_does_not_double_bill(self):
        self.assertEqual(len(close_per_bed_period(self.subscription)), 1)
        self.assertEqual(close_per_bed_period(self.subscription), [])
        self.assertEqual(len(self.invoices()), 1)
