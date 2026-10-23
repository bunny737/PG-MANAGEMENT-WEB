"""D2 — GET /properties/{id}/layout/: structure, counts, payment states,
redaction and property scope."""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse

from apps.billing.tests.base import BillingAPITestCase
from apps.core.periods import local_today, month_key, month_start
from apps.core.tenancy import tenant_context
from apps.properties.models import Bed
from apps.residents.models import Resident


class LayoutTests(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.prop = self.create_property(self.tenant)
        self.floor = self.create_floor(self.prop)
        self.room = self.create_room(self.floor, room_number='101')
        self.beds = [self.create_bed(self.room, bed_number=f'101-{c}') for c in 'ABCD']
        self.today = local_today()
        self.month = month_start(self.today)
        self.url = reverse('property-layout', args=[self.prop.id])
        self.authenticate(self.owner)

    def admit(self, bed, name, phone):
        resident = self.create_resident(self.prop, first_name=name, phone=phone, status=Resident.Status.RESERVED)
        self.check_in(resident, bed)
        return resident

    def bed_row(self, data, bed):
        for building in data['buildings']:
            for floor in building['floors']:
                for room in floor['rooms']:
                    for row in room['beds']:
                        if row['id'] == str(bed.id):
                            return row
        raise AssertionError('bed not in layout')

    def test_structure_counts_and_occupancy(self):
        self.admit(self.beds[0], 'Ravi', '9000000001')
        with tenant_context(self.tenant.id):
            Bed.objects.filter(pk=self.beds[1].pk).update(status=Bed.Status.MAINTENANCE)
            Bed.objects.filter(pk=self.beds[2].pk).update(status=Bed.Status.RESERVED)
        data = self.client.get(self.url).data
        self.assertEqual(data['period'], month_key(self.month))
        self.assertEqual(
            data['counts'],
            {'total': 4, 'occupied': 1, 'reserved': 1, 'maintenance': 1, 'available': 1,
             'occupancy_rate': 33.3},
        )
        room = data['buildings'][0]['floors'][0]['rooms'][0]
        self.assertEqual(room['room_number'], '101')
        self.assertEqual(room['rack_rate_with_food'], '5500.00')
        self.assertEqual(len(room['beds']), 4)
        self.assertEqual(data['buildings'][0]['floors'][0]['counts']['total'], 4)
        self.assertEqual(data['redacted'], [])
        # allowed_transitions (D9/F8) travels with every bed in the layout too.
        self.assertEqual(self.bed_row(data, self.beds[0])['allowed_transitions'], [])  # occupied
        self.assertEqual(
            sorted(self.bed_row(data, self.beds[1])['allowed_transitions']),  # maintenance
            ['available', 'reserved'],
        )

    def test_occupancy_rate_null_when_every_bed_is_under_maintenance(self):
        with tenant_context(self.tenant.id):
            Bed.objects.filter(room=self.room).update(status=Bed.Status.MAINTENANCE)
        self.assertIsNone(self.client.get(self.url).data['counts']['occupancy_rate'])

    def test_payment_states(self):
        paid = self.admit(self.beds[0], 'Paid', '9000000001')
        due = self.admit(self.beds[1], 'Due', '9000000002')
        upcoming = self.admit(self.beds[2], 'Later', '9000000003')
        overdue = self.admit(self.beds[3], 'Late', '9000000004')
        inv = self.create_invoice(paid, self.month, due_date=self.today + timedelta(days=20))
        self.pay(inv, Decimal('7000.00'), self.today)
        self.create_invoice(due, self.month, due_date=self.today + timedelta(days=3))
        self.create_invoice(upcoming, self.month, due_date=self.today + timedelta(days=20))
        # Overdue from an earlier month wins over the current period's state.
        self.create_invoice(overdue, month_start(self.month - timedelta(days=1)),
                            due_date=self.today - timedelta(days=1))
        data = self.client.get(self.url).data
        states = {bed.bed_number: self.bed_row(data, bed)['payment']['status'] for bed in self.beds}
        self.assertEqual(states, {'101-A': 'paid', '101-B': 'due', '101-C': 'upcoming', '101-D': 'overdue'})
        late = self.bed_row(data, self.beds[3])['payment']
        self.assertEqual(late['overdue_balance'], '7000.00')
        self.assertEqual(data['finance']['outstanding_total'], '21000.00')
        self.assertEqual(data['finance']['residents_with_balance_count'], 3)
        self.assertEqual(data['finance']['occupied_beds_with_balance_count'], 3)

    def test_no_invoice_and_drafts_do_not_count(self):
        resident = self.admit(self.beds[0], 'New', '9000000001')
        self.create_invoice(resident, self.month, status='draft')
        row = self.bed_row(self.client.get(self.url).data, self.beds[0])
        self.assertEqual(row['payment']['status'], 'no_invoice')
        self.assertEqual(row['resident']['name'], 'New')
        self.assertFalse(row['resident']['on_notice'])

    def test_previous_occupant_dues_never_colour_a_vacant_bed(self):
        resident = self.admit(self.beds[0], 'Gone', '9000000001')
        self.create_invoice(resident, self.month, due_date=self.today - timedelta(days=2))
        with tenant_context(self.tenant.id):
            resident.status = Resident.Status.VACATED
            resident.save(update_fields=['status'])
            Bed.objects.filter(pk=self.beds[0].pk).update(status=Bed.Status.AVAILABLE)
        data = self.client.get(self.url).data
        row = self.bed_row(data, self.beds[0])
        self.assertIsNone(row['resident'])
        self.assertIsNone(row['payment'])
        # ...but the dues stay visible on the property banner.
        self.assertEqual(data['finance']['outstanding_total'], '7000.00')

    def test_period_parameter(self):
        resident = self.admit(self.beds[0], 'Ravi', '9000000001')
        self.create_invoice(resident, self.month, due_date=self.today + timedelta(days=20))
        previous = month_start(self.month - timedelta(days=1))
        data = self.client.get(self.url, {'period': month_key(previous)}).data
        self.assertEqual(self.bed_row(data, self.beds[0])['payment']['status'], 'no_invoice')
        self.assertEqual(self.client.get(self.url, {'period': 'oct'}).status_code, 400)

    def test_entry_via_allocations_with_finance_off_redacts_payment(self):
        """Properties off: the only entry codes are Tenants->Full's
        manage_admissions / manage_allocations. (Module levels are cumulative,
        so manage_allocations always comes with view_resident_profile.)"""
        self.admit(self.beds[0], 'Ravi', '9000000001')
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.prop)
        self.customize(manager, properties='off', tenants='full', finance='off')
        self.authenticate(manager)
        data = self.client.get(self.url).data
        self.assertEqual(set(data['redacted']), {'payment', 'finance'})
        row = self.bed_row(data, self.beds[0])
        self.assertEqual(row['availability'], 'occupied')
        self.assertIsNone(row['payment'])
        self.assertIsNone(data['finance'])
        self.assertEqual(row['rack_rate_with_food'], '5500.00')  # rates stay visible

    def test_receptionist_sees_occupants_but_no_money(self):
        self.admit(self.beds[0], 'Ravi', '9000000001')
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.prop)
        self.authenticate(receptionist)
        data = self.client.get(self.url).data
        self.assertEqual(set(data['redacted']), {'payment', 'finance'})
        self.assertEqual(self.bed_row(data, self.beds[0])['resident']['name'], 'Ravi')

    def test_resident_redacted_without_view_resident_profile(self):
        self.admit(self.beds[0], 'Ravi', '9000000001')
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.prop)
        self.customize(manager, tenants='off', properties='view')
        self.authenticate(manager)
        data = self.client.get(self.url).data
        self.assertIn('resident', data['redacted'])
        row = self.bed_row(data, self.beds[0])
        self.assertEqual(row['availability'], 'occupied')
        self.assertIsNone(row['resident'])

    def test_no_entry_permission_is_403(self):
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.prop)
        self.customize(manager, properties='off', tenants='off')
        self.authenticate(manager)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_unassigned_and_other_tenant_property_is_404(self):
        manager = self.create_manager(self.tenant)
        self.authenticate(manager)  # not assigned to self.prop
        self.assertEqual(self.client.get(self.url).status_code, 404)
        other = self.create_tenant('Other')
        other_prop = self.create_property(other)
        self.authenticate(self.owner)
        self.assertEqual(self.client.get(reverse('property-layout', args=[other_prop.id])).status_code, 404)
