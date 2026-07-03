"""Tenant-isolation proof for admissions (invariant 1), mirroring
apps/residents/tests/test_isolation.py."""
from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from apps.core.tenancy import tenant_context
from apps.residents.models import Admission, Resident

from .base import ResidentAPITestCase


class AdmissionRowLevelSecurityTests(TestCase):
    def setUp(self):
        self.tenant_a = ResidentAPITestCase.create_tenant('Tenant A')
        self.tenant_b = ResidentAPITestCase.create_tenant('Tenant B')

        property_a = ResidentAPITestCase.create_property(self.tenant_a, name='Property A')
        floor_a = ResidentAPITestCase.create_floor(property_a)
        room_a = ResidentAPITestCase.create_room(floor_a)
        self.bed_a = ResidentAPITestCase.create_bed(room_a)
        resident_a = ResidentAPITestCase.create_resident(
            property_a, first_name='Resident A', status=Resident.Status.RESERVED
        )
        ResidentAPITestCase.create_admission(resident_a, self.bed_a)

        property_b = ResidentAPITestCase.create_property(self.tenant_b, name='Property B')
        floor_b = ResidentAPITestCase.create_floor(property_b)
        room_b = ResidentAPITestCase.create_room(floor_b)
        bed_b = ResidentAPITestCase.create_bed(room_b)
        resident_b = ResidentAPITestCase.create_resident(
            property_b, first_name='Resident B', phone='9000000099', status=Resident.Status.RESERVED
        )
        ResidentAPITestCase.create_admission(resident_b, bed_b)

    def test_tenant_context_sees_only_own_admissions(self):
        with tenant_context(self.tenant_a.id):
            self.assertEqual(Admission.objects.count(), 1)

    def test_no_context_sees_nothing(self):
        self.assertEqual(Admission.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(Admission.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        with tenant_context(self.tenant_a.id):
            evil_resident = ResidentAPITestCase.create_resident(
                ResidentAPITestCase.create_property(self.tenant_a, name='Property A2'),
                phone='9000000098', status=Resident.Status.RESERVED,
            )
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    Admission.objects.create(
                        tenant_id=self.tenant_b.id, resident=evil_resident, bed=self.bed_a,
                        joining_date='2026-07-01', billing_mode=Admission.BillingMode.MONTHLY,
                        food_preference=Admission.FoodPreference.WITH_FOOD,
                        contracted_sharing_type=1, contracted_room_category='ac',
                        contracted_rent='5000.00',
                    )
