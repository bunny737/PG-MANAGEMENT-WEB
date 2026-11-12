from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.residents.models import Admission, Resident

from apps.billing.models import Payment

from .base import BillingAPITestCase

PERIOD = {'period_start': '2026-07-01', 'period_end': '2026-07-31', 'due_date': '2026-07-10'}


def _lines_by_type(invoice_data):
    return {li['line_type']: li for li in invoice_data['line_items']}


class InvoiceGenerationTests(BillingAPITestCase):
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
        self.check_in(self.resident, self.bed)  # contracted 7000, with food
        self.authenticate(self.owner)

    def _generate(self, resident=None, **overrides):
        payload = {'resident': str((resident or self.resident).id), **PERIOD}
        payload.update(overrides)
        return self.client.post(reverse('invoice-list'), payload)

    def test_generation_creates_accommodation_line_from_contracted_rent(self):
        response = self._generate()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['status'], 'draft')
        lines = _lines_by_type(response.data)
        self.assertEqual(lines['accommodation']['amount'], '7000.00')
        self.assertIn('Accommodation + Food (Monthly)', lines['accommodation']['label'])
        self.assertEqual(response.data['total'], '7000.00')

    def test_without_food_uses_without_food_rate_and_label(self):
        resident = self.create_resident(self.property, phone='9000000002', status=Resident.Status.RESERVED)
        bed = self.create_bed(self.room, bed_number='101-B')
        self.check_in(
            resident, bed, food_preference=Admission.FoodPreference.WITHOUT_FOOD,
            contracted_rent=Decimal('5500.00'),
        )

        response = self._generate(resident=resident)

        lines = _lines_by_type(response.data)
        self.assertEqual(lines['accommodation']['amount'], '5500.00')
        self.assertIn('Accommodation (Monthly)', lines['accommodation']['label'])
        self.assertNotIn('Food', lines['accommodation']['label'])

    def test_first_invoice_uses_manual_partial_month_amount(self):
        resident = self.create_resident(self.property, phone='9000000003', status=Resident.Status.RESERVED)
        bed = self.create_bed(self.room, bed_number='101-C')
        self.check_in(
            resident, bed, first_month_billing_amount=Decimal('3500.00'),
            first_month_billing_note='Partial month — joined 15th',
        )

        response = self._generate(resident=resident)

        lines = _lines_by_type(response.data)
        self.assertEqual(lines['accommodation']['amount'], '3500.00')
        self.assertIn('Partial month', lines['accommodation']['label'])

    def test_fixed_discount_is_a_negative_line(self):
        self.create_discount(self.resident, discount_value=Decimal('500.00'), valid_from=date(2026, 7, 1))

        response = self._generate()

        lines = _lines_by_type(response.data)
        self.assertEqual(lines['discount']['amount'], '-500.00')
        self.assertEqual(response.data['total'], '6500.00')

    def test_percentage_discount_is_computed_on_contracted_rent(self):
        self.create_discount(
            self.resident, discount_type='percentage', discount_value=Decimal('10'),
            valid_from=date(2026, 7, 1),
        )

        response = self._generate()

        lines = _lines_by_type(response.data)
        self.assertEqual(lines['discount']['amount'], '-700.00')  # 10% of 7000
        self.assertEqual(response.data['total'], '6300.00')

    def test_temporary_allocation_is_still_billed_at_contracted_rent(self):
        # invariant 3: temp room rack rate is irrelevant.
        room_b = self.create_room(
            self.floor, room_number='201', sharing_type=2, category='ac',
            rack_rate_with_food=Decimal('10000.00'), rack_rate_without_food=Decimal('8000.00'),
        )
        bed_b = self.create_bed(room_b, bed_number='201-A')
        self.client.post(reverse('transfer-list'), {
            'resident': str(self.resident.id), 'new_bed': str(bed_b.id),
            'transfer_date': '2026-07-05', 'is_temporary': True,
        })

        response = self._generate()

        lines = _lines_by_type(response.data)
        self.assertEqual(lines['accommodation']['amount'], '7000.00')  # not 10000

    def test_two_residents_same_room_get_their_own_discount(self):
        # invariant 4: different discounts for residents in the same room.
        second = self.create_resident(self.property, phone='9000000004', status=Resident.Status.RESERVED)
        second_bed = self.create_bed(self.room, bed_number='101-D')
        self.check_in(second, second_bed)
        self.create_discount(self.resident, discount_value=Decimal('500.00'), valid_from=date(2026, 7, 1))
        self.create_discount(second, discount_type='percentage', discount_value=Decimal('10'),
                             valid_from=date(2026, 7, 1))

        first = _lines_by_type(self._generate().data)
        other = _lines_by_type(self._generate(resident=second).data)

        self.assertEqual(first['discount']['amount'], '-500.00')
        self.assertEqual(other['discount']['amount'], '-700.00')

    def test_duplicate_invoice_for_same_period_is_rejected(self):
        self._generate()
        response = self._generate()
        self.assertEqual(response.status_code, 400)
        self.assertIn('period_start', response.data)

    def test_cannot_invoice_a_non_active_resident(self):
        reserved = self.create_resident(self.property, phone='9000000005', status=Resident.Status.RESERVED)
        response = self._generate(resident=reserved)
        self.assertEqual(response.status_code, 400)
        self.assertIn('resident', response.data)

    def test_generation_is_audit_logged(self):
        self._generate()
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='invoice.generated').exists())


