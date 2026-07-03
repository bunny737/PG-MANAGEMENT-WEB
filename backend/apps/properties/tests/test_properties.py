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

    def test_property_has_no_delete_endpoint(self):
        prop = self.create_property(self.tenant)
        self.authenticate(self.owner)
        response = self.client.delete(reverse('property-detail', args=[prop.id]))
        self.assertEqual(response.status_code, 405)
