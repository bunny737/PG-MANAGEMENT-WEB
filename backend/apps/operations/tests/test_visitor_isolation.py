"""Tenant-isolation proof for visitors (invariant 1)."""
from datetime import datetime, timezone as dt_timezone

from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from apps.core.tenancy import tenant_context
from apps.operations.models import Visitor

from .base import OperationsAPITestCase

ENTRY_TIME = datetime(2026, 7, 1, 10, 0, tzinfo=dt_timezone.utc)


class VisitorRowLevelSecurityTests(TestCase):
    @staticmethod
    def _visitor(tenant, phone):
        prop = OperationsAPITestCase.create_property(tenant, name=f'Prop {phone}')
        resident = OperationsAPITestCase.create_resident(prop, phone=phone)
        with tenant_context(tenant.id):
            return Visitor.objects.create(
                tenant_id=tenant.id, resident=resident, visitor_name='Test Visitor',
                mobile_number='9000000099', purpose='Test visit', entry_time=ENTRY_TIME,
            )

    def setUp(self):
        self.tenant_a = OperationsAPITestCase.create_tenant('Tenant A')
        self.tenant_b = OperationsAPITestCase.create_tenant('Tenant B')
        self.visitor_a = self._visitor(self.tenant_a, '9000000001')
        self._visitor(self.tenant_b, '9000000002')

    def test_tenant_context_sees_only_own_visitors(self):
        with tenant_context(self.tenant_a.id):
            self.assertEqual(Visitor.objects.count(), 1)

    def test_no_context_sees_nothing(self):
        self.assertEqual(Visitor.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(Visitor.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        with tenant_context(self.tenant_a.id):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    Visitor.objects.create(
                        tenant_id=self.tenant_b.id, resident=self.visitor_a.resident,
                        visitor_name='Evil', mobile_number='0000000000', purpose='Evil',
                        entry_time=ENTRY_TIME,
                    )