class InvoiceLifecycleTests(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(
            self.floor, sharing_type=4, category='ac',
            rack_rate_with_food=Decimal('7000.00'), rack_rate_without_food=Decimal('5500.00'),
        )
        self.bed = self.create_bed(self.room, bed_number='101-A')
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.check_in(self.resident, self.bed)
        self.authenticate(self.owner)

    def _generate(self, **overrides):
        payload = {'resident': str(self.resident.id), **PERIOD}
        payload.update(overrides)
        return self.client.post(reverse('invoice-list'), payload).data

    def test_issue_sets_status_and_issue_date(self):
        invoice = self._generate()
        response = self.client.post(reverse('invoice-issue', args=[invoice['id']]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'issued')
        self.assertEqual(response.data['issue_date'], date.today().isoformat())

    def test_is_overdue_is_derived_from_due_date(self):
        past = (date.today() - timedelta(days=5)).isoformat()
        invoice = self._generate(due_date=past)
        response = self.client.post(reverse('invoice-issue', args=[invoice['id']]))
        self.assertTrue(response.data['is_overdue'])
        self.assertEqual(response.data['status'], 'issued')  # overdue is not stored

    def test_add_edit_and_remove_line_item_updates_total(self):
        invoice = self._generate()
        add = self.client.post(reverse('invoice-add-line-item', args=[invoice['id']]),
                               {'line_type': 'electricity', 'label': 'Electricity', 'amount': '300.00'})
        self.assertEqual(add.status_code, 201, add.data)
        self.assertEqual(add.data['total'], '7300.00')

        line_id = next(li['id'] for li in add.data['line_items'] if li['line_type'] == 'electricity')
        edit = self.client.patch(reverse('invoice-modify-line-item', args=[invoice['id'], line_id]),
                                 {'amount': '400.00'})
        self.assertEqual(edit.data['total'], '7400.00')

        remove = self.client.delete(reverse('invoice-modify-line-item', args=[invoice['id'], line_id]))
        self.assertEqual(remove.data['total'], '7000.00')

    def test_penalty_can_be_added_as_a_manual_line(self):
        invoice = self._generate()
        response = self.client.post(reverse('invoice-add-line-item', args=[invoice['id']]),
                                    {'line_type': 'penalty', 'label': 'Late fee', 'amount': '200.00'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['total'], '7200.00')

    def test_issued_invoice_cannot_be_modified_or_deleted(self):
        invoice = self._generate()
        self.client.post(reverse('invoice-issue', args=[invoice['id']]))

        add = self.client.post(reverse('invoice-add-line-item', args=[invoice['id']]),
                               {'line_type': 'electricity', 'label': 'E', 'amount': '1.00'})
        self.assertEqual(add.status_code, 400)
        self.assertEqual(self.client.delete(reverse('invoice-detail', args=[invoice['id']])).status_code, 400)

    def test_draft_invoice_can_be_deleted(self):
        invoice = self._generate()
        response = self.client.delete(reverse('invoice-detail', args=[invoice['id']]))
        self.assertEqual(response.status_code, 204)

    def test_due_date_editable_while_draft(self):
        invoice = self._generate()
        response = self.client.patch(reverse('invoice-detail', args=[invoice['id']]),
                                     {'due_date': '2026-07-20'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['due_date'], '2026-07-20')


class InvoiceBulkAndPermissionTests(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(
            self.floor, sharing_type=4, category='ac',
            rack_rate_with_food=Decimal('7000.00'), rack_rate_without_food=Decimal('5500.00'),
        )

    def _active_resident(self, phone, bed_number):
        resident = self.create_resident(self.property, phone=phone, status=Resident.Status.RESERVED)
        self.check_in(resident, self.create_bed(self.room, bed_number=bed_number))
        return resident

    def test_bulk_generate_covers_active_residents_and_skips_others(self):
        self._active_resident('9000000001', '101-A')
        self._active_resident('9000000002', '101-B')
        self.create_resident(self.property, phone='9000000003', status=Resident.Status.RESERVED)  # not checked in
        self.authenticate(self.owner)

        response = self.client.post(reverse('invoice-bulk-generate'), {
            'property': str(self.property.id), **PERIOD,
        })

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['created'], 2)

        # Running again is idempotent — everyone's already invoiced for the period.
        again = self.client.post(reverse('invoice-bulk-generate'), {
            'property': str(self.property.id), **PERIOD,
        })
        self.assertEqual(again.data['created'], 0)

    def test_receptionist_cannot_manage_invoices(self):
        self._active_resident('9000000001', '101-A')
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        self.assertEqual(self.client.get(reverse('invoice-list')).status_code, 403)

    def test_manager_scoped_to_assigned_properties(self):
        mine = self._active_resident('9000000001', '101-A')
        other_property = self.create_property(self.tenant, name='Other Property')
        other_room = self.create_room(self.create_floor(other_property))
        other_resident = self.create_resident(other_property, phone='9000000002', status=Resident.Status.RESERVED)
        self.check_in(other_resident, self.create_bed(other_room))

        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        # can generate for assigned resident
        ok = self.client.post(reverse('invoice-list'), {'resident': str(mine.id), **PERIOD})
        self.assertEqual(ok.status_code, 201, ok.data)

        # cannot generate for unassigned property's resident
        blocked = self.client.post(reverse('invoice-list'), {'resident': str(other_resident.id), **PERIOD})
        self.assertEqual(blocked.status_code, 400)

    def test_invoice_detail_is_tenant_scoped(self):
        resident = self._active_resident('9000000001', '101-A')
        self.authenticate(self.owner)
        invoice = self.client.post(reverse('invoice-list'), {'resident': str(resident.id), **PERIOD}).data

        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')
        self.authenticate(other_owner)
        response = self.client.get(reverse('invoice-detail', args=[invoice['id']]))
        self.assertEqual(response.status_code, 404)


class AdvanceAppliedToFirstInvoiceTests(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(self.floor, rack_rate_with_food=Decimal('7000.00'))
        self.bed = self.create_bed(self.room)
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.authenticate(self.owner)

    def _admit(self, advance, **kwargs):
        self.check_in(
            self.resident, self.bed, advance_amount=Decimal(advance),
            advance_collected_date=date(2026, 7, 1), advance_mode=Admission.AdvanceMode.UPI,
            **kwargs,
        )

    def _generate_and_issue(self, **period):
        payload = {'resident': str(self.resident.id), **{**PERIOD, **period}}
        invoice = self.client.post(reverse('invoice-list'), payload).data
        return self.client.post(reverse('invoice-issue', args=[invoice['id']])).data

    def _refresh_admission(self):
        with tenant_context(self.tenant.id):
            return Admission.objects.get(resident=self.resident)

    def test_advance_equal_to_rent_pays_the_first_invoice(self):
        self._admit('7000.00')

        invoice = self._generate_and_issue()

        self.assertEqual(invoice['status'], 'paid')
        with tenant_context(self.tenant.id):
            payment = Payment.objects.get(invoice_id=invoice['id'])
        self.assertEqual(payment.amount, Decimal('7000.00'))
        self.assertEqual(payment.payment_mode, 'upi')
        self.assertTrue(payment.is_advance_adjustment)
        self.assertEqual(payment.payment_source, 'advance_adjustment')
        self.assertEqual(payment.payment_date, date(2026, 7, 1))
        adm = self._refresh_admission()
        self.assertEqual(adm.advance_applied_amount, Decimal('7000.00'))
        self.assertTrue(adm.first_invoice_advance_settled)

    def test_opening_advance_can_remain_held_after_first_invoice(self):
        self._admit('7000.00', auto_apply_advance_to_first_invoice=False)

        invoice = self._generate_and_issue()

        self.assertEqual(invoice['status'], 'issued')
        with tenant_context(self.tenant.id):
            self.assertFalse(Payment.objects.filter(invoice_id=invoice['id']).exists())
        admission = self._refresh_admission()
        self.assertTrue(admission.first_invoice_advance_settled)
        self.assertEqual(admission.advance_applied_amount, Decimal('0.00'))
        self.assertEqual(admission.advance_refundable, Decimal('7000.00'))

    def test_smaller_advance_leaves_invoice_partially_paid(self):
        self._admit('3000.00')

        invoice = self._generate_and_issue()

        self.assertEqual(invoice['status'], 'partially_paid')
        self.assertEqual(self._refresh_admission().advance_refundable, Decimal('0.00'))

    def test_surplus_advance_is_capped_and_kept_for_refund(self):
        self._admit('14000.00')  # two months upfront

        invoice = self._generate_and_issue()

        self.assertEqual(invoice['status'], 'paid')
        admission = self._refresh_admission()
        self.assertEqual(admission.advance_applied_amount, Decimal('7000.00'))
        self.assertEqual(admission.advance_refundable, Decimal('7000.00'))

    def test_second_invoice_gets_no_advance(self):
        self._admit('14000.00')
        self._generate_and_issue()

        second = self._generate_and_issue(
            period_start='2026-08-01', period_end='2026-08-31', due_date='2026-08-10',
        )

        self.assertEqual(second['status'], 'issued')
        with tenant_context(self.tenant.id):
            self.assertFalse(Payment.objects.filter(invoice_id=second['id']).exists())

    def test_no_advance_means_no_payment(self):
        self._admit('0.00')

        invoice = self._generate_and_issue()

        self.assertEqual(invoice['status'], 'issued')
        with tenant_context(self.tenant.id):
            self.assertFalse(Payment.objects.filter(invoice_id=invoice['id']).exists())

    def test_advance_is_not_applied_a_second_time(self):
        from apps.billing.models import Invoice
        from apps.billing.services import apply_advance_to_first_invoice

        self._admit('14000.00')
        invoice = self._generate_and_issue()
        self.assertEqual(self._refresh_admission().advance_applied_amount, Decimal('7000.00'))

        # e.g. a racing second `issue` that got past the "first issued" check.
        with tenant_context(self.tenant.id):
            again = apply_advance_to_first_invoice(
                invoice=Invoice.objects.get(pk=invoice['id']), actor=self.owner,
            )
            self.assertEqual(Payment.objects.filter(invoice_id=invoice['id']).count(), 1)
        self.assertIsNone(again)
        self.assertEqual(self._refresh_admission().advance_applied_amount, Decimal('7000.00'))

    def test_deleting_the_advance_payment_releases_the_advance_and_does_not_retrigger_auto_apply(self):
        self._admit('14000.00')
        invoice = self._generate_and_issue()
        with tenant_context(self.tenant.id):
            payment = Payment.objects.get(invoice_id=invoice['id'])

        response = self.client.delete(reverse('payment-detail', args=[payment.id]))

        self.assertEqual(response.status_code, 204)
        admission = self._refresh_admission()
        self.assertEqual(admission.advance_applied_amount, Decimal('0.00'))
        self.assertEqual(admission.advance_refundable, Decimal('14000.00'))
        self.assertTrue(admission.first_invoice_advance_settled)

        # Second invoice issued after deletion must NOT auto-apply advance again.
        second = self._generate_and_issue(
            period_start='2026-08-01', period_end='2026-08-31', due_date='2026-08-10',
        )
        self.assertEqual(second['status'], 'issued')
        self.assertEqual(self._refresh_admission().advance_applied_amount, Decimal('0.00'))

    def test_deleting_an_ordinary_payment_leaves_the_advance_alone(self):
        self._admit('3000.00')
        invoice = self._generate_and_issue()
        ordinary = self.client.post(reverse('payment-list'), {
            'invoice': invoice['id'], 'amount': '1000.00',
            'payment_date': '2026-07-05', 'payment_mode': 'cash',
        })
        self.assertEqual(ordinary.status_code, 201, ordinary.data)

        self.client.delete(reverse('payment-detail', args=[ordinary.data['id']]))

        self.assertEqual(self._refresh_admission().advance_applied_amount, Decimal('3000.00'))


class HeldAdvanceAdjustmentTests(BillingAPITestCase):
    """Explicit 'Adjust from advance' lifecycle: worked ₹10k/₹20k/₹5k scenarios,
    partial & multi-invoice drawdowns, error guards, reversal, blank-mode source
    presentation, permissions, timeline, and idempotency."""

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.room = self.create_room(
            self.create_floor(self.property), room_number='101', sharing_type=2, category='ac',
            rack_rate_with_food=Decimal('10000.00'),
        )
        self.bed = self.create_bed(self.room, bed_number='101-A')
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.authenticate(self.owner)

    def _admit_via_api(self, *, advance='20000.00', deposit='5000.00', mode='upi'):
        resp = self.client.post(reverse('admission-list'), {
            'resident': str(self.resident.id),
            'bed': str(self.bed.id),
            'joining_date': '2026-07-01',
            'billing_mode': 'monthly',
            'food_preference': 'with_food',
            'advance_amount': advance,
            'advance_collected_date': '2026-07-01',
            'advance_mode': mode,
            'security_deposit_amount': deposit,
            'security_deposit_agreed': deposit,
            'security_deposit_collected_date': '2026-07-01',
            'security_deposit_mode': 'cash',
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data

    def _generate_and_issue(self, start, end, due):
        inv = self.client.post(reverse('invoice-list'), {
            'resident': str(self.resident.id),
            'period_start': start, 'period_end': end, 'due_date': due,
        }).data
        return self.client.post(reverse('invoice-issue', args=[inv['id']])).data

    def _adjust(self, invoice_id, amount, adjustment_date='2026-09-05', note='', key=None):
        headers = {'HTTP_IDEMPOTENCY_KEY': key} if key else {}
        return self.client.post(
            reverse('invoice-adjust-advance', args=[invoice_id]),
            {'amount': amount, 'adjustment_date': adjustment_date, 'note': note},
            **headers,
        )

    def _admission(self):
        with tenant_context(self.tenant.id):
            return Admission.objects.get(resident=self.resident)

    def test_worked_example_paths_a_b_and_c(self):
        # ₹10,000 monthly rent, ₹20,000 advance, ₹5,000 deposit
        self._admit_via_api(advance='20000.00', deposit='5000.00')
        jul = self._generate_and_issue('2026-07-01', '2026-07-31', '2026-07-10')
        self.assertEqual(jul['status'], 'paid')
        adm = self._admission()
        self.assertEqual(adm.advance_applied_amount, Decimal('10000.00'))
        self.assertEqual(adm.advance_refundable, Decimal('10000.00'))

        # August & September invoices stay issued; advance is NOT auto-applied.
        aug = self._generate_and_issue('2026-08-01', '2026-08-31', '2026-08-10')
        sep = self._generate_and_issue('2026-09-01', '2026-09-30', '2026-09-10')
        self.assertEqual(aug['status'], 'issued')
        self.assertEqual(sep['status'], 'issued')

        # Path C: partial adjustment ₹4,000 on Aug + ₹6,000 on Sep, then delete Sep -> restores ₹6,000
        adj_aug = self._adjust(aug['id'], '4000.00', '2026-08-05', note='Partial aug')
        self.assertEqual(adj_aug.status_code, 201, adj_aug.data)
        self.assertTrue(adj_aug.data['is_advance_adjustment'])
        self.assertEqual(adj_aug.data['payment_source'], 'advance_adjustment')
        self.assertEqual(adj_aug.data['payment_source_label'], 'Advance Adjustment')
        self.assertEqual(adj_aug.data['historical_collection_mode'], 'upi')

        adj_sep = self._adjust(sep['id'], '6000.00', '2026-09-05', note='Partial sep')
        self.assertEqual(adj_sep.status_code, 201, adj_sep.data)
        adm = self._admission()
        self.assertEqual(adm.advance_applied_amount, Decimal('20000.00'))
        self.assertEqual(adm.advance_refundable, Decimal('0.00'))

        # Pay Aug balance ₹6,000 normally and reverse Sep's ₹6,000 adjustment.
        self.client.post(reverse('payment-list'), {
            'invoice': aug['id'], 'amount': '6000.00',
            'payment_date': '2026-08-06', 'payment_mode': 'cash',
        })
        del_resp = self.client.delete(reverse('payment-detail', args=[adj_sep.data['id']]))
        self.assertEqual(del_resp.status_code, 204)
        adm = self._admission()
        self.assertEqual(adm.advance_applied_amount, Decimal('14000.00'))
        self.assertEqual(adm.advance_refundable, Decimal('6000.00'))
        sep_refreshed = self.client.get(reverse('invoice-detail', args=[sep['id']])).data
        self.assertEqual(sep_refreshed['status'], 'issued')
        self.assertEqual(sep_refreshed['balance_due'], '10000.00')

        # Give notice -> preview reflects ₹6,000 remaining advance + ₹5,000 deposit = ₹11,000, dues separate.
        vacate = self.client.post(reverse('vacate-list'), {
            'resident': str(self.resident.id), 'notice_given_date': '2026-09-01',
        }).data
        preview_c = self.client.get(reverse('vacate-settlement-preview', args=[vacate['id']])).data
        self.assertEqual(preview_c['advance_refundable'], '6000.00')
        self.assertEqual(preview_c['refund_amount'], '11000.00')
        self.assertEqual(preview_c['outstanding_dues'], '10000.00')

        # Path B (leave Sep unpaid / paid by cash) -> ₹11,000 refund; Path A: adjust remaining ₹6,000 -> ₹5,000.
        adj_sep_2 = self._adjust(sep['id'], '6000.00', '2026-09-10')
        self.assertEqual(adj_sep_2.status_code, 201, adj_sep_2.data)
        preview_a = self.client.get(reverse('vacate-settlement-preview', args=[vacate['id']])).data
        self.assertEqual(preview_a['advance_refundable'], '0.00')
        self.assertEqual(preview_a['refund_amount'], '5000.00')
        self.assertEqual(preview_a['outstanding_dues'], '4000.00')

    def test_first_invoice_rule_blocks_adjustment_when_unsettled(self):
        self.check_in(
            self.resident, self.bed,
            joining_date=date(2026, 7, 1),
            advance_amount=Decimal('20000.00'),
            advance_collected_date=date(2026, 7, 1),
            advance_mode='upi',
        )
        # An issued invoice inserted without going through issue_invoice() leaves
        # first_invoice_advance_settled=False, so later manual adjustments are blocked.
        issued_bypass = self.create_invoice(self.resident, date(2026, 8, 1), status='issued')
        resp = self._adjust(issued_bypass.id, '5000.00', '2026-08-05')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'FIRST_INVOICE_NOT_ISSUED')

    def test_manual_payment_with_legacy_reference_does_not_restore_advance_on_delete(self):
        self._admit_via_api(advance='20000.00', deposit='5000.00')
        jul = self._generate_and_issue('2026-07-01', '2026-07-31', '2026-07-10')
        self.assertEqual(jul['status'], 'paid')
        aug = self._generate_and_issue('2026-08-01', '2026-08-31', '2026-08-10')

        manual = self.client.post(reverse('payment-list'), {
            'invoice': aug['id'],
            'amount': '3000.00',
            'payment_date': '2026-08-05',
            'payment_mode': 'cash',
            'reference': 'Advance collected at admission',
        })
        self.assertEqual(manual.status_code, 201, manual.data)
        self.assertFalse(manual.data['is_advance_adjustment'])

        self.assertEqual(self.client.delete(reverse('payment-detail', args=[manual.data['id']])).status_code, 204)
        self.assertEqual(self._admission().advance_applied_amount, Decimal('10000.00'))

    def test_blank_advance_mode_never_invents_cash_fallback(self):
        self.check_in(
            self.resident, self.bed,
            joining_date=date(2026, 7, 1),
            advance_amount=Decimal('20000.00'),
            advance_applied_amount=Decimal('10000.00'),
            advance_collected_date=date(2026, 7, 1),
            advance_mode='',
            first_invoice_advance_settled=True,
        )
        inv = self.create_invoice(self.resident, date(2026, 8, 1), total=Decimal('10000.00'))
        resp = self._adjust(inv.id, '5000.00', '2026-08-05')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['payment_mode'], '')
        self.assertIsNone(resp.data['historical_collection_mode'])
        self.assertEqual(resp.data['payment_source'], 'advance_adjustment')
        self.assertEqual(resp.data['payment_source_label'], 'Advance Adjustment')

        receipt = self.client.get(reverse('payment-receipt', args=[resp.data['id']])).data
        self.assertEqual(receipt['payment_mode'], '')
        self.assertIsNone(receipt['historical_collection_mode'])
        self.assertEqual(receipt['payment_source'], 'advance_adjustment')
        self.assertEqual(receipt['payment_source_label'], 'Advance Adjustment')

        pdf = self.client.get(reverse('payment-receipt', args=[resp.data['id']]), {'filetype': 'pdf'})
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))

        timeline = self.client.get(reverse('resident-timeline', args=[self.resident.id])).data
        events = [row for row in timeline if row['event'] == 'Advance Adjusted']
        self.assertEqual(len(events), 1)
        self.assertIn('Advance Adjustment', events[0]['detail'])

    def test_validation_guards_idempotency_permissions_and_exit_reversal_block(self):
        self._admit_via_api(advance='15000.00', deposit='5000.00')
        jul = self._generate_and_issue('2026-07-01', '2026-07-31', '2026-07-10')
        self.assertEqual(jul['status'], 'paid')  # 5,000 remaining
        draft = self.client.post(reverse('invoice-list'), {
            'resident': str(self.resident.id),
            'period_start': '2026-08-01', 'period_end': '2026-08-31', 'due_date': '2026-08-10',
        }).data
        self.assertEqual(self._adjust(draft['id'], '1000.00').status_code, 400)

        aug = self.client.post(reverse('invoice-issue', args=[draft['id']])).data
        # Exceeds remaining held advance (5,000 < 6,000)
        over_adv = self._adjust(aug['id'], '6000.00')
        self.assertEqual(over_adv.status_code, 400)
        self.assertEqual(over_adv.data['amount'].code, 'exceeds_held_advance')

        # Pay 8,000 by cash -> balance_due = 2,000 < 5,000 remaining -> overpayment guard
        self.client.post(reverse('payment-list'), {
            'invoice': aug['id'], 'amount': '8000.00',
            'payment_date': '2026-08-02', 'payment_mode': 'cash',
        })
        over_bal = self._adjust(aug['id'], '3000.00')
        self.assertEqual(over_bal.status_code, 400)
        self.assertEqual(over_bal.data['amount'].code, 'overpayment')

        # Idempotent retry & 409 reuse
        first = self._adjust(aug['id'], '2000.00', '2026-08-05', note='Final settlement', key='adj-key-1')
        self.assertEqual(first.status_code, 201)
        replay = self._adjust(aug['id'], '2000.00', '2026-08-05', note='Final settlement', key='adj-key-1')
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay['Idempotent-Replayed'], 'true')
        self.assertEqual(self._adjust(aug['id'], '1000.00', '2026-08-05', key='adj-key-1').status_code, 409)

        # Staff without manage_payments gets 403
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)
        self.assertEqual(self._adjust(aug['id'], '1000.00').status_code, 403)

        # Vacate resident -> reversing or creating advance adjustments is blocked
        self.authenticate(self.owner)
        vacate = self.client.post(reverse('vacate-list'), {
            'resident': str(self.resident.id), 'notice_given_date': '2026-08-01',
        }).data
        self.client.post(reverse('vacate-finalize', args=[vacate['id']]), {'actual_vacate_date': '2026-09-01'})
        del_after_exit = self.client.delete(reverse('payment-detail', args=[first.data['id']]))
        self.assertEqual(del_after_exit.status_code, 400)
        self.assertEqual(del_after_exit.data['code'], 'RESIDENT_NOT_CURRENT')

    def test_issuing_later_invoice_while_earlier_draft_exists_preserves_first_invoice_advance(self):
        self._admit_via_api(advance='20000.00', deposit='5000.00')
        jul_draft = self.client.post(reverse('invoice-list'), {
            'resident': str(self.resident.id),
            'period_start': '2026-07-01', 'period_end': '2026-07-31', 'due_date': '2026-07-10',
        }).data
        aug_draft = self.client.post(reverse('invoice-list'), {
            'resident': str(self.resident.id),
            'period_start': '2026-08-01', 'period_end': '2026-08-31', 'due_date': '2026-08-10',
        }).data

        # Staff issues August first while July is still a draft.
        aug_issued = self.client.post(reverse('invoice-issue', args=[aug_draft['id']])).data
        self.assertEqual(aug_issued['status'], 'issued')
        self.assertEqual(aug_issued['balance_due'], '10000.00')
        adm = self._admission()
        self.assertEqual(adm.advance_applied_amount, Decimal('0.00'))
        self.assertFalse(adm.first_invoice_advance_settled)

        # Manual adjust-advance on August stays blocked until July (the earlier invoice) is issued.
        blocked = self._adjust(aug_issued['id'], '5000.00', '2026-08-05')
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.data['code'], 'FIRST_INVOICE_NOT_ISSUED')

        # Issuing July next still applies Month 1's advance automatically to July and unlocks later adjustments.
        jul_issued = self.client.post(reverse('invoice-issue', args=[jul_draft['id']])).data
        self.assertEqual(jul_issued['status'], 'paid')
        self.assertEqual(jul_issued['balance_due'], '0.00')
        adm = self._admission()
        self.assertEqual(adm.advance_applied_amount, Decimal('10000.00'))
        self.assertEqual(adm.advance_refundable, Decimal('10000.00'))
        self.assertTrue(adm.first_invoice_advance_settled)

        # Now August can receive explicit adjustment from the remaining ₹10,000 held advance.
        aug_adj = self._adjust(aug_issued['id'], '4000.00', '2026-08-05')
        self.assertEqual(aug_adj.status_code, 201, aug_adj.data)
        self.assertEqual(self._admission().advance_refundable, Decimal('6000.00'))

    def test_deleting_blocking_earlier_draft_settles_remaining_earliest_issued_invoice(self):
        self._admit_via_api(advance='20000.00', deposit='5000.00')
        jul_draft = self.client.post(reverse('invoice-list'), {
            'resident': str(self.resident.id),
            'period_start': '2026-07-01', 'period_end': '2026-07-31', 'due_date': '2026-07-10',
        }).data
        aug_draft = self.client.post(reverse('invoice-list'), {
            'resident': str(self.resident.id),
            'period_start': '2026-08-01', 'period_end': '2026-08-31', 'due_date': '2026-08-10',
        }).data

        self.client.post(reverse('invoice-issue', args=[aug_draft['id']]))
        self.assertFalse(self._admission().first_invoice_advance_settled)

        deleted = self.client.delete(reverse('invoice-detail', args=[jul_draft['id']]))
        self.assertEqual(deleted.status_code, 204)

        aug_refreshed = self.client.get(reverse('invoice-detail', args=[aug_draft['id']])).data
        self.assertEqual(aug_refreshed['status'], 'paid')
        adm = self._admission()
        self.assertEqual(adm.advance_applied_amount, Decimal('10000.00'))
        self.assertEqual(adm.advance_refundable, Decimal('10000.00'))
        self.assertTrue(adm.first_invoice_advance_settled)

    def test_adjustment_date_required_on_api_and_replay_succeeds_across_midnight(self):
        from apps.billing import services as billing_services

        self._admit_via_api(advance='20000.00', deposit='5000.00')
        self._generate_and_issue('2026-07-01', '2026-07-31', '2026-07-10')
        aug = self._generate_and_issue('2026-08-01', '2026-08-31', '2026-08-10')
        sep = self._generate_and_issue('2026-09-01', '2026-09-30', '2026-09-10')

        # API requires an explicit adjustment_date so network retries cannot shift dates across midnight.
        missing_date = self.client.post(
            reverse('invoice-adjust-advance', args=[aug['id']]),
            {'amount': '4000.00'},
            HTTP_IDEMPOTENCY_KEY='missing-date-key',
        )
        self.assertEqual(missing_date.status_code, 400)
        self.assertIn('adjustment_date', missing_date.data)

        # 2026-08-05 23:59 IST == 18:29 UTC; 2026-08-06 00:01 IST == 18:31 UTC.
        before_midnight = datetime(2026, 8, 5, 18, 29, tzinfo=dt_timezone.utc)
        after_midnight = datetime(2026, 8, 5, 18, 31, tzinfo=dt_timezone.utc)

        with mock.patch('django.utils.timezone.now', return_value=before_midnight):
            first = self._adjust(aug['id'], '4000.00', '2026-08-05', key='api-midnight-key')
        self.assertEqual(first.status_code, 201, first.data)

        with mock.patch('django.utils.timezone.now', return_value=after_midnight):
            replay = self._adjust(aug['id'], '4000.00', '2026-08-05', key='api-midnight-key')
            mismatch = self._adjust(aug['id'], '4000.00', '2026-08-06', key='api-midnight-key')
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay['Idempotent-Replayed'], 'true')
        self.assertEqual(replay.data['id'], first.data['id'])
        self.assertEqual(mismatch.status_code, 409)

        # Direct Python callers passing adjustment_date=None also replay safely across midnight.
        with tenant_context(self.tenant.id):
            with mock.patch('django.utils.timezone.now', return_value=before_midnight):
                svc_first = billing_services.adjust_from_advance(
                    invoice_id=sep['id'],
                    amount=Decimal('3000.00'),
                    adjustment_date=None,
                    actor=self.owner,
                    idempotency_key='svc-midnight-key',
                )
            with mock.patch('django.utils.timezone.now', return_value=after_midnight):
                svc_replay = billing_services.adjust_from_advance(
                    invoice_id=sep['id'],
                    amount=Decimal('3000.00'),
                    adjustment_date=None,
                    actor=self.owner,
                    idempotency_key='svc-midnight-key',
                )
        self.assertFalse(svc_first.replayed)
        self.assertTrue(svc_replay.replayed)
        self.assertEqual(svc_replay.id, svc_first.id)
        self.assertEqual(svc_replay.payment_date, date(2026, 8, 5))


