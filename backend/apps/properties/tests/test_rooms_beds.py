from datetime import date
from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.properties.models import Bed, Building, Room
from apps.residents.models import Admission, Allocation, Resident

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

    def _room_payload(self, floor, **extra):
        return {
            'floor': str(floor.id), 'room_number': '301', 'sharing_type': 3,
            'category': 'non_ac', 'rack_rate_with_food': '6000.00',
            'rack_rate_without_food': '4500.00', **extra,
        }

    def test_auto_create_beds_creates_sharing_type_beds(self):
        floor = self.create_floor(self.property)
        self.authenticate(self.owner)

        response = self.client.post(
            reverse('room-list'), self._room_payload(floor, auto_create_beds=True)
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual([b['bed_number'] for b in response.data['beds']], ['301-A', '301-B', '301-C'])
        self.assertEqual(response.data['bed_capacity'], 3)
        self.assertEqual(response.data['beds'][0]['effective_rate_with_food'], '6000.00')
        self.assertNotIn('auto_create_beds', response.data)

    def test_auto_created_beds_are_tenant_isolated(self):
        floor = self.create_floor(self.property)
        self.authenticate(self.owner)
        self.client.post(reverse('room-list'), self._room_payload(floor, auto_create_beds=True))
        other_tenant = self.create_tenant('Other PG Co')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')

        self.authenticate(other_owner)
        response = self.client.get(reverse('bed-list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results'] if 'results' in response.data else response.data), 0)

    def test_room_without_auto_create_beds_has_no_beds(self):
        floor = self.create_floor(self.property)
        self.authenticate(self.owner)

        response = self.client.post(reverse('room-list'), self._room_payload(floor))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['beds'], [])

    def test_auto_create_beds_rejects_overlong_room_number(self):
        floor = self.create_floor(self.property)
        self.authenticate(self.owner)

        response = self.client.post(
            reverse('room-list'), self._room_payload(floor, room_number='9' * 19, auto_create_beds=True)
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('room_number', response.data)
        with tenant_context(self.tenant.id):
            self.assertFalse(Room.objects.filter(room_number='9' * 19).exists())

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

        # Occupied is set only by the admission/transfer workflows (D9), which
        # save the bed directly — do the same; Bed.save() runs the room sync.
        self.set_bed_status(bed_a, Bed.Status.OCCUPIED)
        self.assertEqual(room_status(), 'available')  # bed_b still vacant

        self.set_bed_status(bed_b, Bed.Status.OCCUPIED)
        self.assertEqual(room_status(), 'occupied')

        self.set_bed_status(bed_b, Bed.Status.RESERVED)
        self.assertEqual(room_status(), 'reserved')

    @staticmethod
    def set_bed_status(bed, status):
        with tenant_context(bed.tenant_id):
            bed.refresh_from_db()
            bed.status = status
            bed.save()

    def test_manual_maintenance_status_is_not_overridden_by_bed_sync(self):
        floor = self.create_floor(self.property)
        room = self.create_room(floor, sharing_type=Room.SharingType.ONE)
        bed = self.create_bed(room, bed_number='101-A')
        self.authenticate(self.owner)

        self.client.patch(reverse('room-detail', args=[room.id]), {'status': 'maintenance'})
        self.set_bed_status(bed, Bed.Status.OCCUPIED)

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

    def test_receptionist_can_view_floors_rooms_beds_of_assigned_property(self):
        floor = self.create_floor(self.property)
        room = self.create_room(floor)
        bed = self.create_bed(room)

        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        # Floors
        f_list = self.client.get(reverse('floor-list'), {'building': str(self.building.id)})
        self.assertEqual(f_list.status_code, 200)
        self.assertEqual(len(f_list.data), 1)
        f_detail = self.client.get(reverse('floor-detail', args=[floor.id]))
        self.assertEqual(f_detail.status_code, 200)

        # Rooms
        r_list = self.client.get(reverse('room-list'), {'floor': str(floor.id)})
        self.assertEqual(r_list.status_code, 200)
        self.assertEqual(len(r_list.data), 1)
        r_detail = self.client.get(reverse('room-detail', args=[room.id]))
        self.assertEqual(r_detail.status_code, 200)

        # Beds
        b_list = self.client.get(reverse('bed-list'), {'room': str(room.id)})
        self.assertEqual(b_list.status_code, 200)
        self.assertEqual(len(b_list.data), 1)
        b_detail = self.client.get(reverse('bed-detail', args=[bed.id]))
        self.assertEqual(b_detail.status_code, 200)

    def test_receptionist_cannot_view_floors_rooms_beds_of_unassigned_property(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        other_floor = self.create_floor(other_property)
        other_room = self.create_room(other_floor)
        other_bed = self.create_bed(other_room)

        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)  # not other_property
        self.authenticate(receptionist)

        # Floors
        f_list = self.client.get(reverse('floor-list'), {'building': str(other_floor.building.id)})
        self.assertEqual(f_list.status_code, 200)
        self.assertEqual(len(f_list.data), 0)
        self.assertEqual(self.client.get(reverse('floor-detail', args=[other_floor.id])).status_code, 404)

        # Rooms
        r_list = self.client.get(reverse('room-list'), {'floor': str(other_floor.id)})
        self.assertEqual(r_list.status_code, 200)
        self.assertEqual(len(r_list.data), 0)
        self.assertEqual(self.client.get(reverse('room-detail', args=[other_room.id])).status_code, 404)

        # Beds
        b_list = self.client.get(reverse('bed-list'), {'room': str(other_room.id)})
        self.assertEqual(b_list.status_code, 200)
        self.assertEqual(len(b_list.data), 0)
        self.assertEqual(self.client.get(reverse('bed-detail', args=[other_bed.id])).status_code, 404)

    def test_receptionist_cannot_create_update_or_delete_floors_rooms_beds(self):
        floor = self.create_floor(self.property)
        room = self.create_room(floor)
        bed = self.create_bed(room)

        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        # Floor mutations
        self.assertEqual(self.client.post(reverse('floor-list'), {'building': str(self.building.id), 'name': '2nd Floor'}).status_code, 403)
        self.assertEqual(self.client.patch(reverse('floor-detail', args=[floor.id]), {'name': 'Renamed'}).status_code, 403)
        self.assertEqual(self.client.delete(reverse('floor-detail', args=[floor.id])).status_code, 403)

        # Room mutations
        self.assertEqual(self.client.post(reverse('room-list'), self._room_payload(floor)).status_code, 403)
        self.assertEqual(self.client.patch(reverse('room-detail', args=[room.id]), {'room_number': '999'}).status_code, 403)
        self.assertEqual(self.client.delete(reverse('room-detail', args=[room.id])).status_code, 403)

        # Bed mutations
        self.assertEqual(self.client.post(reverse('bed-list'), {'room': str(room.id), 'bed_number': '999-Z'}).status_code, 403)
        self.assertEqual(self.client.patch(reverse('bed-detail', args=[bed.id]), {'bed_number': 'Renamed'}).status_code, 403)
        self.assertEqual(self.client.delete(reverse('bed-detail', args=[bed.id])).status_code, 403)

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

        # Occupy bed_a the way admission does (PATCH can't set occupied — D9).
        with tenant_context(self.property.tenant_id):
            occupied = Bed.objects.get(pk=bed_a.data['id'])
            occupied.status = Bed.Status.OCCUPIED
            occupied.save()

        # Now floor occupancy_percent should be 50%
        detail_resp = self.client.get(reverse('floor-detail', args=[resp2.data['id']]))
        self.assertEqual(detail_resp.data['occupancy_percent'], 50)

        # Property occupancy_percent should also be 50%
        prop_resp = self.client.get(reverse('property-detail', args=[self.property.id]))
        self.assertEqual(prop_resp.data['occupancy_percent'], 50)

    def _check_in_resident(self, bed, first_name='Ravi', phone='9000000001', contracted_rent='7500.00'):
        with tenant_context(self.tenant.id):
            resident = Resident.objects.create(
                tenant_id=self.tenant.id,
                property=self.property,
                first_name=first_name,
                last_name='Kumar',
                phone=phone,
                email='ravi@example.com',
                status=Resident.Status.ACTIVE,
            )
            admission = Admission.objects.create(
                tenant_id=self.tenant.id,
                resident=resident,
                bed=bed,
                joining_date=date.today(),
                billing_mode=Admission.BillingMode.MONTHLY,
                food_preference=Admission.FoodPreference.WITH_FOOD,
                contracted_sharing_type=bed.room.sharing_type,
                contracted_room_category=bed.room.category,
                contracted_rent=contracted_rent,
            )
            bed.status = Bed.Status.OCCUPIED
            bed.save(update_fields=['status'])
            allocation = Allocation.objects.create(
                tenant_id=self.tenant.id,
                resident=resident,
                allocated_bed=bed,
                contracted_sharing_type=admission.contracted_sharing_type,
                contracted_room_category=admission.contracted_room_category,
                contracted_rent=admission.contracted_rent,
            )
            return resident, allocation

    def test_receptionist_bed_detail_omits_contracted_rent_and_history(self):
        floor = self.create_floor(self.property)
        room = self.create_room(floor)
        bed = self.create_bed(room)
        self._check_in_resident(bed, contracted_rent='8000.00')

        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        response = self.client.get(reverse('bed-detail', args=[bed.id]))
        self.assertEqual(response.status_code, 200)

        # Rack rates and inventory data remain present
        self.assertIn('effective_rate_with_food', response.data)
        self.assertIn('effective_rate_without_food', response.data)

        # Current occupant is present, but rent is omitted
        occupant = response.data.get('current_occupant')
        self.assertIsNotNone(occupant)
        self.assertEqual(occupant['first_name'], 'Ravi')
        self.assertNotIn('rent', occupant)

        # History is omitted
        self.assertNotIn('history', response.data)

    def test_owner_and_manager_bed_detail_includes_rent_and_history(self):
        floor = self.create_floor(self.property)
        room = self.create_room(floor)
        bed = self.create_bed(room)
        self._check_in_resident(bed, contracted_rent='8000.00')

        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)

        for user in [self.owner, manager]:
            self.authenticate(user)
            response = self.client.get(reverse('bed-detail', args=[bed.id]))
            self.assertEqual(response.status_code, 200)

            # Contracted rent is present
            occupant = response.data.get('current_occupant')
            self.assertIsNotNone(occupant)
            self.assertEqual(occupant['rent'], '8000.00')

            # History is present with rate
            history = response.data.get('history')
            self.assertIsNotNone(history)
            self.assertGreater(len(history), 0)
            self.assertIn('rate', history[0])

    def test_receptionist_room_list_omits_bed_rent_and_history(self):
        floor = self.create_floor(self.property)
        room = self.create_room(floor)
        bed = self.create_bed(room)
        self._check_in_resident(bed, contracted_rent='8000.00')

        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        response = self.client.get(reverse('room-list'), {'floor': str(floor.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

        room_data = response.data[0]
        self.assertIn('rack_rate_with_food', room_data)
        self.assertIn('beds', room_data)
        self.assertEqual(len(room_data['beds']), 1)

        bed_data = room_data['beds'][0]
        self.assertIn('effective_rate_with_food', bed_data)

        # Occupant rent omitted
        occupant = bed_data.get('current_occupant')
        self.assertIsNotNone(occupant)
        self.assertNotIn('rent', occupant)

        # Bed history omitted
        self.assertNotIn('history', bed_data)

    def test_owner_and_manager_room_list_includes_bed_rent_and_history(self):
        floor = self.create_floor(self.property)
        room = self.create_room(floor)
        bed = self.create_bed(room)
        self._check_in_resident(bed, contracted_rent='8000.00')

        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)

        for user in [self.owner, manager]:
            self.authenticate(user)
            response = self.client.get(reverse('room-list'), {'floor': str(floor.id)})
            self.assertEqual(response.status_code, 200)

            room_data = response.data[0]
            bed_data = room_data['beds'][0]
            occupant = bed_data.get('current_occupant')
            self.assertIsNotNone(occupant)
            self.assertEqual(occupant['rent'], '8000.00')
            self.assertIn('history', bed_data)
            self.assertIn('rate', bed_data['history'][0])

