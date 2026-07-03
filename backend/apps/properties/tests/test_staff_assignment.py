from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context

from .base import PropertyAPITestCase


class StaffPropertyAssignmentTests(PropertyAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.manager = self.create_manager(self.tenant)

    def test_owner_assigns_manager_and_it_is_audit_logged(self):
        self.authenticate(self.owner)

        response = self.client.post(reverse('property-staff-assignment-list'), {
            'staff': str(self.manager.id), 'property': str(self.property.id),
        })

        self.assertEqual(response.status_code, 201)
        with tenant_context(self.tenant.id):
            self.assertTrue(
                AuditLog.objects.filter(action='property_staff_assignment.created').exists()
            )

    def test_manager_cannot_assign_staff(self):
        self.authenticate(self.manager)
        response = self.client.post(reverse('property-staff-assignment-list'), {
            'staff': str(self.manager.id), 'property': str(self.property.id),
        })
        self.assertEqual(response.status_code, 403)

    def test_assigned_manager_sees_only_assigned_property(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        self.assign_staff(self.manager, self.property)

        self.authenticate(self.manager)
        response = self.client.get(reverse('property-list'))

        names = {row['name'] for row in response.data}
        self.assertEqual(names, {self.property.name})
        self.assertNotIn(other_property.name, names)

    def test_removing_assignment_revokes_access(self):
        assignment = self.assign_staff(self.manager, self.property)
        self.authenticate(self.owner)

        response = self.client.delete(
            reverse('property-staff-assignment-detail', args=[assignment.id])
        )
        self.assertEqual(response.status_code, 204)

        self.authenticate(self.manager)
        detail = self.client.get(reverse('property-detail', args=[self.property.id]))
        self.assertEqual(detail.status_code, 404)

    def test_cannot_assign_owner_role_as_staff(self):
        self.authenticate(self.owner)
        response = self.client.post(reverse('property-staff-assignment-list'), {
            'staff': str(self.owner.id), 'property': str(self.property.id),
        })
        self.assertEqual(response.status_code, 400)

    def test_cannot_assign_staff_from_another_tenant(self):
        other_tenant = self.create_tenant('Other PG')
        foreign_manager = self.create_user(other_tenant, Role.MANAGER, 'foreign-manager@example.com')
        self.authenticate(self.owner)

        response = self.client.post(reverse('property-staff-assignment-list'), {
            'staff': str(foreign_manager.id), 'property': str(self.property.id),
        })
        self.assertEqual(response.status_code, 400)
