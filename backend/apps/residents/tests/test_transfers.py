from decimal import Decimal

from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.properties.models import Bed, Room
from apps.residents.models import Resident

from .base import ResidentAPITestCase


class TransferTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room_a = self.create_room(
            self.floor, room_number='101', sharing_type=Room.SharingType.FOUR, category=Room.Category.AC,
            rack_rate_with_food=Decimal('7000.00'), rack_rate_without_food=Decimal('5500.00'),
        )
        self.room_b = self.create_room(
            self.floor, room_number='201', sharing_type=Room.SharingType.TWO, category=Room.Category.AC,
            rack_rate_with_food=Decimal('10000.00'), rack_rate_without_food=Decimal('8000.00'),
        )
        self.bed_a = self.create_bed(self.room_a, bed_number='101-A')
        self.bed_b = self.create_bed(self.room_b, bed_number='201-A')
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.allocation = self.check_in(self.resident, self.bed_a)  # contracted 7000, with_food
        self.authenticate(self.owner)

    def _transfer(self, **overrides):
        payload = {
            'resident': str(self.resident.id),
            'new_bed': str(self.bed_b.id),
            'transfer_date': '2026-07-15',
        }
        payload.update(overrides)
        return self.client.post(reverse('transfer-list'), payload)

    def test_permanent_transfer_updates_contracted_rent_from_new_bed(self):
        response = self._transfer()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data['is_temporary'])
        self.assertEqual(response.data['previous_rent'], '7000.00')
        self.assertEqual(response.data['new_rent'], '10000.00')  # bed_b with-food rack rate

        with tenant_context(self.tenant.id):
            self.allocation.refresh_from_db()
            self.bed_a.refresh_from_db()
            self.bed_b.refresh_from_db()
        self.assertEqual(self.allocation.allocated_bed_id, self.bed_b.id)
        self.assertEqual(self.allocation.contracted_rent, Decimal('10000.00'))
        self.assertEqual(self.allocation.contracted_sharing_type, 2)
        self.assertFalse(self.allocation.is_temporary)
        self.assertEqual(self.bed_a.status, Bed.Status.AVAILABLE)
        self.assertEqual(self.bed_b.status, Bed.Status.OCCUPIED)

    def test_permanent_transfer_honours_explicit_new_rent(self):
        response = self._transfer(new_rent='9000.00')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['new_rent'], '9000.00')
        with tenant_context(self.tenant.id):
            self.allocation.refresh_from_db()
        self.assertEqual(self.allocation.contracted_rent, Decimal('9000.00'))

    def test_rent_effective_date_defaults_to_next_billing_cycle(self):
        response = self._transfer()
        self.assertEqual(response.data['rent_effective_date'], '2026-08-01')

    def test_rent_effective_date_immediate_when_property_configured(self):
        self.client.patch(
            reverse('property-settings', args=[self.property.id]),
            {'room_transfer_rent_timing': 'immediate'},
        )
        response = self._transfer()
        self.assertEqual(response.data['rent_effective_date'], '2026-07-15')

    def test_temporary_transfer_keeps_contracted_rent(self):
        response = self._transfer(
            is_temporary=True, temporary_note='4-sharing full, placed in 2-sharing',
            expected_move_date='2026-08-01',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['is_temporary'])
        self.assertEqual(response.data['previous_rent'], '7000.00')
        self.assertEqual(response.data['new_rent'], '7000.00')  # unchanged (invariant 3)

        with tenant_context(self.tenant.id):
            self.allocation.refresh_from_db()
        self.assertTrue(self.allocation.is_temporary)
        self.assertEqual(self.allocation.contracted_rent, Decimal('7000.00'))
        self.assertEqual(str(self.allocation.temporary_since), '2026-07-15')
        self.assertEqual(self.allocation.allocated_bed_id, self.bed_b.id)

    def test_temporary_allocation_exposes_contracted_vs_actual(self):
        self._transfer(is_temporary=True)
        response = self.client.get(reverse('allocation-list'), {'is_temporary': 'true'})

        allocation = response.data[0]
        self.assertEqual(allocation['contracted_sharing_type'], 4)  # what they pay for
        self.assertEqual(allocation['actual_sharing_type'], 2)      # where they physically are
        self.assertEqual(allocation['contracted_rent'], '7000.00')

    def test_permanent_transfer_clears_temporary_flag(self):
        self._transfer(is_temporary=True)  # place temporarily in room_b
        bed_c = self.create_bed(self.room_a, bed_number='101-B')  # matching 4-sharing bed

        response = self.client.post(reverse('transfer-list'), {
            'resident': str(self.resident.id), 'new_bed': str(bed_c.id), 'transfer_date': '2026-08-01',
        })

        self.assertEqual(response.status_code, 201, response.data)
        with tenant_context(self.tenant.id):
            self.allocation.refresh_from_db()
        self.assertFalse(self.allocation.is_temporary)
        self.assertIsNone(self.allocation.temporary_since)

    def test_cannot_transfer_to_occupied_bed(self):
        other = self.create_resident(self.property, phone='9000000002', status=Resident.Status.RESERVED)
        self.check_in(other, self.bed_b)  # bed_b now occupied

        response = self._transfer()

        self.assertEqual(response.status_code, 400)
        self.assertIn('new_bed', response.data)

    def test_cannot_transfer_to_same_bed(self):
        response = self._transfer(new_bed=str(self.bed_a.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn('new_bed', response.data)

    def test_cannot_transfer_to_bed_in_another_property(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        other_bed = self.create_bed(self.create_room(self.create_floor(other_property)))

        response = self._transfer(new_bed=str(other_bed.id))

        self.assertEqual(response.status_code, 400)
        self.assertIn('new_bed', response.data)

    def test_cannot_transfer_resident_without_allocation(self):
        reserved = self.create_resident(self.property, phone='9000000002', status=Resident.Status.RESERVED)
        response = self._transfer(resident=str(reserved.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn('resident', response.data)

    def test_transfer_records_history_and_audit_log(self):
        self._transfer()

        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='resident.transferred').exists())
        history = self.client.get(reverse('transfer-list'))
        self.assertEqual(len(history.data), 1)
        self.assertEqual(str(history.data[0]['resident']), str(self.resident.id))

    def test_receptionist_cannot_transfer(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        response = self._transfer()

        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_transfer_in_unassigned_property(self):
        manager = self.create_manager(self.tenant)  # not assigned to self.property
        self.authenticate(manager)

        response = self._transfer()

        self.assertEqual(response.status_code, 400)
        self.assertIn('resident', response.data)
