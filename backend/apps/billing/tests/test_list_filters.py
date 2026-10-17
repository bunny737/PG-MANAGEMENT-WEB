"""D3 server-side list filters for invoices, payments and cash movements."""
from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse

from apps.billing.models import Invoice
from apps.core.periods import local_today
from apps.core.tenancy import tenant_context
from apps.residents.models import Resident

from .base import BillingAPITestCase


class InvoiceAndPaymentFilterTests(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.prop_a = self.create_property(self.tenant, name='A')
        self.prop_b = self.create_property(self.tenant, name='B')
        self.ravi = self._resident(self.prop_a, 'Ravi', '9000000001', '101')
        self.sita = self._resident(self.prop_b, 'Sita', '9000000002', '201')
        self.authenticate(self.owner)

        today = local_today()
        self.past_due = today - timedelta(days=5)
        self.jul_ravi = self.create_invoice(self.ravi, date(2026, 7, 1), due_date=self.past_due)
        self.aug_ravi = self.create_invoice(self.ravi, date(2026, 8, 1), due_date=today + timedelta(days=30))
        self.jul_sita = self.create_invoice(self.sita, date(2026, 7, 1), due_date=today + timedelta(days=30))
        self.draft = self.create_invoice(self.sita, date(2026, 8, 1), status=Invoice.Status.DRAFT)
        self.pay(self.jul_sita, Decimal('7000.00'), date(2026, 7, 5))      # fully paid
        self.pay(self.aug_ravi, Decimal('2000.00'), date(2026, 8, 3))      # partial

    def _resident(self, prop, name, phone, room_number):
        room = self.create_room(self.create_floor(prop), room_number=room_number)
        bed = self.create_bed(room, bed_number=f'{room_number}-A')
        resident = self.create_resident(prop, first_name=name, phone=phone, status=Resident.Status.RESERVED)
        self.check_in(resident, bed)
        return resident

    def ids(self, url, **params):
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, 200, response.data)
        return {row['id'] for row in response.data}

    def test_outstanding_alias_excludes_paid_and_draft(self):
        got = self.ids(reverse('invoice-list'), status='outstanding')
        self.assertEqual(got, {str(self.jul_ravi.id), str(self.aug_ravi.id)})

    def test_outstanding_action_matches_the_alias(self):
        response = self.client.get(reverse('invoice-outstanding'), {'property': str(self.prop_a.id)})
        self.assertEqual({row['id'] for row in response.data}, {str(self.jul_ravi.id), str(self.aug_ravi.id)})

    def test_overdue_alias(self):
        self.assertEqual(self.ids(reverse('invoice-list'), status='overdue'), {str(self.jul_ravi.id)})

    def test_comma_separated_statuses_and_unknown_status(self):
        got = self.ids(reverse('invoice-list'), status='paid,draft')
        self.assertEqual(got, {str(self.jul_sita.id), str(self.draft.id)})
        response = self.client.get(reverse('invoice-list'), {'status': 'pending'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['status'][0].code, 'invalid_status')

    def test_property_period_and_search(self):
        self.assertEqual(
            self.ids(reverse('invoice-list'), property=str(self.prop_b.id)),
            {str(self.jul_sita.id), str(self.draft.id)},
        )
        self.assertEqual(
            self.ids(reverse('invoice-list'), period='2026-07'),
            {str(self.jul_ravi.id), str(self.jul_sita.id)},
        )
        self.assertEqual(
            self.ids(reverse('invoice-list'), period='2026-07', status='outstanding'),
            {str(self.jul_ravi.id)},
        )
        self.assertEqual(
            self.ids(reverse('invoice-list'), search='sit'), {str(self.jul_sita.id), str(self.draft.id)},
        )
        self.assertEqual(self.client.get(reverse('invoice-list'), {'period': '2026-13'}).status_code, 400)

    def test_invoice_rows_carry_context_and_capped_allocated(self):
        response = self.client.get(reverse('invoice-detail', args=[self.aug_ravi.id]))
        self.assertEqual(response.data['resident_name'], 'Ravi')
        self.assertEqual(response.data['property'], str(self.prop_a.id))
        self.assertEqual(response.data['room_number'], '101')
        self.assertEqual(response.data['bed_number'], '101-A')
        self.assertEqual(response.data['capped_allocated'], '2000.00')

    def test_capped_allocated_never_exceeds_a_reduced_total(self):
        """A total cut below what was paid (credit after payment) caps it."""
        with tenant_context(self.tenant.id):
            self.jul_sita.line_items.create(
                tenant_id=self.tenant.id, line_type='discount', label='Credit', amount='-1000.00', order=5,
            )
        response = self.client.get(reverse('invoice-detail', args=[self.jul_sita.id]))
        self.assertEqual(response.data['total'], '6000.00')
        self.assertEqual(response.data['capped_allocated'], '6000.00')

    def test_payment_filters(self):
        url = reverse('payment-list')
        all_ids = self.ids(url)
        self.assertEqual(len(all_ids), 2)
        self.assertEqual(len(self.ids(url, month='2026-07')), 1)
        self.assertEqual(len(self.ids(url, **{'from': '2026-08-01', 'to': '2026-08-31'})), 1)
        self.assertEqual(len(self.ids(url, property=str(self.prop_b.id))), 1)
        self.assertEqual(len(self.ids(url, resident=str(self.ravi.id))), 1)
        self.assertEqual(len(self.ids(url, invoice__resident=str(self.ravi.id))), 1)  # legacy name
        row = self.client.get(url, {'resident': str(self.ravi.id)}).data[0]
        self.assertEqual(row['resident_name'], 'Ravi')
        self.assertEqual(row['room_number'], '101')
        self.assertTrue(row['receipt_number'] is None or row['receipt_number'].startswith('RCT-'))

    def test_cash_movements_sum_to_gross_receipts(self):
        response = self.client.get(reverse('cash-movements'), {'month': '2026-08'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total'], '2000.00')
        self.assertEqual(response.data['refunds_paid'], '0.00')
        self.assertEqual(
            sum(Decimal(row['amount']) for row in response.data['results']), Decimal(response.data['total'])
        )

    def test_cash_movements_unassigned_property_is_404_and_needs_view_finance(self):
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.prop_a)
        self.authenticate(manager)
        response = self.client.get(reverse('cash-movements'), {'property': str(self.prop_b.id)})
        self.assertEqual(response.status_code, 404)
        self.customize(manager, finance='off')
        self.authenticate(manager)
        self.assertEqual(self.client.get(reverse('cash-movements')).status_code, 403)

    def test_other_tenant_rows_never_appear(self):
        other = self.create_tenant('Other')
        other_prop = self.create_property(other, name='X')
        other_res = self._resident(other_prop, 'Zed', '9000000099', '301')
        self.create_invoice(other_res, date(2026, 7, 1))
        self.assertNotIn(
            str(other_prop.id),
            {row['property'] for row in self.client.get(reverse('invoice-list')).data},
        )
        self.assertEqual(self.ids(reverse('invoice-list'), property=str(other_prop.id)), set())
