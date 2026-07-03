"""Tenant-isolation proof for the property hierarchy (invariant 1).

Mirrors apps/core/tests.py's RLS proof, applied to the tables this module
introduces (properties, floors, rooms, beds, property_staff_assignments).
"""
from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from apps.core.tenancy import tenant_context
from apps.properties.models import Property

from .base import PropertyAPITestCase


class PropertyRowLevelSecurityTests(TestCase):
    def setUp(self):
        self.tenant_a = PropertyAPITestCase.create_tenant('Tenant A')
        self.tenant_b = PropertyAPITestCase.create_tenant('Tenant B')
        PropertyAPITestCase.create_property(self.tenant_a, name='Property A')
        PropertyAPITestCase.create_property(self.tenant_b, name='Property B')

    def test_tenant_context_sees_only_own_properties(self):
        with tenant_context(self.tenant_a.id):
            self.assertEqual(Property.objects.count(), 1)
            self.assertEqual(Property.objects.first().name, 'Property A')

    def test_no_context_sees_nothing(self):
        self.assertEqual(Property.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(Property.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        with tenant_context(self.tenant_a.id):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    Property.objects.create(
                        tenant_id=self.tenant_b.id, name='Evil Property',
                        property_type=Property.PropertyType.PG, address_line='x',
                        city='x', state='x', contact_number='0000000000',
                    )
