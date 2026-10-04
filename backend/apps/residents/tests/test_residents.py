from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.residents.models import Resident

from .base import ResidentAPITestCase


def resident_payload(prop, **overrides):
    payload = {'property': str(prop.id), 'first_name': 'Ravi', 'phone': '9000000001'}
    payload.update(overrides)
    return payload


class ResidentManagementTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)

    def test_owner_creates_resident_with_minimal_fields_and_it_is_audit_logged(self):
        self.authenticate(self.owner)

        response = self.client.post(reverse('resident-list'), resident_payload(self.property))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'inquiry')
        self.assertEqual(response.data['last_name'], '')
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='resident.created').exists())

    def test_manager_can_manage_residents_in_assigned_property(self):
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        response = self.client.post(reverse('resident-list'), resident_payload(self.property))

        self.assertEqual(response.status_code, 201)

    def test_manager_cannot_add_resident_to_unassigned_property(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)  # not assigned to other_property
        self.authenticate(manager)

        response = self.client.post(reverse('resident-list'), resident_payload(other_property))

        self.assertEqual(response.status_code, 400)
        self.assertIn('property', response.data)

    def test_receptionist_can_view_but_not_create_residents(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.create_resident(self.property)
        self.authenticate(receptionist)

        self.assertEqual(self.client.get(reverse('resident-list')).status_code, 200)
        self.assertEqual(
            self.client.post(reverse('resident-list'), resident_payload(self.property)).status_code, 403
        )

    def test_resident_role_has_no_access(self):
        resident_user = self.create_user(self.tenant, Role.RESIDENT, 'resident@example.com')
        self.authenticate(resident_user)
        self.assertEqual(self.client.get(reverse('resident-list')).status_code, 403)

    def test_manager_only_sees_residents_in_assigned_properties(self):
        mine = self.create_resident(self.property, first_name='Mine')
        other_property = self.create_property(self.tenant, name='Other Property')
        self.create_resident(other_property, first_name='NotMine')
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        response = self.client.get(reverse('resident-list'))
        names = {row['first_name'] for row in response.data}
        self.assertEqual(names, {mine.first_name})

    def test_resident_has_no_delete_endpoint(self):
        resident = self.create_resident(self.property)
        self.authenticate(self.owner)
        response = self.client.delete(reverse('resident-detail', args=[resident.id]))
        self.assertEqual(response.status_code, 405)

    def test_resident_detail_is_tenant_scoped(self):
        resident = self.create_resident(self.property)
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')

        self.authenticate(other_owner)
        response = self.client.get(reverse('resident-detail', args=[resident.id]))
        self.assertEqual(response.status_code, 404)

    def test_status_field_is_read_only_on_profile_update(self):
        resident = self.create_resident(self.property)
        self.authenticate(self.owner)

        response = self.client.patch(reverse('resident-detail', args=[resident.id]), {'status': 'active'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'inquiry')  # unchanged — use the status action instead


class ResidentMoneyFieldsTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room_a = self.create_room(self.floor, room_number='101')
        self.room_b = self.create_room(
            self.floor, room_number='201', rack_rate_with_food=Decimal('9000.00'),
        )
        self.bed_a = self.create_bed(self.room_a, bed_number='101-A')
        self.bed_b = self.create_bed(self.room_b, bed_number='201-A')
        self.authenticate(self.owner)

    def _admit(self, resident):
        self.check_in(
            resident, self.bed_a, advance_amount=Decimal('7000.00'),
            security_deposit_amount=Decimal('1500.00'), joining_date=date(2026, 10, 4),
        )

    def test_admitted_resident_exposes_rent_deposit_advance_room_and_bed(self):
        resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self._admit(resident)

        response = self.client.get(reverse('resident-detail', args=[resident.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['contracted_rent'], str(self.bed_a.rack_rate(with_food=True)))
        self.assertEqual(response.data['food_preference'], 'with_food')
        self.assertEqual(response.data['billing_mode'], 'monthly')
        self.assertEqual(response.data['joining_date'], '2026-10-04')
        self.assertEqual(response.data['security_deposit_amount'], '1500.00')
        self.assertEqual(response.data['advance_amount'], '7000.00')
        self.assertEqual(response.data['advance_refundable'], '7000.00')
        self.assertEqual(response.data['room_number'], '101')
        self.assertEqual(response.data['bed_number'], '101-A')

    def test_resident_without_admission_has_null_money_fields(self):
        resident = self.create_resident(self.property)

        response = self.client.get(reverse('resident-list'))

        row = next(r for r in response.data if r['id'] == str(resident.id))
        for field in ('contracted_rent', 'food_preference', 'billing_mode', 'joining_date',
                      'security_deposit_amount', 'advance_amount', 'advance_refundable',
                      'room_number', 'bed_number'):
            self.assertIsNone(row[field], field)

    def test_contracted_rent_follows_a_permanent_transfer(self):
        resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self._admit(resident)

        transfer = self.client.post(reverse('transfer-list'), {
            'resident': str(resident.id), 'new_bed': str(self.bed_b.id), 'transfer_date': '2026-10-20',
        })
        self.assertEqual(transfer.status_code, 201, transfer.data)
        response = self.client.get(reverse('resident-detail', args=[resident.id]))

        self.assertEqual(response.data['contracted_rent'], '9000.00')
        self.assertEqual(response.data['room_number'], '201')
        self.assertEqual(response.data['bed_number'], '201-A')

    def test_other_tenant_cannot_see_residents_money_fields(self):
        resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self._admit(resident)
        other_owner = self.create_owner(self.create_tenant('Other PG Co'), email='other@example.com')

        self.authenticate(other_owner)

        self.assertEqual(self.client.get(reverse('resident-detail', args=[resident.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse('resident-list')).data, [])
