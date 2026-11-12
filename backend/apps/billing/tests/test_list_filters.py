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

    def test_advance_adjustment_filter_and_cash_movements_composition(self):
        # Create an admission in July with 20,000 advance (UPI) + 5,000 deposit (cash)
        room = self.create_room(
            self.create_floor(self.prop_a, name='First Floor', order=1),
            room_number='102', rack_rate_with_food=Decimal('10000.00'),
        )
        bed = self.create_bed(room, bed_number='102-A')
        r3 = self.create_resident(self.prop_a, first_name='Kiran', phone='9000000003', status=Resident.Status.RESERVED)
        self.client.post(reverse('admission-list'), {
            'resident': str(r3.id),
            'bed': str(bed.id),
            'joining_date': '2026-07-01',
            'billing_mode': 'monthly',
            'food_preference': 'with_food',
            'advance_amount': '20000.00',
            'advance_collected_date': '2026-07-01',
            'advance_mode': 'upi',
            'security_deposit_amount': '5000.00',
            'security_deposit_agreed': '5000.00',
            'security_deposit_collected_date': '2026-07-01',
            'security_deposit_mode': 'cash',
        })
        jul_inv = self.client.post(reverse('invoice-list'), {
            'resident': str(r3.id),
            'period_start': '2026-07-01', 'period_end': '2026-07-31', 'due_date': '2026-07-10',
        }).data
        self.client.post(reverse('invoice-issue', args=[jul_inv['id']]))
        aug_inv = self.client.post(reverse('invoice-list'), {
            'resident': str(r3.id),
            'period_start': '2026-08-01', 'period_end': '2026-08-31', 'due_date': '2026-08-10',
        }).data
        self.client.post(reverse('invoice-issue', args=[aug_inv['id']]))
        adj = self.client.post(
            reverse('invoice-adjust-advance', args=[aug_inv['id']]),
            {'amount': '4000.00', 'adjustment_date': '2026-08-04'},
        ).data

        # Payment filters keep advance adjustments distinct even though payment_mode on row is 'upi'
        url = reverse('payment-list')
        self.assertEqual(len(self.ids(url, resident=str(r3.id), payment_mode='advance_adjustment')), 2)
        self.assertEqual(self.ids(url, resident=str(r3.id), payment_mode='upi'), set())
        self.assertEqual(len(self.ids(url, resident=str(r3.id), is_advance_adjustment='true')), 2)
        self.assertEqual(self.ids(url, resident=str(r3.id), is_advance_adjustment='false'), set())
        self.assertEqual(self.client.get(url, {'payment_mode': 'invalid'}).status_code, 400)

        # July cash movements include admission_advance (20,000) + deposit (5,000), not 10,000 adjustment.
        jul_mov = self.client.get(reverse('cash-movements'), {'property': str(self.prop_a.id), 'month': '2026-07'}).data
        self.assertEqual(jul_mov['gross_receipts'], '25000.00')
        self.assertEqual(jul_mov['advance_adjustments_total'], '10000.00')
        self.assertEqual(jul_mov['refunds_paid'], '0.00')
        self.assertEqual(jul_mov['total'], '25000.00')
        self.assertEqual({row['type'] for row in jul_mov['results']}, {'admission_advance', 'deposit'})

        # August cash movements exclude the ₹4,000 advance adjustment (only Ravi's ₹2,000 cash payment counts).
        aug_mov = self.client.get(reverse('cash-movements'), {'property': str(self.prop_a.id), 'month': '2026-08'}).data
        self.assertEqual(aug_mov['gross_receipts'], '2000.00')
        self.assertEqual(aug_mov['advance_adjustments_total'], '4000.00')
        self.assertEqual(aug_mov['total'], '2000.00')
        self.assertNotIn(adj['id'], {row['id'] for row in aug_mov['results']})

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
