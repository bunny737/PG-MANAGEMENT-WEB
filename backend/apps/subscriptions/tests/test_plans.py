from django.urls import reverse

from .base import SubscriptionAPITestCase


class PlanTests(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.super_admin = self.create_super_admin()

    def test_super_admin_can_create_plan(self):
        self.authenticate(self.super_admin)
        response = self.client.post(reverse('plan-list'), {
            'name': 'Starter', 'max_properties': 1, 'max_residents_per_property': 10,
            'price_per_month': '199.00',
        })
        self.assertEqual(response.status_code, 201, response.data)

    def test_owner_cannot_create_plan(self):
        self.authenticate(self.owner)
        response = self.client.post(reverse('plan-list'), {
            'name': 'Starter', 'price_per_month': '199.00',
        })
        self.assertEqual(response.status_code, 403)

    def test_owner_can_list_active_plans_only(self):
        self.create_plan(name='Starter', is_active=True)
        self.create_plan(name='Retired', is_active=False)
        self.authenticate(self.owner)

        response = self.client.get(reverse('plan-list'))

        names = [p['name'] for p in response.data]
        self.assertIn('Starter', names)
        self.assertNotIn('Retired', names)

    def test_super_admin_sees_inactive_plans_too(self):
        self.create_plan(name='Retired', is_active=False)
        self.authenticate(self.super_admin)

        response = self.client.get(reverse('plan-list'))

        names = [p['name'] for p in response.data]
        self.assertIn('Retired', names)

    def test_receptionist_cannot_view_plans(self):
        receptionist = self.create_receptionist(self.tenant)
        self.authenticate(receptionist)

        response = self.client.get(reverse('plan-list'))
        self.assertEqual(response.status_code, 403)

    def test_cannot_delete_a_plan_in_use(self):
        plan = self.create_plan()
        self.create_subscription(self.tenant, plan=plan)
        self.authenticate(self.super_admin)

        response = self.client.delete(reverse('plan-detail', args=[plan.id]))
        self.assertEqual(response.status_code, 400)

    def test_can_delete_an_unused_plan(self):
        plan = self.create_plan()
        self.authenticate(self.super_admin)

        response = self.client.delete(reverse('plan-detail', args=[plan.id]))
        self.assertEqual(response.status_code, 204)
