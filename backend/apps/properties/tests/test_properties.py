from decimal import Decimal

from django.urls import reverse

from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.audit.models import AuditLog

from .base import PropertyAPITestCase


def property_payload(**overrides):
    payload = {
        'name': 'Sunrise PG - Madhapur',
        'property_type': 'pg',
        'address_line': '12 Main Road',
        'city': 'Hyderabad',
        'state': 'Telangana',
        'contact_number': '9999999999',
    }
    payload.update(overrides)
    return payload


class PropertyManagementTests(PropertyAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)

    def test_owner_creates_property_and_it_is_audit_logged(self):
        self.authenticate(self.owner)
        response = self.client.post(reverse('property-list'), property_payload())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['floors_count'], 0)
        self.assertEqual(response.data['status'], 'active')
        with tenant_context(self.tenant.id):
            self.assertTrue(
                AuditLog.objects.filter(action='property.created', tenant_id=self.tenant.id).exists()
            )

    def test_manager_and_receptionist_cannot_create_property(self):
        for role, email in [(Role.MANAGER, 'manager@example.com'), (Role.RECEPTIONIST, 'reception@example.com')]:
            user = self.create_user(self.tenant, role, email)
            self.authenticate(user)
            response = self.client.post(reverse('property-list'), property_payload())
            self.assertEqual(response.status_code, 403)

    def test_resident_cannot_list_properties(self):
        resident = self.create_user(self.tenant, Role.RESIDENT, 'resident@example.com')
        self.authenticate(resident)
        self.assertEqual(self.client.get(reverse('property-list')).status_code, 403)

    def test_owner_sees_all_tenant_properties(self):
        prop_a = self.create_property(self.tenant, name='Property A')
        prop_b = self.create_property(self.tenant, name='Property B')
        self.authenticate(self.owner)

        response = self.client.get(reverse('property-list'))

        names = {row['name'] for row in response.data}
        self.assertEqual(names, {prop_a.name, prop_b.name})

    def test_manager_sees_only_assigned_properties(self):
        assigned = self.create_property(self.tenant, name='Assigned Property')
        unassigned = self.create_property(self.tenant, name='Unassigned Property')
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, assigned)

        self.authenticate(manager)
        response = self.client.get(reverse('property-list'))
        names = {row['name'] for row in response.data}
        self.assertEqual(names, {assigned.name})

        detail = self.client.get(reverse('property-detail', args=[unassigned.id]))
        self.assertEqual(detail.status_code, 404)

    def test_property_status_change_writes_before_after_audit_log(self):
        prop = self.create_property(self.tenant)
        self.authenticate(self.owner)

        response = self.client.patch(reverse('property-detail', args=[prop.id]), {'status': 'inactive'})

        self.assertEqual(response.status_code, 200)
        with tenant_context(self.tenant.id):
            entry = AuditLog.objects.get(action='property.updated', object_id=str(prop.id))
        self.assertEqual(entry.before['status'], 'active')
        self.assertEqual(entry.after['status'], 'inactive')

    def test_property_detail_is_tenant_scoped(self):
        prop = self.create_property(self.tenant)
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')

        self.authenticate(other_owner)
        response = self.client.get(reverse('property-detail', args=[prop.id]))
        self.assertEqual(response.status_code, 404)

    def test_create_without_coordinates_returns_them_as_null(self):
        self.authenticate(self.owner)
        response = self.client.post(reverse('property-list'), property_payload(), format='json')

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data['latitude'])
        self.assertIsNone(response.data['longitude'])
        self.assertEqual(response.data['pincode'], '')
        self.assertEqual(response.data['gender_preference'], 'unisex')

    def test_create_with_app_payload_stores_every_field(self):
        self.authenticate(self.owner)
        response = self.client.post(reverse('property-list'), property_payload(
            property_type='hostel', gender_preference='female', pincode='500081',
            latitude=17.385044, longitude=78.486671,
        ), format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['property_type'], 'hostel')
        self.assertEqual(response.data['gender_preference'], 'female')
        self.assertEqual(response.data['pincode'], '500081')
        self.assertEqual(response.data['latitude'], '17.385044')
        self.assertEqual(response.data['longitude'], '78.486671')

    def test_list_and_detail_expose_coordinates(self):
        prop = self.create_property(self.tenant, latitude=Decimal('17.385044'), longitude=Decimal('78.486671'))
        self.authenticate(self.owner)

        listed = self.client.get(reverse('property-list')).data[0]
        detail = self.client.get(reverse('property-detail', args=[prop.id])).data

        for row in (listed, detail):
            self.assertEqual(row['latitude'], '17.385044')
            self.assertEqual(row['longitude'], '78.486671')

    def test_unrelated_patch_leaves_coordinates_untouched(self):
        prop = self.create_property(self.tenant, latitude=Decimal('17.385044'), longitude=Decimal('78.486671'))
        self.authenticate(self.owner)

        response = self.client.patch(reverse('property-detail', args=[prop.id]), {'city': 'Pune'}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['city'], 'Pune')
        self.assertEqual(response.data['latitude'], '17.385044')
        self.assertEqual(response.data['longitude'], '78.486671')

    def test_patch_sets_then_clears_coordinates(self):
        prop = self.create_property(self.tenant)
        url = reverse('property-detail', args=[prop.id])
        self.authenticate(self.owner)

        response = self.client.patch(url, {'latitude': 17.385044, 'longitude': 78.486671}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['latitude'], '17.385044')

        response = self.client.patch(url, {'latitude': None, 'longitude': None}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['latitude'])
        self.assertIsNone(response.data['longitude'])

    def test_patch_with_one_coordinate_is_rejected(self):
        unpinned = self.create_property(self.tenant, name='Unpinned')
        pinned = self.create_property(
            self.tenant, name='Pinned', latitude=Decimal('17.385044'), longitude=Decimal('78.486671'),
        )
        self.authenticate(self.owner)

        # Setting one half on an unpinned row, and clearing one half of a pin.
        response = self.client.patch(
            reverse('property-detail', args=[unpinned.id]), {'latitude': 17.385044}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('longitude', response.data)

        response = self.client.patch(
            reverse('property-detail', args=[pinned.id]), {'longitude': None}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('longitude', response.data)

    def test_out_of_range_or_over_precise_coordinates_are_rejected(self):
        prop = self.create_property(self.tenant)
        url = reverse('property-detail', args=[prop.id])
        self.authenticate(self.owner)

        for payload, field in [
            ({'latitude': 90.5, 'longitude': 78.486671}, 'latitude'),
            ({'latitude': 17.385044, 'longitude': -180.5}, 'longitude'),
            ({'latitude': 17.3850441, 'longitude': 78.486671}, 'latitude'),
        ]:
            response = self.client.patch(url, payload, format='json')
            self.assertEqual(response.status_code, 400, payload)
            self.assertIn(field, response.data)

    def test_pincode_is_validated_only_when_written(self):
        prop = self.create_property(self.tenant)
        url = reverse('property-detail', args=[prop.id])
        self.authenticate(self.owner)

        for bad in ('012345', '50008', '5000811', '50008a'):
            response = self.client.patch(url, {'pincode': bad}, format='json')
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn('pincode', response.data)

        # A row with no pincode still accepts an unrelated edit.
        self.assertEqual(self.client.patch(url, {'city': 'Pune'}, format='json').status_code, 200)
        self.assertEqual(self.client.patch(url, {'pincode': '500081'}, format='json').data['pincode'], '500081')

    def test_manager_can_edit_assigned_property_only(self):
        assigned = self.create_property(self.tenant, name='Assigned Property')
        unassigned = self.create_property(self.tenant, name='Unassigned Property')
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, assigned)
        self.authenticate(manager)

        response = self.client.patch(
            reverse('property-detail', args=[assigned.id]),
            {'city': 'Pune', 'latitude': 17.385044, 'longitude': 78.486671}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['city'], 'Pune')

        response = self.client.patch(
            reverse('property-detail', args=[unassigned.id]), {'city': 'Pune'}, format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_manager_cannot_change_property_status(self):
        prop = self.create_property(self.tenant)
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, prop)
        self.authenticate(manager)
        url = reverse('property-detail', args=[prop.id])

        response = self.client.patch(url, {'status': 'inactive'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertIn('detail', response.data)
        # Echoing the current status back is not a status change.
        self.assertEqual(self.client.patch(url, {'status': 'active'}, format='json').status_code, 200)

    def test_receptionist_cannot_edit_property(self):
        prop = self.create_property(self.tenant)
        receptionist = self.create_user(self.tenant, Role.RECEPTIONIST, 'reception@example.com')
        self.assign_staff(receptionist, prop)
        self.authenticate(receptionist)

        response = self.client.patch(reverse('property-detail', args=[prop.id]), {'city': 'Pune'}, format='json')

        self.assertEqual(response.status_code, 403)
        self.assertIn('detail', response.data)

    def test_cannot_patch_another_tenants_property(self):
        prop = self.create_property(self.tenant)
        other_owner = self.create_owner(self.create_tenant('Other PG'), email='other-owner@example.com')
        self.authenticate(other_owner)

        response = self.client.patch(
            reverse('property-detail', args=[prop.id]),
            {'latitude': 17.385044, 'longitude': 78.486671}, format='json',
        )

        self.assertEqual(response.status_code, 404)
        with tenant_context(self.tenant.id):
            prop.refresh_from_db()
        self.assertIsNone(prop.latitude)

    def test_coordinate_change_is_audit_logged(self):
        prop = self.create_property(self.tenant)
        self.authenticate(self.owner)

        self.client.patch(
            reverse('property-detail', args=[prop.id]),
            {'latitude': 17.385044, 'longitude': 78.486671}, format='json',
        )

        with tenant_context(self.tenant.id):
            entry = AuditLog.objects.get(action='property.updated', object_id=str(prop.id))
        self.assertIsNone(entry.before['latitude'])
        self.assertEqual(entry.after['latitude'], '17.385044')

    def test_property_has_no_delete_endpoint(self):
        prop = self.create_property(self.tenant)
        self.authenticate(self.owner)
        response = self.client.delete(reverse('property-detail', args=[prop.id]))
        self.assertEqual(response.status_code, 405)
