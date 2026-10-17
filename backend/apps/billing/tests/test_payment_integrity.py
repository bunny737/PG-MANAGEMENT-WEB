"""D3 payment integrity + D4 receipts: overpayment, Idempotency-Key, receipt
numbers, receipt PDF."""
import threading
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.billing import services
from apps.billing.models import Invoice, Payment, ReceiptCounter
from apps.core.tenancy import tenant_context
from apps.properties.models import Property
from apps.residents.models import Admission, Allocation, Resident

from .base import BillingAPITestCase


class PaymentIntegrityTests(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.prop = self.create_property(self.tenant)
        bed = self.create_bed(self.create_room(self.create_floor(self.prop)))
        self.resident = self.create_resident(self.prop, status=Resident.Status.RESERVED)
        self.check_in(self.resident, bed)
        self.invoice = self.create_invoice(self.resident, date(2026, 7, 1), total=Decimal('5000.00'))
        self.authenticate(self.owner)

    def post(self, amount, key=None):
        headers = {'HTTP_IDEMPOTENCY_KEY': key} if key else {}
        return self.client.post(reverse('payment-list'), {
            'invoice': str(self.invoice.id), 'amount': amount,
            'payment_date': '2026-07-05', 'payment_mode': 'cash',
        }, **headers)

    def test_overpayment_is_rejected(self):
        self.assertEqual(self.post('3000.00').status_code, 201)
        response = self.post('2500.00')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['amount'][0].code, 'overpayment')

    def test_idempotent_retry_returns_the_original_payment(self):
        first = self.post('5000.00', key='k-1')
        self.assertEqual(first.status_code, 201)
        # The invoice is now fully paid: a fresh POST would be rejected, but a
        # retry with the same key replays the original.
        retry = self.post('5000.00', key='k-1')
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry['Idempotent-Replayed'], 'true')
        self.assertEqual(retry.data['id'], first.data['id'])
        with tenant_context(self.tenant.id):
            self.assertEqual(Payment.objects.count(), 1)

    def test_key_reused_with_a_different_body_is_409(self):
        self.assertEqual(self.post('1000.00', key='k-2').status_code, 201)
        response = self.post('1500.00', key='k-2')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'IDEMPOTENCY_KEY_REUSED')

    def test_key_reused_with_any_changed_input_is_409(self):
        body = {
            'invoice': str(self.invoice.id), 'amount': '1000.00', 'payment_date': '2026-07-05',
            'payment_mode': 'cash', 'reference': 'TXN-1',
        }
        post = lambda **changes: self.client.post(  # noqa: E731
            reverse('payment-list'), {**body, **changes}, HTTP_IDEMPOTENCY_KEY='k-3',
        )
        self.assertEqual(post().status_code, 201)
        self.assertEqual(post(amount='1000').status_code, 200)  # same value, other spelling
        for changes in ({'payment_date': '2026-07-06'}, {'payment_mode': 'upi'}, {'reference': 'TXN-2'},
                        {'reference': ''}, {'payment_date': 'not-a-date'}):
            self.assertEqual(post(**changes).status_code, 409, changes)
        with tenant_context(self.tenant.id):
            self.assertEqual(Payment.objects.count(), 1)

    def test_keys_are_per_tenant(self):
        self.assertEqual(self.post('1000.00', key='shared').status_code, 201)
        other = self.create_tenant('Other')
        other_owner = self.create_owner(other, email='o2@example.com')
        prop = self.create_property(other)
        bed = self.create_bed(self.create_room(self.create_floor(prop)))
        resident = self.create_resident(prop, phone='9000000077', status=Resident.Status.RESERVED)
        self.check_in(resident, bed)
        invoice = self.create_invoice(resident, date(2026, 7, 1))
        self.authenticate(other_owner)
        response = self.client.post(reverse('payment-list'), {
            'invoice': str(invoice.id), 'amount': '1000.00', 'payment_date': '2026-07-05', 'payment_mode': 'cash',
        }, HTTP_IDEMPOTENCY_KEY='shared')
        self.assertEqual(response.status_code, 201)

    def test_receipt_numbers_are_sequential_per_tenant(self):
        first = self.post('1000.00').data['receipt_number']
        second = self.post('1000.00').data['receipt_number']
        self.assertEqual((first, second), ('RCT-000001', 'RCT-000002'))
        # A deleted payment's number is never reused.
        self.client.delete(reverse('payment-detail', args=[self.post('1000.00').data['id']]))
        self.assertEqual(self.post('1000.00').data['receipt_number'], 'RCT-000004')

    def test_payment_carries_recorder_and_resident_context(self):
        data = self.post('1000.00').data
        self.assertEqual(data['recorded_by'], self.owner.id)
        self.assertEqual(data['recorded_by_name'], 'Test')
        self.assertEqual(data['resident'], str(self.resident.id))
        self.assertIsNotNone(data['created_at'])

    def test_receipt_json_and_pdf(self):
        payment_id = self.post('1000.00').data['id']
        url = reverse('payment-receipt', args=[payment_id])
        data = self.client.get(url).data
        self.assertEqual(data['receipt_number'], 'RCT-000001')
        self.assertEqual(data['invoice_balance_due'], '4000.00')
        pdf = self.client.get(url, {'filetype': 'pdf'})
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        self.assertIn('receipt-RCT-000001.pdf', pdf['Content-Disposition'])


