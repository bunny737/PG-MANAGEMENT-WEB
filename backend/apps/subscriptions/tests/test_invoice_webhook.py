"""invoice.* webhooks settle a per-bed SubscriptionInvoice, including when the response
to our Razorpay create call was lost and we hold no Razorpay id yet."""
import uuid
from decimal import Decimal
from unittest import mock

from django.urls import reverse

from apps.accounts.models import Tenant
from apps.core.tenancy import set_tenant_context, tenant_context
from apps.subscriptions.models import SubscriptionInvoice, SubscriptionPayment
from apps.subscriptions.razorpay_client import RazorpayInvoice
from apps.subscriptions.services import process_invoice_issuing

from .base import SubscriptionAPITestCase
from .test_invoice_issuing import CREATE_INVOICE, make_draft, reload, set_fields


def invoice_payload(event, razorpay_invoice_id, *, receipt=None, payment_id='pay_inv_1'):
    entity = {'id': razorpay_invoice_id}
    if receipt is not None:
        entity['receipt'] = receipt
    return {
        'event': event,
        'payload': {'invoice': {'entity': entity}, 'payment': {'entity': {'id': payment_id}}},
    }


class InvoiceWebhookTestCase(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.plan = self.create_bed_plan(bed_tiers=[(None, '10.00')])
        self.tenant = self.create_tenant(status=Tenant.Status.PAYMENT_FAILED)
        self.invoice = make_draft(self, self.tenant)

    def post(self, payload):
        return self.client.post(reverse('razorpay-webhook'), payload, format='json')

    def payments(self):
        with tenant_context(self.tenant.id):
            return list(SubscriptionPayment.objects.filter(subscription=self.invoice.subscription))


class IssuedInvoiceWebhookTests(InvoiceWebhookTestCase):
    def setUp(self):
        super().setUp()
        set_fields(
            self.invoice, status=SubscriptionInvoice.Status.ISSUED, razorpay_invoice_id='inv_known',
        )

    def test_a_paid_event_settles_the_invoice_and_records_the_payment(self):
        response = self.post(invoice_payload('invoice.paid', 'inv_known'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(reload(self.invoice).status, SubscriptionInvoice.Status.PAID)
        (payment,) = self.payments()
        self.assertEqual(payment.amount, Decimal('100.00'))
        self.assertEqual(payment.status, SubscriptionPayment.Status.SUCCESS)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)

    def test_a_replayed_paid_event_is_a_no_op(self):
        self.post(invoice_payload('invoice.paid', 'inv_known'))
        self.post(invoice_payload('invoice.paid', 'inv_known'))
        self.assertEqual(len(self.payments()), 1)

    def test_an_unknown_invoice_is_ignored(self):
        self.assertEqual(self.post(invoice_payload('invoice.paid', 'inv_other')).status_code, 200)
        self.assertEqual(self.payments(), [])


class LostResponseRecoveryTests(InvoiceWebhookTestCase):
    """Razorpay created the invoice but the response never reached us, so the local
    invoice is a DRAFT with no Razorpay id."""

    def test_a_paid_event_is_matched_by_receipt_and_settles_the_invoice(self):
        response = self.post(invoice_payload('invoice.paid', 'inv_remote', receipt=str(self.invoice.pk)))
        self.assertEqual(response.status_code, 200)
        invoice = reload(self.invoice)
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.PAID)
        self.assertEqual(invoice.razorpay_invoice_id, 'inv_remote')
        (payment,) = self.payments()
        self.assertEqual(payment.razorpay_payment_id, 'pay_inv_1')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)

    def test_the_retry_sweep_then_leaves_the_settled_invoice_alone(self):
        self.post(invoice_payload('invoice.paid', 'inv_remote', receipt=str(self.invoice.pk)))
        with mock.patch(CREATE_INVOICE) as create:
            self.assertEqual(process_invoice_issuing(), {'issued': 0, 'failed': 0})
        create.assert_not_called()
        self.assertEqual(reload(self.invoice).status, SubscriptionInvoice.Status.PAID)

    def test_an_event_that_is_not_a_settlement_still_binds_and_issues_the_draft(self):
        self.post(invoice_payload('invoice.issued', 'inv_remote', receipt=str(self.invoice.pk)))
        invoice = reload(self.invoice)
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.ISSUED)
        self.assertEqual(invoice.razorpay_invoice_id, 'inv_remote')

    def test_a_receipt_for_an_invoice_bound_to_a_different_razorpay_id_is_refused(self):
        set_fields(self.invoice, status=SubscriptionInvoice.Status.ISSUED, razorpay_invoice_id='inv_ours')
        self.post(invoice_payload('invoice.paid', 'inv_stranger', receipt=str(self.invoice.pk)))
        invoice = reload(self.invoice)
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.ISSUED)
        self.assertEqual(invoice.razorpay_invoice_id, 'inv_ours')
        self.assertEqual(self.payments(), [])

    def test_an_id_bound_between_the_lookup_and_the_row_lock_is_not_overridden(self):
        # The lookup saw the invoice unbound; another process then bound inv_ours before
        # this webhook got the row lock.
        stale = reload(self.invoice)
        set_fields(self.invoice, status=SubscriptionInvoice.Status.ISSUED, razorpay_invoice_id='inv_ours')
        with mock.patch('apps.subscriptions.services._invoice_for_webhook', return_value=stale):
            self.post(invoice_payload('invoice.paid', 'inv_stranger', receipt=str(self.invoice.pk)))
        invoice = reload(self.invoice)
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.ISSUED)
        self.assertEqual(invoice.razorpay_invoice_id, 'inv_ours')
        self.assertEqual(self.payments(), [])

    def test_a_malformed_or_unknown_receipt_is_ignored(self):
        for receipt in ('not-a-uuid', str(uuid.uuid4()), ''):
            with self.subTest(receipt=receipt):
                self.assertEqual(self.post(invoice_payload('invoice.paid', 'inv_x', receipt=receipt)).status_code, 200)
        self.assertEqual(reload(self.invoice).status, SubscriptionInvoice.Status.DRAFT)
        self.assertEqual(self.payments(), [])

    def test_a_receipt_only_ever_reaches_its_own_tenants_invoice(self):
        other_tenant = self.create_tenant(name='Other PG', status=Tenant.Status.PAYMENT_FAILED)
        other = make_draft(self, other_tenant)
        self.post(invoice_payload('invoice.paid', 'inv_remote', receipt=str(self.invoice.pk)))
        self.assertEqual(reload(self.invoice).status, SubscriptionInvoice.Status.PAID)
        self.assertEqual(reload(other).status, SubscriptionInvoice.Status.DRAFT)
        other_tenant.refresh_from_db()
        self.assertEqual(other_tenant.status, Tenant.Status.PAYMENT_FAILED)