class BillingAcrossNoticeCancellationTests(BillingAPITestCase):
    """Cancelling a notice (Module 10) must be invisible to billing. Notice
    Period is already billable, so the resident is invoiceable before and
    after, at the same contracted rent — invariant 2, never re-derived from the
    room's rack rate."""

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.room = self.create_room(
            self.create_floor(self.property), room_number='101', sharing_type=4, category='ac',
            rack_rate_with_food=Decimal('7000.00'), rack_rate_without_food=Decimal('5500.00'),
        )
        self.bed = self.create_bed(self.room, bed_number='101-A')
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.check_in(self.resident, self.bed)  # contracted 7000, with food
        self.authenticate(self.owner)

    def _generate(self, **period):
        payload = {'resident': str(self.resident.id), **PERIOD}
        payload.update(period)
        return self.client.post(reverse('invoice-list'), payload)

    def test_resident_is_billable_at_the_same_rent_before_and_after_cancelling(self):
        vacate = self.client.post(reverse('vacate-list'), {
            'resident': str(self.resident.id), 'notice_given_date': '2026-07-01',
        })
        self.assertEqual(vacate.status_code, 201, vacate.data)

        during_notice = self._generate()
        self.assertEqual(during_notice.status_code, 201, during_notice.data)

        cancel = self.client.post(reverse('vacate-cancel', args=[vacate.data['id']]), {
            'cancellation_reason': 'Resident is staying on',
        })
        self.assertEqual(cancel.status_code, 200, cancel.data)

        after_cancel = self._generate(
            period_start='2026-08-01', period_end='2026-08-31', due_date='2026-08-10',
        )

        self.assertEqual(after_cancel.status_code, 201, after_cancel.data)
        # Same contracted rent on both sides of the cancellation.
        self.assertEqual(during_notice.data['total'], '7000.00')
        self.assertEqual(after_cancel.data['total'], '7000.00')
        self.assertEqual(
            _lines_by_type(after_cancel.data)['accommodation']['amount'], '7000.00'
        )

    def test_cancelling_does_not_change_the_plan_resident_count(self):
        """Active and Notice Period both count toward the plan limit, so the
        round trip must leave the tally untouched."""
        def counted():
            with tenant_context(self.tenant.id):
                return Resident.objects.filter(
                    property=self.property, status__in=Resident.COUNTS_TOWARD_PLAN_LIMIT,
                ).count()

        before = counted()
        vacate = self.client.post(reverse('vacate-list'), {
            'resident': str(self.resident.id), 'notice_given_date': '2026-07-01',
        })
        self.assertEqual(counted(), before)

        self.client.post(reverse('vacate-cancel', args=[vacate.data['id']]), {
            'cancellation_reason': 'Resident is staying on',
        })

        self.assertEqual(counted(), before)