@skipUnlessDBFeature('has_select_for_update')
class ConcurrentOverpaymentTests(TransactionTestCase):
    """Two concurrent payments that each fit the balance but together exceed
    it: the invoice row lock lets exactly one through."""

    def _fixture_teardown(self):
        # Don't flush migration-seeded tables (see VacateConcurrencyTests);
        # tearDown removes exactly what this test created.
        pass

    def setUp(self):
        helper = BillingAPITestCase
        self.tenant = helper.create_tenant('Payment Concurrency Tenant')
        self.owner = helper.create_owner(self.tenant, email=f'{self._testMethodName}@concurrency.example.com')
        self.prop = helper.create_property(self.tenant)
        bed = helper.create_bed(helper.create_room(helper.create_floor(self.prop)))
        self.resident = helper.create_resident(self.prop, status=Resident.Status.RESERVED)
        helper.check_in(self.resident, bed)
        self.invoice = helper.create_invoice(self.resident, date(2026, 7, 1), total=Decimal('5000.00'))

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            Payment.objects.filter(invoice__resident=self.resident).delete()
            ReceiptCounter.objects.filter(tenant_id=self.tenant.id).delete()
            Invoice.objects.filter(resident=self.resident).delete()
            Allocation.objects.filter(resident=self.resident).delete()
            Admission.objects.filter(resident=self.resident).delete()
            Resident.objects.filter(pk=self.resident.pk).delete()
            Property.objects.filter(pk=self.prop.pk).delete()
            AuditLog.objects.filter(tenant_id=self.tenant.id).delete()
        self.owner.delete()
        self.tenant.delete()

    def test_only_one_of_two_racing_payments_succeeds(self):
        barrier = threading.Barrier(2)
        outcomes = []

        def attempt():
            try:
                with tenant_context(self.tenant.id):
                    barrier.wait(timeout=10)
                    services.record_payment(
                        invoice=self.invoice, amount=Decimal('3000.00'), payment_date=date(2026, 7, 5),
                        payment_mode='cash', actor=self.owner,
                    )
                outcomes.append('ok')
            except Exception as exc:  # noqa: BLE001 — the rejected one raises ValidationError
                outcomes.append(type(exc).__name__)
            finally:
                connection.close()

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(outcomes), ['ValidationError', 'ok'])
        with tenant_context(self.tenant.id):
            self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 1)
