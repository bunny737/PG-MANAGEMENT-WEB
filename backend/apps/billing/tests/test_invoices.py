from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.residents.models import Admission, Resident

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
