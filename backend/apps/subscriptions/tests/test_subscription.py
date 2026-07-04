from django.urls import reverse

from apps.residents.models import Resident

from .base import SubscriptionAPITestCase


class SubscriptionRetrieveTests(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.plan = self.create_plan(max_properties=2, max_residents_per_property=3)
        self.subscription = self.create_subscription(self.tenant, plan=self.plan)

    def test_owner_can_view_own_subscription(self):
        self.authenticate(self.owner)
        response = self.client.get(reverse('subscription-detail', args=[self.tenant.id]))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['plan']['name'], self.plan.name)
        self.assertEqual(response.data['max_properties'], 2)
        self.assertEqual(response.data['max_residents_per_property'], 3)
        self.assertEqual(response.data['tenant_status'], 'trial')

    def test_usage_summary_counts_properties_and_residents(self):
        prop = self.create_property(self.tenant)
        self.create_resident(prop, status=Resident.Status.ACTIVE)
        self.authenticate(self.owner)

        response = self.client.get(reverse('subscription-detail', args=[self.tenant.id]))

        self.assertEqual(response.data['properties_used'], 1)
        usage = response.data['property_usage'][0]
        self.assertEqual(usage['residents_used'], 1)
        self.assertEqual(usage['max_residents'], 3)

    def test_non_counting_statuses_are_excluded_from_usage(self):
        prop = self.create_property(self.tenant)
        self.create_resident(prop, status=Resident.Status.INQUIRY)
        self.authenticate(self.owner)

        response = self.client.get(reverse('subscription-detail', args=[self.tenant.id]))

        self.assertEqual(response.data['property_usage'][0]['residents_used'], 0)

    def test_owner_cannot_view_another_tenants_subscription(self):
        other_tenant = self.create_tenant('Other PG')
        self.create_subscription(other_tenant)
        self.authenticate(self.owner)

        response = self.client.get(reverse('subscription-detail', args=[other_tenant.id]))
        self.assertEqual(response.status_code, 404)

    def test_super_admin_can_view_any_tenants_subscription(self):
        super_admin = self.create_super_admin()
        self.authenticate(super_admin)

        response = self.client.get(reverse('subscription-detail', args=[self.tenant.id]))
        self.assertEqual(response.status_code, 200)

    def test_manager_cannot_view_subscription(self):
        manager = self.create_manager(self.tenant)
        self.authenticate(manager)

        response = self.client.get(reverse('subscription-detail', args=[self.tenant.id]))
        self.assertEqual(response.status_code, 403)
