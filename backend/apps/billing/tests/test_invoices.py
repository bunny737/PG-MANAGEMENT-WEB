from datetime import date, timedelta
from decimal import Decimal

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

    def _admit(self, advance):
        self.check_in(
            self.resident, self.bed, advance_amount=Decimal(advance),
            advance_collected_date=date(2026, 7, 1), advance_mode=Admission.AdvanceMode.UPI,
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
        self.assertEqual(payment.payment_date, date(2026, 7, 1))
        self.assertEqual(self._refresh_admission().advance_applied_amount, Decimal('7000.00'))

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

    def test_deleting_the_advance_payment_releases_the_advance(self):
        self._admit('7000.00')
        invoice = self._generate_and_issue()
        with tenant_context(self.tenant.id):
            payment = Payment.objects.get(invoice_id=invoice['id'])

        response = self.client.delete(reverse('payment-detail', args=[payment.id]))

        self.assertEqual(response.status_code, 204)
        admission = self._refresh_admission()
        self.assertEqual(admission.advance_applied_amount, Decimal('0.00'))
        self.assertEqual(admission.advance_refundable, Decimal('7000.00'))

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
