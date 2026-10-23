"""D6 resident finance block + D3 resident list filters."""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse

from apps.billing.tests.base import BillingAPITestCase
from apps.core.periods import local_today, month_key, month_start
from apps.residents.models import Resident


class ResidentFinanceBlockTests(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.prop = self.create_property(self.tenant)
        bed = self.create_bed(self.create_room(self.create_floor(self.prop)))
        self.resident = self.create_resident(self.prop, first_name='Ravi', status=Resident.Status.RESERVED)
        self.check_in(self.resident, bed)
        self.today = local_today()
        self.month = month_start(self.today)
        self.url = reverse('resident-detail', args=[self.resident.id])
        self.authenticate(self.owner)

    def finance(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.data['finance']

    def test_no_invoice_yet(self):
        current = self.finance()['current_period']
        self.assertEqual(current['period'], month_key(self.month))
        self.assertEqual(current['status'], 'no_invoice')
        self.assertEqual(current['invoices'], [])
        self.assertFalse(current['has_draft'])

    def test_draft_is_flagged_but_not_owed(self):
        self.create_invoice(self.resident, self.month, status='draft')
        finance = self.finance()
        self.assertEqual(finance['current_period']['status'], 'no_invoice')
        self.assertTrue(finance['current_period']['has_draft'])
        self.assertEqual(finance['outstanding_total'], '0.00')

    def test_partial_payment_and_prior_arrears(self):
        previous = month_start(self.month - timedelta(days=1))
        self.create_invoice(self.resident, previous, total=Decimal('6000.00'),
                            due_date=self.today - timedelta(days=3))
        current = self.create_invoice(self.resident, self.month, due_date=self.today + timedelta(days=10))
        self.pay(current, Decimal('2500.00'), self.today)
        finance = self.finance()
        period = finance['current_period']
        self.assertEqual((period['total'], period['paid'], period['balance']), ('7000.00', '2500.00', '4500.00'))
        self.assertEqual(period['status'], 'partially_paid')
        self.assertEqual(finance['outstanding_total'], '10500.00')
        self.assertEqual(finance['prior_outstanding'], '6000.00')
        self.assertEqual(finance['overdue_total'], '6000.00')
        self.assertEqual(finance['last_payment_date'], self.today)

    def test_paid(self):
        invoice = self.create_invoice(self.resident, self.month, due_date=self.today + timedelta(days=5))
        self.pay(invoice, Decimal('7000.00'), self.today)
        self.assertEqual(self.finance()['current_period']['status'], 'paid')

    def test_redacted_without_view_finance(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.prop)
        self.authenticate(receptionist)
        data = self.client.get(self.url).data
        self.assertIsNone(data['finance'])
        self.assertEqual(data['redacted'], ['finance'])

    def test_finance_needs_view_resident_profile_to_enter(self):
        """view_finance alone is not an entry permission for resident detail."""
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.prop)
        self.customize(manager, tenants='off', finance='view')
        self.authenticate(manager)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_view_resident_profile_and_finance_without_properties_gets_the_block(self):
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.prop)
        self.customize(manager, properties='off', tenants='view', finance='view')
        self.authenticate(manager)
        data = self.client.get(self.url).data
        self.assertIsNotNone(data['finance'])
        self.assertEqual(data['redacted'], [])

    def test_list_has_no_finance_block(self):
        row = self.client.get(reverse('resident-list')).data[0]
        self.assertNotIn('finance', row)


class ResidentListFilterTests(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.prop = self.create_property(self.tenant)
        self.create_resident(self.prop, first_name='Ravi', last_name='Kumar', phone='9000000001',
                             status=Resident.Status.ACTIVE)
        self.create_resident(self.prop, first_name='Sita', phone='9000000002',
                             status=Resident.Status.NOTICE_PERIOD)
        self.create_resident(self.prop, first_name='Lead', phone='9000000003')
        self.authenticate(self.owner)

    def names(self, **params):
        return sorted(row['first_name'] for row in self.client.get(reverse('resident-list'), params).data)

    def test_status_list_and_search(self):
        self.assertEqual(self.names(status='active,notice_period'), ['Ravi', 'Sita'])
        self.assertEqual(self.names(search='kumar'), ['Ravi'])
        self.assertEqual(self.names(search='0000003'), ['Lead'])
        self.assertEqual(self.names(search='ravi kum'), ['Ravi'])
        response = self.client.get(reverse('resident-list'), {'status': 'gone'})
        self.assertEqual(response.data['status'][0].code, 'invalid_status')
