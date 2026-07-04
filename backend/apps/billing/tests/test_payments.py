from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.residents.models import Resident

from .base import BillingAPITestCase

PERIOD = {'period_start': '2026-07-01', 'period_end': '2026-07-31', 'due_date': '2026-07-10'}


class PaymentTestsBase(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(
            self.floor, room_number='101', sharing_type=4, category='ac',
            rack_rate_with_food=Decimal('7000.00'), rack_rate_without_food=Decimal('5500.00'),
        )
        self.bed = self.create_bed(self.room, bed_number='101-A')
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.check_in(self.resident, self.bed)
        self.authenticate(self.owner)
        self.invoice = self._generate_and_issue()

    def _generate_and_issue(self, resident=None):
        resident = resident or self.resident
        generated = self.client.post(
            reverse('invoice-list'), {'resident': str(resident.id), **PERIOD}
        ).data
        issued = self.client.post(reverse('invoice-issue', args=[generated['id']]))
        return issued.data

    def _pay(self, invoice_id=None, **overrides):
        payload = {
            'invoice': invoice_id or self.invoice['id'], 'amount': '2000.00',
            'payment_date': '2026-07-05', 'payment_mode': 'upi',
        }
        payload.update(overrides)
        return self.client.post(reverse('payment-list'), payload)


class PaymentRecordingTests(PaymentTestsBase):
    def test_partial_payment_updates_status_and_balance(self):
        response = self._pay(amount='2000.00')

        self.assertEqual(response.status_code, 201, response.data)
        invoice = self.client.get(reverse('invoice-detail', args=[self.invoice['id']])).data
        self.assertEqual(invoice['status'], 'partially_paid')
        self.assertEqual(invoice['amount_paid'], '2000.00')
        self.assertEqual(invoice['balance_due'], '5000.00')

    def test_multiple_partial_payments_accumulate_to_paid(self):
        self._pay(amount='2000.00', payment_mode='upi')
        self._pay(amount='5000.00', payment_mode='cash', payment_date='2026-07-10')

        invoice = self.client.get(reverse('invoice-detail', args=[self.invoice['id']])).data
        self.assertEqual(invoice['status'], 'paid')
        self.assertEqual(invoice['amount_paid'], '7000.00')
        self.assertEqual(invoice['balance_due'], '0.00')

    def test_full_payment_marks_invoice_paid(self):
        response = self._pay(amount='7000.00')
        self.assertEqual(response.status_code, 201, response.data)

        invoice = self.client.get(reverse('invoice-detail', args=[self.invoice['id']])).data
        self.assertEqual(invoice['status'], 'paid')
        self.assertFalse(invoice['is_overdue'])

    def test_cannot_pay_a_draft_invoice(self):
        draft = self.client.post(
            reverse('invoice-list'),
            {'resident': str(self.resident.id), 'period_start': '2026-08-01',
             'period_end': '2026-08-31', 'due_date': '2026-08-10'},
        ).data

        response = self._pay(invoice_id=draft['id'])
        self.assertEqual(response.status_code, 400)
        self.assertIn('invoice', response.data)

    def test_cannot_overpay(self):
        response = self._pay(amount='9000.00')
        self.assertEqual(response.status_code, 400)
        self.assertIn('amount', response.data)

    def test_cannot_pay_an_already_fully_paid_invoice(self):
        self._pay(amount='7000.00')
        response = self._pay(amount='1.00')
        self.assertEqual(response.status_code, 400)
        self.assertIn('invoice', response.data)

    def test_payment_amount_must_be_positive(self):
        response = self._pay(amount='0.00')
        self.assertEqual(response.status_code, 400)
        self.assertIn('amount', response.data)

    def test_payment_recorded_is_audit_logged(self):
        self._pay(amount='2000.00')
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='payment.recorded').exists())

    def test_receipt_endpoint(self):
        payment = self._pay(amount='2000.00').data
        response = self.client.get(reverse('payment-receipt', args=[payment['id']]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['amount'], '2000.00')
        self.assertEqual(response.data['payment_mode'], 'upi')
        self.assertEqual(response.data['invoice_balance_due'], '5000.00')


class PaymentDeletionTests(PaymentTestsBase):
    def test_delete_payment_reverts_invoice_status(self):
        payment = self._pay(amount='7000.00').data
        response = self.client.delete(reverse('payment-detail', args=[payment['id']]))
        self.assertEqual(response.status_code, 204)

        invoice = self.client.get(reverse('invoice-detail', args=[self.invoice['id']])).data
        self.assertEqual(invoice['status'], 'issued')
        self.assertEqual(invoice['balance_due'], '7000.00')

    def test_delete_partial_payment_reverts_to_partially_paid(self):
        first = self._pay(amount='2000.00').data
        self._pay(amount='5000.00', payment_date='2026-07-10')

        self.client.delete(reverse('payment-detail', args=[first['id']]))

        invoice = self.client.get(reverse('invoice-detail', args=[self.invoice['id']])).data
        self.assertEqual(invoice['status'], 'partially_paid')
        self.assertEqual(invoice['balance_due'], '2000.00')

    def test_payment_deletion_is_audit_logged(self):
        payment = self._pay(amount='2000.00').data
        self.client.delete(reverse('payment-detail', args=[payment['id']]))
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='payment.deleted').exists())


class OutstandingDuesTests(PaymentTestsBase):
    def test_outstanding_lists_unpaid_and_partially_paid_invoices(self):
        second_resident = self.create_resident(self.property, phone='9000000009', status=Resident.Status.RESERVED)
        second_bed = self.create_bed(self.room, bed_number='101-B')
        self.check_in(second_resident, second_bed)
        fully_paid = self._generate_and_issue(resident=second_resident)
        self._pay(invoice_id=fully_paid['id'], amount='7000.00')
        self._pay(amount='2000.00')  # partial payment on self.invoice

        response = self.client.get(reverse('invoice-outstanding'))

        self.assertEqual(response.status_code, 200)
        ids = [inv['id'] for inv in response.data]
        self.assertIn(self.invoice['id'], ids)
        self.assertNotIn(fully_paid['id'], ids)


class PaymentPermissionTests(PaymentTestsBase):
    def test_receptionist_cannot_manage_payments(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        self.assertEqual(self.client.get(reverse('payment-list')).status_code, 403)
        self.assertEqual(self._pay().status_code, 403)

    def test_manager_scoped_to_assigned_properties(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        other_room = self.create_room(self.create_floor(other_property))
        other_resident = self.create_resident(other_property, phone='9000000008', status=Resident.Status.RESERVED)
        self.check_in(other_resident, self.create_bed(other_room))
        other_invoice = self._generate_and_issue(resident=other_resident)

        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        ok = self._pay(amount='2000.00')
        self.assertEqual(ok.status_code, 201, ok.data)

        blocked = self._pay(invoice_id=other_invoice['id'], amount='2000.00')
        self.assertEqual(blocked.status_code, 400)

    def test_payment_detail_is_tenant_scoped(self):
        payment = self._pay(amount='2000.00').data

        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')
        self.authenticate(other_owner)

        response = self.client.get(reverse('payment-detail', args=[payment['id']]))
        self.assertEqual(response.status_code, 404)
