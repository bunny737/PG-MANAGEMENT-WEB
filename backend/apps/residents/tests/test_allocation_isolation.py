"""Tenant-isolation proof for allocations (invariant 1), mirroring the
other Module 04/05 isolation tests."""
from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from apps.core.tenancy import tenant_context
from apps.residents.models import Allocation, Resident

from .base import ResidentAPITestCase


class AllocationRowLevelSecurityTests(TestCase):
    @staticmethod
    def _checked_in(tenant, name, phone):
        prop = ResidentAPITestCase.create_property(tenant, name=f'Prop {name}')
        bed = ResidentAPITestCase.create_bed(
            ResidentAPITestCase.create_room(ResidentAPITestCase.create_floor(prop))
        )
        resident = ResidentAPITestCase.create_resident(
            prop, first_name=name, phone=phone, status=Resident.Status.RESERVED
        )
        return ResidentAPITestCase.check_in(resident, bed)

    def setUp(self):
        self.tenant_a = ResidentAPITestCase.create_tenant('Tenant A')
        self.tenant_b = ResidentAPITestCase.create_tenant('Tenant B')
        self._checked_in(self.tenant_a, 'Resident A', '9000000001')
        self._checked_in(self.tenant_b, 'Resident B', '9000000002')

    def test_tenant_context_sees_only_own_allocations(self):
        with tenant_context(self.tenant_a.id):
            self.assertEqual(Allocation.objects.count(), 1)

    def test_no_context_sees_nothing(self):
        self.assertEqual(Allocation.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(Allocation.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        with tenant_context(self.tenant_a.id):
            prop = ResidentAPITestCase.create_property(self.tenant_a, name='Prop Evil')
            bed = ResidentAPITestCase.create_bed(
                ResidentAPITestCase.create_room(ResidentAPITestCase.create_floor(prop))
            )
            resident = ResidentAPITestCase.create_resident(
                prop, first_name='Evil', phone='9000000099', status=Resident.Status.RESERVED
            )
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    Allocation.objects.create(
                        tenant_id=self.tenant_b.id, resident=resident, allocated_bed=bed,
                        contracted_sharing_type=1, contracted_room_category='ac',
                        contracted_rent='5000.00',
                    )
