"""Tenant-isolation proof for SubscriptionPayment (invariant 1) — the only
RLS-scoped table in this module. `Plan`/`Subscription` are deliberately not
under RLS; see the Module 13 spec's Decisions."""
from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from apps.core.tenancy import tenant_context
from apps.subscriptions.models import SubscriptionPayment

from .base import SubscriptionAPITestCase


class SubscriptionPaymentRowLevelSecurityTests(TestCase):
    @staticmethod
    def _payment(tenant_name):
        tenant = SubscriptionAPITestCase.create_tenant(tenant_name)
        subscription = SubscriptionAPITestCase.create_subscription(tenant)
        with tenant_context(tenant.id):
            return SubscriptionPayment.objects.create(
                tenant_id=tenant.id, subscription=subscription, amount='199.00',
                status=SubscriptionPayment.Status.SUCCESS,
            )

    def setUp(self):
        self.payment_a = self._payment('Tenant A')
        self._payment('Tenant B')

    def test_tenant_context_sees_only_own_payments(self):
        with tenant_context(self.payment_a.tenant_id):
            self.assertEqual(SubscriptionPayment.objects.count(), 1)

    def test_no_context_sees_nothing(self):
        self.assertEqual(SubscriptionPayment.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(SubscriptionPayment.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        other_tenant = SubscriptionAPITestCase.create_tenant('Tenant C')
        with tenant_context(self.payment_a.tenant_id):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    SubscriptionPayment.objects.create(
                        tenant_id=other_tenant.id, subscription=self.payment_a.subscription,
                        amount='1.00', status=SubscriptionPayment.Status.SUCCESS,
                    )
