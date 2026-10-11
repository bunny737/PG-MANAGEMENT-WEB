from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.properties.models import Building

from .base import PropertyAPITestCase


class BuildingTests(PropertyAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)

    def test_property_creation_auto_provisions_a_default_building(self):
        self.authenticate(self.owner)
        response = self.client.post(reverse('property-list'), {
            'name': 'Green Valley PG', 'property_type': 'pg', 'address_line': '1 Main Road',
            'city': 'Hyderabad', 'state': 'Telangana', 'contact_number': '9999999999',
        })
        self.assertEqual(response.status_code, 201)

        buildings = self.client.get(reverse('building-list'), {'property': response.data['id']})
        names = [row['name'] for row in buildings.data]
        self.assertEqual(names, ['Main Building'])
        self.assertEqual(response.data['buildings_count'], 1)

    def test_owner_adds_a_second_building_for_a_multi_block_property(self):
        self.authenticate(self.owner)

        resp_a = self.client.post(reverse('building-list'), {'property': str(self.property.id), 'name': 'Block A'})
        self.assertEqual(resp_a.status_code, 201)
        # order auto-increments after the auto-provisioned "Main Building" (order 0)
        self.assertEqual(resp_a.data['order'], 1)

        resp_b = self.client.post(reverse('building-list'), {'property': str(self.property.id), 'name': 'Block B'})
        self.assertEqual(resp_b.status_code, 201)
        self.assertEqual(resp_b.data['order'], 2)

    def test_number_of_floors_auto_creates_named_floors(self):
        self.authenticate(self.owner)

        response = self.client.post(reverse('building-list'), {
            'property': str(self.property.id), 'name': 'Block A', 'number_of_floors': 3,
        })

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['floors_count'], 3)

        floors = self.client.get(reverse('floor-list'), {'building': response.data['id']})
        floor_names = sorted((f['order'], f['name']) for f in floors.data)
        self.assertEqual(floor_names, [(0, 'Ground Floor'), (1, '1st Floor'), (2, '2nd Floor')])

    def test_manager_cannot_add_building_to_unassigned_property(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)  # not assigned to other_property
        self.authenticate(manager)

        response = self.client.post(
            reverse('building-list'), {'property': str(other_property.id), 'name': 'Block A'}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('property', response.data)

    def test_receptionist_can_view_buildings_of_assigned_property(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        response = self.client.get(reverse('building-list'), {'property': str(self.property.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

        with tenant_context(self.tenant.id):
            building = Building.objects.get(property=self.property)
        detail_resp = self.client.get(reverse('building-detail', args=[building.id]))
        self.assertEqual(detail_resp.status_code, 200)

    def test_receptionist_cannot_view_buildings_of_unassigned_property(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)  # not other_property
        self.authenticate(receptionist)

        response = self.client.get(reverse('building-list'), {'property': str(other_property.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 0)

        with tenant_context(self.tenant.id):
            other_bldg = Building.objects.get(property=other_property)
        detail_resp = self.client.get(reverse('building-detail', args=[other_bldg.id]))
        self.assertEqual(detail_resp.status_code, 404)

    def test_receptionist_cannot_create_update_or_delete_building(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        with tenant_context(self.tenant.id):
            building = Building.objects.get(property=self.property)

        # POST
        create_resp = self.client.post(reverse('building-list'), {'property': str(self.property.id), 'name': 'Block B'})
        self.assertEqual(create_resp.status_code, 403)

        # PATCH
        patch_resp = self.client.patch(reverse('building-detail', args=[building.id]), {'name': 'New Name'})
        self.assertEqual(patch_resp.status_code, 403)

        # DELETE
        delete_resp = self.client.delete(reverse('building-detail', args=[building.id]))
        self.assertEqual(delete_resp.status_code, 403)

    def test_cannot_delete_building_with_floors(self):
        self.authenticate(self.owner)
        with tenant_context(self.tenant.id):
            building = Building.objects.get(property=self.property)  # auto-provisioned default
        self.create_floor(self.property)

        response = self.client.delete(reverse('building-detail', args=[building.id]))
        self.assertEqual(response.status_code, 400)

    def test_can_delete_empty_building(self):
        self.authenticate(self.owner)
        response = self.client.post(reverse('building-list'), {'property': str(self.property.id), 'name': 'Block A'})
        self.assertEqual(response.status_code, 201)

        delete_resp = self.client.delete(reverse('building-detail', args=[response.data['id']]))
        self.assertEqual(delete_resp.status_code, 204)
