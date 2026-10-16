"""D9 — bed availability transitions, reservations, deletion, room capacity,
and the ?property= filters on rooms/beds."""
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.properties.models import Bed
from apps.residents.models import Resident
from apps.residents.tests.base import ResidentAPITestCase


class BedTransitionTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.prop = self.create_property(self.tenant)
        self.room = self.create_room(self.create_floor(self.prop), room_number='101')
        self.bed = self.create_bed(self.room, bed_number='101-A')
        self.authenticate(self.owner)

    def patch(self, bed, **body):
        return self.client.patch(reverse('bed-detail', args=[bed.id]), body, format='json')

    def set_status(self, bed, status):
        with tenant_context(self.tenant.id):
            Bed.objects.filter(pk=bed.pk).update(status=status)

    def test_allowed_manual_transitions(self):
        for status in ('maintenance', 'available', 'reserved', 'maintenance', 'reserved', 'available'):
            response = self.patch(self.bed, status=status)
            self.assertEqual(response.status_code, 200, (status, response.data))
            self.assertEqual(response.data['status'], status)

    def test_occupied_bed_cannot_change_by_patch(self):
        self.set_status(self.bed, Bed.Status.OCCUPIED)
        for status in ('maintenance', 'reserved', 'available'):
            response = self.patch(self.bed, status=status)
            self.assertEqual(response.status_code, 409, status)
            self.assertEqual(response.data['code'], 'BED_TRANSITION_NOT_ALLOWED')

    def test_nothing_becomes_occupied_by_patch(self):
        for start in (Bed.Status.AVAILABLE, Bed.Status.RESERVED, Bed.Status.MAINTENANCE):
            self.set_status(self.bed, start)
            self.assertEqual(self.patch(self.bed, status='occupied').status_code, 409, start)

    def test_new_bed_cannot_start_occupied(self):
        response = self.client.post(reverse('bed-list'), {
            'room': str(self.room.id), 'bed_number': '101-B', 'status': 'occupied',
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['status'][0].code, 'bed_status_not_allowed')

    def test_status_change_is_audit_logged(self):
        self.patch(self.bed, status='maintenance')
        with tenant_context(self.tenant.id):
            log = AuditLog.objects.get(action='bed.status_changed')
        self.assertEqual(log.before['status'], 'available')
        self.assertEqual(log.after['status'], 'maintenance')

    def test_reservation_fields(self):
        lead = self.create_resident(self.prop, phone='9000000002', status=Resident.Status.RESERVED)
        response = self.patch(self.bed, status='reserved', reserved_for=str(lead.id), reserved_until='2026-12-01')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['reserved_for'], lead.id)
        # Leaving `reserved` clears the hold.
        response = self.patch(self.bed, status='available')
        self.assertIsNone(response.data['reserved_for'])
        self.assertIsNone(response.data['reserved_until'])

    def test_reservation_rules(self):
        lead = self.create_resident(self.prop, phone='9000000002', status=Resident.Status.RESERVED)
        def code(response):
            return response.data['reserved_for'][0].code

        self.assertEqual(code(self.patch(self.bed, reserved_for=str(lead.id))), 'bed_not_reserved')
        active = self.create_resident(self.prop, phone='9000000003', status=Resident.Status.ACTIVE)
        response = self.patch(self.bed, status='reserved', reserved_for=str(active.id))
        self.assertEqual(code(response), 'reserved_for_not_eligible')
        elsewhere = self.create_resident(
            self.create_property(self.tenant, name='Other'), phone='9000000004',
            status=Resident.Status.RESERVED,
        )
        response = self.patch(self.bed, status='reserved', reserved_for=str(elsewhere.id))
        self.assertEqual(code(response), 'reserved_for_property_mismatch')

    def test_bed_with_resident_history_cannot_be_deleted(self):
        resident = self.create_resident(self.prop, phone='9000000002', status=Resident.Status.RESERVED)
        self.check_in(resident, self.bed)
        with tenant_context(self.tenant.id):
            resident.status = Resident.Status.VACATED
            resident.save(update_fields=['status'])
        self.set_status(self.bed, Bed.Status.AVAILABLE)
        response = self.client.delete(reverse('bed-detail', args=[self.bed.id]))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'BED_HAS_HISTORY')

    def test_vacant_bed_without_history_is_deleted_and_logged(self):
        self.assertEqual(self.client.delete(reverse('bed-detail', args=[self.bed.id])).status_code, 204)
        with tenant_context(self.tenant.id):
            log = AuditLog.objects.get(action='bed.deleted')
        self.assertEqual(log.object_id, str(self.bed.id))

    def test_room_capacity_cannot_drop_below_its_beds(self):
        self.create_bed(self.room, bed_number='101-B')
        url = reverse('room-detail', args=[self.room.id])
        response = self.client.patch(url, {'sharing_type': 1})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['sharing_type'][0].code, 'room_capacity_below_beds')
        self.assertEqual(self.client.patch(url, {'sharing_type': 2}).status_code, 200)

    def test_property_filters_on_rooms_and_beds(self):
        other = self.create_property(self.tenant, name='Other')
        other_room = self.create_room(self.create_floor(other), room_number='201')
        self.create_bed(other_room, bed_number='201-A')
        rooms = self.client.get(reverse('room-list'), {'property': str(self.prop.id)}).data
        self.assertEqual([r['id'] for r in rooms], [str(self.room.id)])
        self.assertEqual(rooms[0]['property'], str(self.prop.id))
        beds = self.client.get(reverse('bed-list'), {'property': str(other.id), 'availability': 'available'}).data
        self.assertEqual([b['bed_number'] for b in beds], ['201-A'])


class AdmissionToReservedBedTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.prop = self.create_property(self.tenant)
        self.bed = self.create_bed(self.create_room(self.create_floor(self.prop)))
        self.lead = self.create_resident(self.prop, phone='9000000001', status=Resident.Status.RESERVED)
        self.other = self.create_resident(self.prop, phone='9000000002', status=Resident.Status.RESERVED)
        self.authenticate(self.owner)

    def reserve(self, resident=None):
        with tenant_context(self.tenant.id):
            Bed.objects.filter(pk=self.bed.pk).update(
                status=Bed.Status.RESERVED, reserved_for=resident,
            )

    def admit(self, resident):
        return self.client.post(reverse('admission-list'), {
            'resident': str(resident.id), 'bed': str(self.bed.id), 'joining_date': '2026-10-01',
            'billing_mode': 'monthly', 'food_preference': 'with_food',
        })

    def test_bed_held_for_this_resident_admits_and_clears_the_hold(self):
        self.reserve(self.lead)
        self.assertEqual(self.admit(self.lead).status_code, 201)
        with tenant_context(self.tenant.id):
            self.bed.refresh_from_db()
        self.assertEqual(self.bed.status, Bed.Status.OCCUPIED)
        self.assertIsNone(self.bed.reserved_for_id)

    def test_bed_held_for_someone_else_is_not_available(self):
        self.reserve(self.lead)
        response = self.admit(self.other)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['bed'][0].code, 'bed_not_available')

    def test_reserved_bed_held_for_nobody_admits_anyone(self):
        self.reserve(None)
        self.assertEqual(self.admit(self.other).status_code, 201)
