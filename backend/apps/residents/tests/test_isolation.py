"""Tenant-isolation proof for residents (invariant 1), mirroring
apps/properties/tests/test_isolation.py."""
from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from apps.core.tenancy import tenant_context
from apps.residents.models import Resident

from .base import ResidentAPITestCase


class ResidentRowLevelSecurityTests(TestCase):
    def setUp(self):
        self.tenant_a = ResidentAPITestCase.create_tenant('Tenant A')
        self.tenant_b = ResidentAPITestCase.create_tenant('Tenant B')
        property_a = ResidentAPITestCase.create_property(self.tenant_a, name='Property A')
        property_b = ResidentAPITestCase.create_property(self.tenant_b, name='Property B')
        ResidentAPITestCase.create_resident(property_a, first_name='Resident A')
        ResidentAPITestCase.create_resident(property_b, first_name='Resident B')

    def test_tenant_context_sees_only_own_residents(self):
        with tenant_context(self.tenant_a.id):
            self.assertEqual(Resident.objects.count(), 1)
            self.assertEqual(Resident.objects.first().first_name, 'Resident A')

    def test_no_context_sees_nothing(self):
        self.assertEqual(Resident.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(Resident.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        with tenant_context(self.tenant_a.id):
            property_a = Resident.objects.first().property
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    Resident.objects.create(
                        tenant_id=self.tenant_b.id, property=property_a,
                        first_name='Evil', phone='9999999999',
                    )
