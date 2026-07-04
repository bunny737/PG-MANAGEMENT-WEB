from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context

from .base import SubscriptionAPITestCase


class SelectPlanTests(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.subscription = self.create_subscription(self.tenant)
        self.plan = self.create_plan(name='Growth')
        self.authenticate(self.owner)

    def _select(self, plan):
        return self.client.post(reverse('subscription-select-plan', args=[self.tenant.id]), {'plan': str(plan.id)})

    def test_select_plan_stamps_plan_and_razorpay_ids(self):
        response = self._select(self.plan)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['plan']['name'], 'Growth')
        self.assertTrue(response.data['razorpay_subscription_id'].startswith('test_sub_'))

    def test_select_plan_does_not_immediately_activate_tenant(self):
        # Activation happens on webhook confirmation, not selection itself.
        self._select(self.plan)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, 'trial')

    def test_select_plan_is_audit_logged(self):
        self._select(self.plan)
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='subscription.plan_selected').exists())

    def test_only_active_plans_are_selectable(self):
        inactive = self.create_plan(name='Retired', is_active=False)
        response = self._select(inactive)
        self.assertEqual(response.status_code, 400)

    def test_manager_cannot_select_a_plan(self):
        manager = self.create_manager(self.tenant)
        self.authenticate(manager)
        response = self._select(self.plan)
        self.assertEqual(response.status_code, 403)
