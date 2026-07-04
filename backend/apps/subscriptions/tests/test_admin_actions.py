from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context

from .base import SubscriptionAPITestCase


class OverrideLimitsTests(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.super_admin = self.create_super_admin()
        self.subscription = self.create_subscription(self.tenant)

    def _override(self, **data):
        return self.client.patch(reverse('subscription-override-limits', args=[self.tenant.id]), data)

    def test_super_admin_can_override_limits(self):
        self.authenticate(self.super_admin)
        response = self._override(max_properties_override=5)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['max_properties_override'], 5)

    def test_owner_cannot_override_limits(self):
        self.authenticate(self.owner)
        response = self._override(max_properties_override=5)
        self.assertEqual(response.status_code, 403)

    def test_override_is_partial(self):
        self.subscription.max_residents_override = 20
        self.subscription.save()
        self.authenticate(self.super_admin)

        response = self._override(max_properties_override=5)

        self.assertEqual(response.data['max_properties_override'], 5)
        self.assertEqual(response.data['max_residents_override'], 20)

    def test_override_is_audit_logged(self):
        self.authenticate(self.super_admin)
        self._override(max_properties_override=5)
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='subscription.limits_overridden').exists())


class SuspendReactivateTests(SubscriptionAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.super_admin = self.create_super_admin()
        self.subscription = self.create_subscription(self.tenant)

    def test_super_admin_can_suspend_a_tenant(self):
        self.authenticate(self.super_admin)
        response = self.client.post(reverse('subscription-suspend', args=[self.tenant.id]))

        self.assertEqual(response.status_code, 200, response.data)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, 'suspended')

    def test_cannot_suspend_an_already_suspended_tenant(self):
        self.tenant.status = 'suspended'
        self.tenant.save()
        self.authenticate(self.super_admin)

        response = self.client.post(reverse('subscription-suspend', args=[self.tenant.id]))
        self.assertEqual(response.status_code, 400)

    def test_owner_cannot_suspend(self):
        self.authenticate(self.owner)
        response = self.client.post(reverse('subscription-suspend', args=[self.tenant.id]))
        self.assertEqual(response.status_code, 403)

    def test_super_admin_can_reactivate_a_suspended_tenant(self):
        self.tenant.status = 'suspended'
        self.tenant.save()
        self.authenticate(self.super_admin)

        response = self.client.post(reverse('subscription-reactivate', args=[self.tenant.id]))

        self.assertEqual(response.status_code, 200, response.data)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, 'active')

    def test_cannot_reactivate_a_tenant_that_is_not_suspended(self):
        self.authenticate(self.super_admin)
        response = self.client.post(reverse('subscription-reactivate', args=[self.tenant.id]))
        self.assertEqual(response.status_code, 400)

    def test_suspend_is_audit_logged(self):
        self.authenticate(self.super_admin)
        self.client.post(reverse('subscription-suspend', args=[self.tenant.id]))
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='tenant.status_changed').exists())