class RetryFindsRemoteInvoiceTests(InvoiceWebhookTestCase):
    """The retry finds the invoice Razorpay already created and takes its real status."""

    def retry(self, remote):
        with mock.patch(CREATE_INVOICE, return_value=remote):
            return process_invoice_issuing()

    def test_a_remote_invoice_already_paid_is_recorded_as_paid(self):
        result = self.retry(RazorpayInvoice('inv_remote', '', 'paid', 'pay_77'))
        self.assertEqual(result, {'issued': 1, 'failed': 0})
        invoice = reload(self.invoice)
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.PAID)
        self.assertEqual(invoice.razorpay_invoice_id, 'inv_remote')
        (payment,) = self.payments()
        self.assertEqual(payment.razorpay_payment_id, 'pay_77')
        self.assertEqual(payment.status, SubscriptionPayment.Status.SUCCESS)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)

    def test_a_remote_invoice_that_expired_is_recorded_as_failed(self):
        self.tenant.status = Tenant.Status.ACTIVE
        self.tenant.save(update_fields=['status'])
        self.retry(RazorpayInvoice('inv_remote', '', 'expired'))
        self.assertEqual(reload(self.invoice).status, SubscriptionInvoice.Status.FAILED)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.PAYMENT_FAILED)

    def test_a_remote_invoice_that_is_partially_paid_is_recorded_as_failed_like_its_webhook(self):
        self.tenant.status = Tenant.Status.ACTIVE
        self.tenant.save(update_fields=['status'])
        self.retry(RazorpayInvoice('inv_remote', '', 'partially_paid', 'pay_part'))
        self.assertEqual(reload(self.invoice).status, SubscriptionInvoice.Status.FAILED)
        (payment,) = self.payments()
        self.assertEqual(payment.status, SubscriptionPayment.Status.FAILED)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.PAYMENT_FAILED)

    def test_a_retry_whose_invoice_was_bound_to_another_razorpay_id_meanwhile_changes_nothing(self):
        def bound_elsewhere_then_returns(customer_id, invoice):
            set_fields(invoice, status=SubscriptionInvoice.Status.ISSUED, razorpay_invoice_id='inv_ours')
            return RazorpayInvoice('inv_remote', '', 'paid', 'pay_77')

        with mock.patch(CREATE_INVOICE, side_effect=bound_elsewhere_then_returns):
            process_invoice_issuing()
        invoice = reload(self.invoice)
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.ISSUED)
        self.assertEqual(invoice.razorpay_invoice_id, 'inv_ours')
        self.assertIsNone(invoice.issue_claimed_at)
        self.assertEqual(self.payments(), [])

    def test_a_remote_invoice_still_awaiting_payment_is_just_issued(self):
        self.retry(RazorpayInvoice('inv_remote', '', 'issued'))
        self.assertEqual(reload(self.invoice).status, SubscriptionInvoice.Status.ISSUED)
        self.assertEqual(self.payments(), [])

    def test_the_same_payment_arriving_by_webhook_and_by_retry_is_recorded_once(self):
        self.post(invoice_payload('invoice.paid', 'inv_remote', receipt=str(self.invoice.pk), payment_id='pay_77'))
        # Put the invoice back as a sweep that had already claimed the draft would see it.
        set_fields(self.invoice, status=SubscriptionInvoice.Status.DRAFT, razorpay_invoice_id='', issue_claimed_at=None)
        self.retry(RazorpayInvoice('inv_remote', '', 'paid', 'pay_77'))
        self.assertEqual(len(self.payments()), 1)

    def test_a_webhook_that_lands_while_the_create_call_is_in_flight_is_not_undone(self):
        def create_then_paid_webhook(customer_id, invoice):
            self.post(invoice_payload('invoice.paid', 'inv_remote', receipt=str(invoice.pk)))
            # In production the webhook is another process on its own connection. Here the
            # test client shares ours and its middleware clears the tenant context on exit.
            set_tenant_context(invoice.tenant_id)
            return RazorpayInvoice('inv_remote', '', 'issued')  # the stale view our own call got back

        with mock.patch(CREATE_INVOICE, side_effect=create_then_paid_webhook):
            process_invoice_issuing()
        self.assertEqual(reload(self.invoice).status, SubscriptionInvoice.Status.PAID)
        self.assertEqual(len(self.payments()), 1)
