from decimal import Decimal

from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.properties.models import Bed, Room
from apps.residents.models import Resident

from .base import ResidentAPITestCase


def admission_payload(resident, bed, **overrides):
    payload = {
        'resident': str(resident.id),
        'bed': str(bed.id),
        'joining_date': '2026-07-01',
        'billing_mode': 'monthly',
        'food_preference': 'with_food',
        'advance_amount': '1500.00',
    }
    payload.update(overrides)
    return payload


class AdmissionTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(
            self.floor, sharing_type=Room.SharingType.ONE, category=Room.Category.AC,
            rack_rate_with_food=Decimal('7000.00'), rack_rate_without_food=Decimal('5500.00'),
        )
        self.bed = self.create_bed(self.room)
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)

    def test_owner_admits_resident_checks_in_bed_and_activates_resident(self):
        self.authenticate(self.owner)

        response = self.client.post(reverse('admission-list'), admission_payload(self.resident, self.bed))

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['contracted_rent'], '7000.00')
        self.assertEqual(response.data['contracted_sharing_type'], 1)
        self.assertEqual(response.data['contracted_room_category'], 'ac')

        with tenant_context(self.tenant.id):
            self.bed.refresh_from_db()
            self.room.refresh_from_db()
            self.resident.refresh_from_db()
        self.assertEqual(self.bed.status, Bed.Status.OCCUPIED)
        self.assertEqual(self.room.status, Room.Status.OCCUPIED)
        self.assertEqual(self.resident.status, Resident.Status.ACTIVE)

    def test_without_food_preference_uses_without_food_rate(self):
        self.authenticate(self.owner)

        response = self.client.post(
            reverse('admission-list'), admission_payload(self.resident, self.bed, food_preference='without_food')
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['contracted_rent'], '5500.00')

    def test_bed_rack_rate_override_takes_precedence(self):
        with tenant_context(self.tenant.id):
            self.bed.rack_rate_with_food_override = Decimal('6500.00')
            self.bed.save()
        self.authenticate(self.owner)

        response = self.client.post(reverse('admission-list'), admission_payload(self.resident, self.bed))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['contracted_rent'], '6500.00')

    def test_cannot_admit_resident_who_is_not_reserved(self):
        inquiry_resident = self.create_resident(self.property, phone='9000000002')  # default: inquiry
        self.authenticate(self.owner)

        response = self.client.post(reverse('admission-list'), admission_payload(inquiry_resident, self.bed))

        self.assertEqual(response.status_code, 400)
        self.assertIn('resident', response.data)

    def test_cannot_admit_into_an_occupied_bed(self):
        with tenant_context(self.tenant.id):
            self.bed.status = Bed.Status.OCCUPIED
            self.bed.save()
        self.authenticate(self.owner)

        response = self.client.post(reverse('admission-list'), admission_payload(self.resident, self.bed))

        self.assertEqual(response.status_code, 400)
        self.assertIn('bed', response.data)

    def test_cannot_admit_into_a_bed_of_a_different_property(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        other_floor = self.create_floor(other_property)
        other_room = self.create_room(other_floor)
        other_bed = self.create_bed(other_room)
        self.authenticate(self.owner)

        response = self.client.post(reverse('admission-list'), admission_payload(self.resident, other_bed))

        self.assertEqual(response.status_code, 400)
        self.assertIn('bed', response.data)

    def test_contracted_rent_is_immune_to_later_rack_rate_changes(self):
        self.authenticate(self.owner)
        create_response = self.client.post(reverse('admission-list'), admission_payload(self.resident, self.bed))
        admission_id = create_response.data['id']

        with tenant_context(self.tenant.id):
            self.room.rack_rate_with_food = Decimal('9999.00')
            self.room.save()

        detail = self.client.get(reverse('admission-detail', args=[admission_id]))
        self.assertEqual(detail.data['contracted_rent'], '7000.00')

    def test_admission_has_no_update_or_delete_endpoint(self):
        self.authenticate(self.owner)
        create_response = self.client.post(reverse('admission-list'), admission_payload(self.resident, self.bed))
        admission_id = create_response.data['id']

        detail_url = reverse('admission-detail', args=[admission_id])
        self.assertEqual(self.client.patch(detail_url, {'advance_amount': '2000.00'}).status_code, 405)
        self.assertEqual(self.client.delete(detail_url).status_code, 405)

    def test_receptionist_cannot_view_or_create_admissions(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        self.assertEqual(self.client.get(reverse('admission-list')).status_code, 403)
        self.assertEqual(
            self.client.post(reverse('admission-list'), admission_payload(self.resident, self.bed)).status_code, 403
        )

    def test_manager_can_only_admit_into_assigned_properties(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        other_floor = self.create_floor(other_property)
        other_room = self.create_room(other_floor)
        other_bed = self.create_bed(other_room)
        other_resident = self.create_resident(
            other_property, phone='9000000003', status=Resident.Status.RESERVED
        )
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)  # not assigned to other_property
        self.authenticate(manager)

        ok = self.client.post(reverse('admission-list'), admission_payload(self.resident, self.bed))
        self.assertEqual(ok.status_code, 201)

        blocked = self.client.post(
            reverse('admission-list'), admission_payload(other_resident, other_bed)
        )
        self.assertEqual(blocked.status_code, 400)

    def test_admission_and_status_change_are_audit_logged(self):
        self.authenticate(self.owner)

        response = self.client.post(reverse('admission-list'), admission_payload(self.resident, self.bed))

        with tenant_context(self.tenant.id):
            self.assertTrue(
                AuditLog.objects.filter(action='admission.created', object_id=response.data['id']).exists()
            )
            status_entry = AuditLog.objects.get(
                action='resident.status_changed', object_id=str(self.resident.id)
            )
        self.assertEqual(status_entry.before['status'], 'reserved')
        self.assertEqual(status_entry.after['status'], 'active')
