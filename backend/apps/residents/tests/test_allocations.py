from decimal import Decimal

from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.properties.models import Room
from apps.residents.models import Resident

from .base import ResidentAPITestCase


class AllocationTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(
            self.floor, sharing_type=Room.SharingType.FOUR, category=Room.Category.AC,
            rack_rate_with_food=Decimal('7000.00'), rack_rate_without_food=Decimal('5500.00'),
        )
        self.bed = self.create_bed(self.room, bed_number='101-A')
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)

    def test_checkin_creates_allocation_mirroring_admitted_bed(self):
        self.authenticate(self.owner)
        admit = self.client.post(reverse('admission-list'), {
            'resident': str(self.resident.id), 'bed': str(self.bed.id),
            'joining_date': '2026-07-01', 'billing_mode': 'monthly', 'food_preference': 'with_food',
        })
        self.assertEqual(admit.status_code, 201, admit.data)

        response = self.client.get(reverse('allocation-list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        allocation = response.data[0]
        self.assertEqual(str(allocation['allocated_bed']), str(self.bed.id))
        self.assertEqual(allocation['contracted_rent'], '7000.00')
        self.assertFalse(allocation['is_temporary'])
        self.assertEqual(allocation['actual_sharing_type'], 4)
        self.assertEqual(allocation['actual_room_category'], 'ac')

    def test_temporary_filter_lists_only_temporary_allocations(self):
        allocation = self.check_in(self.resident, self.bed)
        with tenant_context(self.tenant.id):
            allocation.is_temporary = True
            allocation.save()
        second = self.create_resident(self.property, phone='9000000002', status=Resident.Status.RESERVED)
        self.check_in(second, self.create_bed(self.room, bed_number='101-B'))

        self.authenticate(self.owner)
        response = self.client.get(reverse('allocation-list'), {'is_temporary': 'true'})

        self.assertEqual(len(response.data), 1)
        self.assertEqual(str(response.data[0]['resident']), str(self.resident.id))

    def test_allocation_is_read_only(self):
        allocation = self.check_in(self.resident, self.bed)
        self.authenticate(self.owner)

        detail_url = reverse('allocation-detail', args=[allocation.id])
        self.assertEqual(self.client.patch(detail_url, {'is_temporary': True}).status_code, 405)
        self.assertEqual(self.client.delete(detail_url).status_code, 405)

    def test_receptionist_cannot_view_allocations(self):
        self.check_in(self.resident, self.bed)
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        self.assertEqual(self.client.get(reverse('allocation-list')).status_code, 403)

    def test_manager_sees_only_assigned_property_allocations(self):
        self.check_in(self.resident, self.bed)
        other_property = self.create_property(self.tenant, name='Other Property')
        other_floor = self.create_floor(other_property)
        other_bed = self.create_bed(self.create_room(other_floor))
        other_resident = self.create_resident(
            other_property, phone='9000000003', status=Resident.Status.RESERVED
        )
        self.check_in(other_resident, other_bed)

        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        response = self.client.get(reverse('allocation-list'))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(str(response.data[0]['resident']), str(self.resident.id))
