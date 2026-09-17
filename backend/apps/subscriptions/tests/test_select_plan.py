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

    def test_select_per_bed_plan_activates_non_active_tenants(self):
        from apps.accounts.models import Tenant
        from django.utils import timezone

        per_bed_plan = self.create_bed_plan(name='Per Bed Plan', bed_tiers=[(None, '2.00')])
        for initial_status in (Tenant.Status.TRIAL, Tenant.Status.SUSPENDED, Tenant.Status.PAYMENT_FAILED):
            tenant = self.create_tenant(status=initial_status)
            subscription = self.create_subscription(tenant, payment_failed_at=timezone.now())
            if initial_status == Tenant.Status.SUSPENDED:
                super_admin = self.create_super_admin()
                self.authenticate(super_admin)
            else:
                owner = self.create_owner(tenant, email=f'owner_{initial_status}@example.com')
                self.authenticate(owner)

            response = self.client.post(
                reverse('subscription-select-plan', args=[tenant.id]),
                {'plan': str(per_bed_plan.id)},
            )
            self.assertEqual(response.status_code, 200, response.data)
            tenant.refresh_from_db()
            subscription.refresh_from_db()
            self.assertEqual(tenant.status, Tenant.Status.ACTIVE)
            self.assertIsNone(subscription.payment_failed_at)
            with tenant_context(tenant.id):
                self.assertTrue(AuditLog.objects.filter(tenant_id=tenant.id, action='tenant.status_changed').exists())
