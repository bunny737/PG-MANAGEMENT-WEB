"""Invoices are priced and saved as DRAFT inside a transaction that may roll back, and
sent to Razorpay only afterwards, so a rollback can't strand a live Razorpay invoice and a
retry can't bill twice."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.subscriptions import razorpay_client
from apps.subscriptions.razorpay_client import RazorpayInvoice
from apps.subscriptions.models import Subscription, SubscriptionInvoice, SubscriptionInvoiceLine
from apps.subscriptions.services import (
    INVOICE_ISSUE_CLAIM_TIMEOUT,
    issue_invoice,
    process_invoice_issuing,
)

from .base import SubscriptionAPITestCase

CREATE_INVOICE = 'apps.subscriptions.razorpay_client.create_razorpay_invoice'


def make_draft(test, tenant, *, amount='100.00', cycles_ago=1):
    """One DRAFT invoice; a tenant can have several if they cover different cycles."""
    subscription = Subscription.objects.filter(tenant=tenant).first() or test.create_subscription(
        tenant, plan=test.plan, razorpay_customer_id=f'cust_{tenant.id.hex[:8]}',
    )
    with tenant_context(tenant.id):
        invoice = SubscriptionInvoice.objects.create(
            tenant_id=tenant.id, subscription=subscription,
            period_start=timezone.now().date() - timedelta(days=30 * cycles_ago),
            period_end=timezone.now().date() - timedelta(days=30 * (cycles_ago - 1)),
            status=SubscriptionInvoice.Status.DRAFT, total_amount=Decimal(amount),
            billed_bed_count_start=10, billed_bed_count_end=10,
        )
        SubscriptionInvoiceLine.objects.create(
            tenant_id=tenant.id, invoice=invoice, description='10 beds', quantity=Decimal('10'),
            unit_rate=Decimal('10.00'), amount=Decimal(amount),
        )
    return invoice


def set_fields(invoice, **fields):
    with tenant_context(invoice.tenant_id):
        SubscriptionInvoice.objects.filter(pk=invoice.pk).update(**fields)


def reload(invoice):
    with tenant_context(invoice.tenant_id):
        return SubscriptionInvoice.objects.get(pk=invoice.pk)


class IssueInvoiceTests(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.plan = self.create_bed_plan(bed_tiers=[(None, '10.00')])
        self.invoice = make_draft(self, self.tenant)

    def test_issues_a_draft_and_records_the_razorpay_id(self):
        self.assertTrue(issue_invoice(self.invoice.pk, self.tenant.id))
        invoice = reload(self.invoice)
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.ISSUED)
        self.assertNotEqual(invoice.razorpay_invoice_id, '')
        self.assertIsNotNone(invoice.issued_at)
        self.assertIsNone(invoice.issue_claimed_at)

    def test_an_issued_invoice_is_never_sent_again(self):
        issue_invoice(self.invoice.pk, self.tenant.id)
        with mock.patch(CREATE_INVOICE) as create:
            self.assertIsNone(issue_invoice(self.invoice.pk, self.tenant.id))
        create.assert_not_called()

    def test_an_invoice_another_worker_holds_is_left_alone(self):
        set_fields(self.invoice, issue_claimed_at=timezone.now())
        with mock.patch(CREATE_INVOICE) as create:
            self.assertIsNone(issue_invoice(self.invoice.pk, self.tenant.id))
        create.assert_not_called()

    def test_a_claim_left_by_a_dead_worker_is_taken_over(self):
        set_fields(
            self.invoice, issue_claimed_at=timezone.now() - INVOICE_ISSUE_CLAIM_TIMEOUT - timedelta(minutes=1),
        )
        self.assertTrue(issue_invoice(self.invoice.pk, self.tenant.id))

    def test_a_failure_keeps_the_draft_records_the_error_and_releases_the_claim(self):
        with mock.patch(CREATE_INVOICE, side_effect=RuntimeError('gateway timeout')):
            self.assertIs(issue_invoice(self.invoice.pk, self.tenant.id), False)
        invoice = reload(self.invoice)
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.DRAFT)
        self.assertEqual(invoice.razorpay_invoice_id, '')
        self.assertEqual(invoice.issue_attempts, 1)
        self.assertIn('gateway timeout', invoice.last_issue_error)
        self.assertIsNone(invoice.issue_claimed_at)
        # ...so the very next attempt can take it.
        self.assertTrue(issue_invoice(self.invoice.pk, self.tenant.id))

    def test_the_first_failure_is_audited(self):
        with mock.patch(CREATE_INVOICE, side_effect=RuntimeError('boom')):
            issue_invoice(self.invoice.pk, self.tenant.id)
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='subscription.invoice_issue_failed').exists())

    def test_the_invoice_id_is_what_makes_a_retry_safe(self):
        with mock.patch(CREATE_INVOICE, return_value=RazorpayInvoice('inv_1', '', 'issued')) as create:
            issue_invoice(self.invoice.pk, self.tenant.id)
        sent = create.call_args.args[1]
        self.assertEqual(sent.pk, self.invoice.pk)


class InvoiceIssuingSweepTests(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.plan = self.create_bed_plan(bed_tiers=[(None, '10.00')])
        self.tenant_a = self.create_tenant(name='PG A')
        self.tenant_b = self.create_tenant(name='PG B')

    def test_issues_drafts_across_tenants(self):
        a = make_draft(self, self.tenant_a)
        b = make_draft(self, self.tenant_b)
        self.assertEqual(process_invoice_issuing(), {'issued': 2, 'failed': 0})
        self.assertEqual(reload(a).status, SubscriptionInvoice.Status.ISSUED)
        self.assertEqual(reload(b).status, SubscriptionInvoice.Status.ISSUED)

    def test_each_invoice_is_issued_under_its_own_tenant_with_its_own_customer(self):
        make_draft(self, self.tenant_a)
        make_draft(self, self.tenant_b)
        with mock.patch(CREATE_INVOICE, side_effect=lambda customer, inv: RazorpayInvoice(f'inv_{inv.tenant_id.hex[:6]}', '', 'issued')) as create:
            process_invoice_issuing()
        customers = {call.args[0] for call in create.call_args_list}
        self.assertEqual(customers, {f'cust_{self.tenant_a.id.hex[:8]}', f'cust_{self.tenant_b.id.hex[:8]}'})

    def test_skips_issued_paid_and_claimed_invoices(self):
        issued = make_draft(self, self.tenant_a)
        issue_invoice(issued.pk, self.tenant_a.id)
        paid = make_draft(self, self.tenant_a, cycles_ago=2)
        set_fields(paid, status=SubscriptionInvoice.Status.PAID)
        claimed = make_draft(self, self.tenant_b)
        set_fields(claimed, issue_claimed_at=timezone.now())
        with mock.patch(CREATE_INVOICE) as create:
            self.assertEqual(process_invoice_issuing(), {'issued': 0, 'failed': 0})
        create.assert_not_called()

    def test_one_failure_does_not_stop_the_others(self):
        make_draft(self, self.tenant_a)
        make_draft(self, self.tenant_b)
        calls = []

        def flaky(customer, invoice):
            calls.append(invoice.pk)
            if len(calls) == 1:
                raise RuntimeError('boom')
            return RazorpayInvoice('inv_ok', '', 'issued')

        with mock.patch(CREATE_INVOICE, side_effect=flaky):
            self.assertEqual(process_invoice_issuing(), {'issued': 1, 'failed': 1})
        self.assertEqual(process_invoice_issuing(), {'issued': 1, 'failed': 0})

    def test_the_sweep_is_scheduled(self):
        from django_celery_beat.models import PeriodicTask

        task = PeriodicTask.objects.get(name='subscriptions.retry_invoice_issuing')
        self.assertTrue(task.enabled)
        self.assertEqual(task.task, 'apps.subscriptions.tasks.retry_invoice_issuing')
        from apps.subscriptions.tasks import retry_invoice_issuing

        make_draft(self, self.tenant_a)
        self.assertEqual(retry_invoice_issuing(), {'issued': 1, 'failed': 0})


class RazorpayInvoiceReceiptTests(SubscriptionAPITestCase):
    """create_razorpay_invoice must not create a second Razorpay invoice for one of ours."""

    def setUp(self):
        super().setUp()
        self.plan = self.create_bed_plan(bed_tiers=[(None, '10.00')])
        self.invoice = make_draft(self, self.create_tenant())
        self.client_mock = mock.MagicMock()
        patcher = mock.patch.object(razorpay_client, 'get_client', return_value=self.client_mock)
        patcher.start()
        self.addCleanup(patcher.stop)
        with tenant_context(self.invoice.tenant_id):
            self.invoice = SubscriptionInvoice.objects.get(pk=self.invoice.pk)

    def call(self):
        with tenant_context(self.invoice.tenant_id):
            return razorpay_client.create_razorpay_invoice('cust_1', self.invoice)

    def test_a_new_invoice_is_created_with_our_id_as_the_receipt_and_issued(self):
        self.client_mock.invoice.all.return_value = {'items': []}
        self.client_mock.invoice.create.return_value = {'id': 'inv_new'}
        self.client_mock.invoice.issue.return_value = {'short_url': 'https://rzp.io/i/x'}

        self.assertEqual(self.call(), RazorpayInvoice('inv_new', 'https://rzp.io/i/x', 'issued'))
        payload = self.client_mock.invoice.create.call_args.args[0]
        self.assertEqual(payload['receipt'], str(self.invoice.pk))
        self.client_mock.invoice.all.assert_called_once_with({'receipt': str(self.invoice.pk)})

    def test_an_invoice_razorpay_already_issued_is_reused_not_recreated(self):
        self.client_mock.invoice.all.return_value = {
            'items': [{'id': 'inv_prev', 'status': 'issued', 'short_url': 'https://rzp.io/i/prev'}],
        }
        self.assertEqual(self.call(), RazorpayInvoice('inv_prev', 'https://rzp.io/i/prev', 'issued'))
        self.client_mock.invoice.create.assert_not_called()
        self.client_mock.invoice.issue.assert_not_called()

    def test_a_draft_left_by_a_crash_between_create_and_issue_is_issued(self):
        self.client_mock.invoice.all.return_value = {'items': [{'id': 'inv_half', 'status': 'draft'}]}
        self.client_mock.invoice.issue.return_value = {'id': 'inv_half', 'short_url': 'https://rzp.io/i/half'}
        self.assertEqual(self.call(), RazorpayInvoice('inv_half', 'https://rzp.io/i/half', 'issued'))
        self.client_mock.invoice.create.assert_not_called()
        self.client_mock.invoice.issue.assert_called_once_with('inv_half')

    def test_a_reused_invoice_reports_its_real_status_and_payment(self):
        self.client_mock.invoice.all.return_value = {
            'items': [{'id': 'inv_paid', 'status': 'paid', 'payment_id': 'pay_9', 'short_url': 'https://rzp.io/i/p'}],
        }
        self.assertEqual(self.call(), RazorpayInvoice('inv_paid', 'https://rzp.io/i/p', 'paid', 'pay_9'))

    def test_the_local_stub_is_stable_for_one_invoice(self):
        self.client_mock = None
        with mock.patch.object(razorpay_client, 'get_client', return_value=None):
            first = razorpay_client.create_razorpay_invoice('cust_1', self.invoice)
            second = razorpay_client.create_razorpay_invoice('cust_1', self.invoice)
        self.assertEqual(first, second)
