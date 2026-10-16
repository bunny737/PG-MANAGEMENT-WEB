"""D0/D1 analytics: every figure reconciles with its drill-down list, the
permission matrix, redaction, YTD and the trend."""
from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.billing.tests.base import BillingAPITestCase
from apps.core.tenancy import tenant_context
from apps.expenses.models import Expense, ExpenseCategory
from apps.expenses.services import ensure_system_categories
from apps.residents.models import Resident

JULY = '2026-07'


class AnalyticsBase(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.prop = self.create_property(self.tenant, name='A')
        self.other = self.create_property(self.tenant, name='B')
        self.ravi = self._admit(self.prop, 'Ravi', '9000000001', '101')
        self.sita = self._admit(self.prop, 'Sita', '9000000002', '102')
        self.zed = self._admit(self.other, 'Zed', '9000000003', '201')

        # July invoices (prop A): Ravi 7000 fully paid, Sita 7000 (-500 discount) part paid.
        self.ravi_jul = self.create_invoice(self.ravi, date(2026, 7, 1), due_date=date(2026, 7, 10))
        self.sita_jul = self.create_invoice(self.sita, date(2026, 7, 1), discount=Decimal('500.00'),
                                            due_date=date(2026, 7, 10))
        self.ravi_jun = self.create_invoice(self.ravi, date(2026, 6, 1), due_date=date(2026, 6, 10))
        self.draft = self.create_invoice(self.sita, date(2026, 8, 1), status='draft')
        self.pay(self.ravi_jul, Decimal('7000.00'), date(2026, 7, 5))
        self.pay(self.sita_jul, Decimal('2000.00'), date(2026, 8, 3))   # paid in August
        self.pay(self.ravi_jun, Decimal('3000.00'), date(2026, 7, 20))  # June invoice, July cash
        # Property B, July: invoiced, unpaid.
        self.create_invoice(self.zed, date(2026, 7, 1), total=Decimal('4000.00'), due_date=date(2026, 7, 10))

        with tenant_context(self.tenant.id):
            ensure_system_categories(self.tenant.id)
            water = ExpenseCategory.objects.get(code='water')
            for amount, when, prop, deleted in (
                ('1500.00', date(2026, 7, 9), self.prop, False),
                ('700.00', date(2026, 7, 15), self.prop, True),     # soft-deleted
                ('400.00', date(2026, 7, 2), self.other, False),
                ('250.00', date(2026, 4, 2), self.prop, False),     # earlier in the FY
            ):
                Expense.objects.create(
                    tenant_id=self.tenant.id, property=prop, category=water, amount=Decimal(amount),
                    date=when, payment_mode='cash',
                    deleted_at=date(2026, 7, 16) if deleted else None,
                )
        self.authenticate(self.owner)

    def _admit(self, prop, name, phone, room_number):
        bed = self.create_bed(self.create_room(self.create_floor(prop, name=f'F{room_number}', order=int(room_number)),
                                               room_number=room_number), bed_number=f'{room_number}-A')
        resident = self.create_resident(prop, first_name=name, phone=phone, status=Resident.Status.RESERVED)
        self.check_in(resident, bed, security_deposit_amount=Decimal('2000.00'))
        return resident

    def summary(self, **params):
        response = self.client.get(reverse('analytics-summary'), params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def sum_rows(self, rows, field):
        return sum((Decimal(row[field]) for row in rows), Decimal('0.00'))


class SummaryFiguresTests(AnalyticsBase):
    def test_month_figures_for_one_property(self):
        data = self.summary(property=str(self.prop.id), month=JULY)
        finance = data['finance']
        self.assertEqual(finance['gross_receipts'], '10000.00')      # 7000 + 3000 dated July
        self.assertEqual(finance['refunds_paid'], '0.00')
        self.assertEqual(finance['cash_collected'], '10000.00')
        self.assertEqual(finance['period_invoiced'], '13500.00')     # 7000 + 6500, net of discount
        self.assertEqual(finance['period_collected'], '9000.00')     # 7000 + 2000 (paid in Aug, to date)
        self.assertEqual(finance['collection_rate'], 66.7)
        self.assertEqual(finance['period_outstanding'], '4500.00')
        self.assertEqual(finance['outstanding_total'], '8500.00')    # Sita 4500 + Ravi June 4000
        self.assertEqual(finance['overdue_total'], '8500.00')
        self.assertEqual(finance['residents_with_balance_count'], 2)
        self.assertEqual(finance['occupied_beds_with_balance_count'], 2)
        self.assertEqual(finance['deposits_held'], '4000.00')
        self.assertEqual(data['expenses']['expenses_paid'], '1500.00')
        self.assertEqual(data['cash_flow']['net_cash_flow'], '8500.00')
        self.assertEqual(data['occupancy']['occupied'], 2)
        self.assertEqual(data['timezones'], ['Asia/Kolkata'])
        self.assertEqual(data['redacted'], [])

    def test_all_properties_adds_up(self):
        data = self.summary(month=JULY)
        self.assertEqual(data['finance']['period_invoiced'], '17500.00')
        self.assertEqual(data['expenses']['expenses_paid'], '1900.00')
        self.assertIsNone(data['property'])

    def test_figures_reconcile_with_their_drill_downs(self):
        params = {'property': str(self.prop.id)}
        data = self.summary(month=JULY, **params)['finance']
        outstanding = self.client.get(reverse('invoice-list'), {**params, 'status': 'outstanding'}).data
        self.assertEqual(self.sum_rows(outstanding, 'balance_due'), Decimal(data['outstanding_total']))
        period_open = self.client.get(
            reverse('invoice-list'), {**params, 'period': JULY, 'status': 'outstanding'}
        ).data
        self.assertEqual(self.sum_rows(period_open, 'balance_due'), Decimal(data['period_outstanding']))
        period_rows = self.client.get(
            reverse('invoice-list'), {**params, 'period': JULY, 'status': 'issued,partially_paid,paid'}
        ).data
        self.assertEqual(self.sum_rows(period_rows, 'capped_allocated'), Decimal(data['period_collected']))
        self.assertEqual(self.sum_rows(period_rows, 'total'), Decimal(data['period_invoiced']))
        movements = self.client.get(reverse('cash-movements'), {**params, 'month': JULY}).data
        self.assertEqual(Decimal(movements['total']), Decimal(data['cash_collected']))
        self.assertEqual(self.sum_rows(movements['results'], 'amount'), Decimal(data['cash_collected']))
        expenses = self.client.get(reverse('expense-list'), {**params, 'month': JULY}).data
        self.assertEqual(
            self.sum_rows(expenses, 'amount'),
            Decimal(self.summary(month=JULY, **params)['expenses']['expenses_paid']),
        )

    def test_collection_rate_null_when_nothing_invoiced(self):
        data = self.summary(property=str(self.prop.id), month='2026-02')
        self.assertIsNone(data['finance']['collection_rate'])
        self.assertEqual(data['finance']['period_invoiced'], '0.00')

    def test_collection_rate_stays_at_most_100_after_a_post_payment_credit(self):
        with tenant_context(self.tenant.id):
            self.ravi_jul.line_items.create(
                tenant_id=self.tenant.id, line_type='discount', label='Credit', amount='-1000.00', order=9,
            )
        finance = self.summary(property=str(self.prop.id), month=JULY)['finance']
        self.assertEqual(finance['period_invoiced'], '12500.00')
        self.assertEqual(finance['period_collected'], '8000.00')   # Ravi capped at 6000
        self.assertLessEqual(finance['collection_rate'], 100)

    def test_ytd_uses_the_tenant_fiscal_year(self):
        data = self.summary(property=str(self.prop.id), month=JULY)
        self.assertEqual(str(data['ytd']['start']), '2026-04-01')
        self.assertEqual(data['expenses']['ytd_expenses_paid'], '1750.00')   # Apr 250 + Jul 1500
        self.tenant.fiscal_year_start_month = 7
        self.tenant.save(update_fields=['fiscal_year_start_month'])
        data = self.summary(property=str(self.prop.id), month=JULY)
        self.assertEqual(str(data['ytd']['start']), '2026-07-01')
        self.assertEqual(data['expenses']['ytd_expenses_paid'], '1500.00')

    def test_bad_month_and_unassigned_property(self):
        self.assertEqual(self.client.get(reverse('analytics-summary'), {'month': '7-2026'}).status_code, 400)
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.prop)
        self.authenticate(manager)
        response = self.client.get(reverse('analytics-summary'), {'property': str(self.other.id)})
        self.assertEqual(response.status_code, 404)
        # "All properties" for a manager covers only assigned ones.
        self.assertEqual(self.summary(month=JULY)['finance']['period_invoiced'], '13500.00')


class AnalyticsPermissionMatrixTests(AnalyticsBase):
    def staff(self, **levels):
        manager = self.create_manager(self.tenant, email=None)
        self.assign_staff(manager, self.prop)
        self.customize(manager, **levels)
        self.authenticate(manager)
        return manager

    def test_dashboard_and_finance_without_reports_gets_finance(self):
        self.staff(reports='off', expenses='off')
        data = self.summary(month=JULY)
        self.assertIsNotNone(data['finance'])
        self.assertEqual(set(data['redacted']), {'expenses', 'cash_flow'})

    def test_finance_without_dashboard_or_reports_is_403(self):
        self.staff(reports='off', dashboard='off')
        self.assertEqual(self.client.get(reverse('analytics-summary')).status_code, 403)
        self.assertEqual(self.client.get(reverse('analytics-trend')).status_code, 403)

    def test_reports_without_finance_sees_occupancy_and_expenses_only(self):
        self.staff(finance='off')
        data = self.summary(month=JULY)
        self.assertIsNone(data['finance'])
        self.assertIsNone(data['cash_flow'])
        self.assertIsNotNone(data['expenses'])
        self.assertIsNotNone(data['occupancy'])
        self.assertEqual(set(data['redacted']), {'finance', 'cash_flow'})

    def test_net_cash_flow_needs_both_permissions(self):
        self.staff(expenses='off')
        data = self.summary(month=JULY)
        self.assertIsNotNone(data['finance'])
        self.assertIsNone(data['cash_flow'])


class TrendTests(AnalyticsBase):
    def test_series_ends_at_the_requested_month(self):
        data = self.client.get(reverse('analytics-trend'),
                               {'property': str(self.prop.id), 'end': '2026-08', 'months': 3}).data
        self.assertEqual([row['month'] for row in data['series']], ['2026-06', '2026-07', '2026-08'])
        july = data['series'][1]
        self.assertEqual(july['finance']['cash_collected'], '10000.00')
        self.assertEqual(july['expenses']['expenses_paid'], '1500.00')
        self.assertEqual(july['cash_flow']['net_cash_flow'], '8500.00')

    def test_months_bounds(self):
        self.assertEqual(self.client.get(reverse('analytics-trend'), {'months': 0}).status_code, 400)
        self.assertEqual(self.client.get(reverse('analytics-trend'), {'months': 25}).status_code, 400)

    def test_redaction(self):
        receptionist_like = self.create_manager(self.tenant, email=None)
        self.assign_staff(receptionist_like, self.prop)
        self.customize(receptionist_like, finance='off')
        self.authenticate(receptionist_like)
        data = self.client.get(reverse('analytics-trend'), {'end': '2026-07', 'months': 2}).data
        self.assertEqual(set(data['redacted']), {'finance', 'cash_flow'})
        self.assertTrue(all(row['finance'] is None for row in data['series']))


class ExportAdditionsTests(AnalyticsBase):
    def test_cash_flow_statement(self):
        response = self.client.get(reverse('export-pnl'), {'property': str(self.prop.id), 'month': JULY})
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Net cash flow,8500.00', body)
        self.assertIn('Expense: Water,1500.00', body)

    def test_cash_flow_statement_needs_finance_and_expenses(self):
        manager = self.create_manager(self.tenant, email=None)
        self.assign_staff(manager, self.prop)
        self.customize(manager, expenses='off')
        self.authenticate(manager)
        self.assertEqual(self.client.get(reverse('export-pnl')).status_code, 403)

    def test_month_filter_on_payment_export_and_xlsx(self):
        csv = self.client.get(reverse('export-payments'), {'month': '2026-08'}).content.decode()
        self.assertEqual(len(csv.strip().splitlines()), 2)  # header + Sita's August payment
        xlsx = self.client.get(reverse('export-expenses'), {'filetype': 'xlsx', 'month': JULY})
        self.assertEqual(xlsx.status_code, 200)
        self.assertTrue(xlsx.content.startswith(b'PK'))
