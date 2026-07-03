"""Tenant-isolation proof for discounts (invariant 1), mirroring the other
modules' isolation tests."""
from datetime import date

from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from apps.core.tenancy import tenant_context
from apps.billing.models import Discount

from .base import BillingAPITestCase


class DiscountRowLevelSecurityTests(TestCase):
    def setUp(self):
        self.tenant_a = BillingAPITestCase.create_tenant('Tenant A')
        self.tenant_b = BillingAPITestCase.create_tenant('Tenant B')
        self.resident_a = BillingAPITestCase.create_resident(
            BillingAPITestCase.create_property(self.tenant_a, name='Prop A'), phone='9000000001'
        )
        resident_b = BillingAPITestCase.create_resident(
            BillingAPITestCase.create_property(self.tenant_b, name='Prop B'), phone='9000000002'
        )
        BillingAPITestCase.create_discount(self.resident_a)
        BillingAPITestCase.create_discount(resident_b)

    def test_tenant_context_sees_only_own_discounts(self):
        with tenant_context(self.tenant_a.id):
            self.assertEqual(Discount.objects.count(), 1)

    def test_no_context_sees_nothing(self):
        self.assertEqual(Discount.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(Discount.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        with tenant_context(self.tenant_a.id):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    Discount.objects.create(
                        tenant_id=self.tenant_b.id, resident=self.resident_a,
                        discount_type=Discount.DiscountType.FIXED, discount_value='500.00',
                        reason=Discount.Reason.LOYALTY, valid_from=date(2026, 7, 1),
                    )
