from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.properties.models import Bed, Building, Room

from .base import PropertyAPITestCase


class RoomBedHierarchyTests(PropertyAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        # create_property already auto-provisions the default Building
        # (mirrors PropertyViewSet.perform_create) — fetch it rather than
        # creating a second one.
        with tenant_context(self.tenant.id):
            self.building = Building.objects.get(property=self.property)

    def test_owner_builds_floor_room_bed_hierarchy(self):
        self.authenticate(self.owner)

        floor_resp = self.client.post(
            reverse('floor-list'), {'building': str(self.building.id), 'name': 'Ground Floor', 'order': 0}
        )
        self.assertEqual(floor_resp.status_code, 201)

        room_resp = self.client.post(reverse('room-list'), {
            'floor': floor_resp.data['id'], 'room_number': '201', 'sharing_type': 4,
            'category': 'ac', 'rack_rate_with_food': '7000.00', 'rack_rate_without_food': '5500.00',
        })
        self.assertEqual(room_resp.status_code, 201)
        self.assertEqual(room_resp.data['bed_capacity'], 4)
        self.assertEqual(room_resp.data['current_occupancy'], 0)

        bed_resp = self.client.post(
            reverse('bed-list'), {'room': room_resp.data['id'], 'bed_number': '201-A'}
        )
        self.assertEqual(bed_resp.status_code, 201)
        self.assertEqual(bed_resp.data['effective_rate_with_food'], '7000.00')

    def test_bed_count_cannot_exceed_room_sharing_type(self):
        floor = self.create_floor(self.property)
        room = self.create_room(floor, sharing_type=Room.SharingType.TWO)
        self.create_bed(room, bed_number='101-A')
        self.create_bed(room, bed_number='101-B')
        self.authenticate(self.owner)

        response = self.client.post(reverse('bed-list'), {'room': str(room.id), 'bed_number': '101-C'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('room', response.data)

    def test_room_status_syncs_from_bed_statuses(self):
        floor = self.create_floor(self.property)
        room = self.create_room(floor, sharing_type=Room.SharingType.TWO)
        bed_a = self.create_bed(room, bed_number='101-A')
        bed_b = self.create_bed(room, bed_number='101-B')
        self.authenticate(self.owner)

        def room_status():
            return self.client.get(reverse('room-detail', args=[room.id])).data['status']

        self.assertEqual(room_status(), 'available')

        self.client.patch(reverse('bed-detail', args=[bed_a.id]), {'status': 'occupied'})
        self.assertEqual(room_status(), 'available')  # bed_b still vacant

        self.client.patch(reverse('bed-detail', args=[bed_b.id]), {'status': 'occupied'})
        self.assertEqual(room_status(), 'occupied')

        self.client.patch(reverse('bed-detail', args=[bed_b.id]), {'status': 'reserved'})
        self.assertEqual(room_status(), 'reserved')

    def test_manual_maintenance_status_is_not_overridden_by_bed_sync(self):
        floor = self.create_floor(self.property)
        room = self.create_room(floor, sharing_type=Room.SharingType.ONE)
        bed = self.create_bed(room, bed_number='101-A')
        self.authenticate(self.owner)

        self.client.patch(reverse('room-detail', args=[room.id]), {'status': 'maintenance'})
        self.client.patch(reverse('bed-detail', args=[bed.id]), {'status': 'occupied'})

        detail = self.client.get(reverse('room-detail', args=[room.id]))
        self.assertEqual(detail.data['status'], 'maintenance')

    def test_cannot_delete_floor_with_rooms_or_room_with_beds(self):
        floor = self.create_floor(self.property)
        room = self.create_room(floor)
        bed = self.create_bed(room)
        self.authenticate(self.owner)

        self.assertEqual(self.client.delete(reverse('floor-detail', args=[floor.id])).status_code, 400)
        self.assertEqual(self.client.delete(reverse('room-detail', args=[room.id])).status_code, 400)

        with tenant_context(self.tenant.id):
            bed.status = Bed.Status.OCCUPIED
            bed.save()
        self.assertEqual(self.client.delete(reverse('bed-detail', args=[bed.id])).status_code, 400)

        with tenant_context(self.tenant.id):
            bed.status = Bed.Status.AVAILABLE
            bed.save()
        self.assertEqual(self.client.delete(reverse('bed-detail', args=[bed.id])).status_code, 204)

    def test_receptionist_has_no_access_to_rooms_or_beds(self):
        receptionist = self.create_receptionist(self.tenant)
        self.authenticate(receptionist)
        self.assertEqual(self.client.get(reverse('floor-list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('room-list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('bed-list')).status_code, 403)

    def test_manager_can_add_floor_to_assigned_property(self):
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        response = self.client.post(
            reverse('floor-list'), {'building': str(self.building.id), 'name': 'Ground Floor', 'order': 0}
        )

        self.assertEqual(response.status_code, 201)

    def test_manager_cannot_add_floor_to_unassigned_property(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        with tenant_context(self.tenant.id):
            other_building = Building.objects.get(property=other_property)
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)  # not assigned to other_property
        self.authenticate(manager)

        response = self.client.post(
            reverse('floor-list'), {'building': str(other_building.id), 'name': 'Ground Floor', 'order': 0}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('building', response.data)

    def test_manager_only_sees_rooms_in_assigned_properties(self):
        floor = self.create_floor(self.property)
        my_room = self.create_room(floor, room_number='101')
        other_property = self.create_property(self.tenant, name='Other Property')
        other_floor = self.create_floor(other_property)
        self.create_room(other_floor, room_number='201')

        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        response = self.client.get(reverse('room-list'))
        room_numbers = {row['room_number'] for row in response.data}
        self.assertEqual(room_numbers, {my_room.room_number})

    def test_floor_serializer_auto_order_and_counters(self):
        self.authenticate(self.owner)

        # 1. Create first floor without specifying order (should default to 0)
        resp1 = self.client.post(
            reverse('floor-list'), {'building': str(self.building.id), 'name': 'Ground Floor'}
        )
        self.assertEqual(resp1.status_code, 201)
        self.assertEqual(resp1.data['order'], 0)
        self.assertEqual(resp1.data['rooms_count'], 0)
        self.assertEqual(resp1.data['occupancy_percent'], 0)

        # 2. Create second floor without specifying order (should auto-increment to 1)
        resp2 = self.client.post(
            reverse('floor-list'), {'building': str(self.building.id), 'name': 'First Floor'}
        )
        self.assertEqual(resp2.status_code, 201)
        self.assertEqual(resp2.data['order'], 1)

        # 3. Create a room on First Floor
        room_resp = self.client.post(reverse('room-list'), {
            'floor': resp2.data['id'], 'room_number': '101', 'sharing_type': 2,
            'category': 'ac', 'rack_rate_with_food': '5000.00', 'rack_rate_without_food': '4000.00',
        })
        self.assertEqual(room_resp.status_code, 201)

        # Check rooms_count has updated to 1
        detail_resp = self.client.get(reverse('floor-detail', args=[resp2.data['id']]))
        self.assertEqual(detail_resp.data['rooms_count'], 1)
        self.assertEqual(detail_resp.data['occupancy_percent'], 0)

        # 4. Add beds to the room and occupy one to verify occupancy_percent updates
        bed_a = self.client.post(reverse('bed-list'), {'room': room_resp.data['id'], 'bed_number': '101-A'})
        bed_b = self.client.post(reverse('bed-list'), {'room': room_resp.data['id'], 'bed_number': '101-B'})
        self.assertEqual(bed_a.status_code, 201)
        self.assertEqual(bed_b.status_code, 201)

        # Set bed_a to occupied
        self.client.patch(reverse('bed-detail', args=[bed_a.data['id']]), {'status': 'occupied'})

        # Now floor occupancy_percent should be 50%
        detail_resp = self.client.get(reverse('floor-detail', args=[resp2.data['id']]))
        self.assertEqual(detail_resp.data['occupancy_percent'], 50)

        # Property occupancy_percent should also be 50%
        prop_resp = self.client.get(reverse('property-detail', args=[self.property.id]))
        self.assertEqual(prop_resp.data['occupancy_percent'], 50)
