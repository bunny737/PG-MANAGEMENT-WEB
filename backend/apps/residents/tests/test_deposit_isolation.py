"""Tenant-isolation proof for Vacate/AbscondedRecord/BlacklistEntry (invariant 1)."""
from datetime import date

from django.db import transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from apps.core.tenancy import tenant_context
from apps.residents.models import AbscondedRecord, BlacklistEntry, Resident, Vacate

from .base import ResidentAPITestCase


class DepositRowLevelSecurityTests(TestCase):
    @staticmethod
    def _resident(tenant, phone, status):
        prop = ResidentAPITestCase.create_property(tenant, name=f'Prop {phone}')
        room = ResidentAPITestCase.create_room(ResidentAPITestCase.create_floor(prop))
        bed = ResidentAPITestCase.create_bed(room)
        resident = ResidentAPITestCase.create_resident(prop, phone=phone, status=Resident.Status.RESERVED)
        ResidentAPITestCase.check_in(resident, bed)
        with tenant_context(tenant.id):
            resident.status = status
            resident.save(update_fields=['status', 'updated_at'])
        return resident

    def setUp(self):
        self.tenant_a = ResidentAPITestCase.create_tenant('Tenant A')
        self.tenant_b = ResidentAPITestCase.create_tenant('Tenant B')
        self.resident_a = self._resident(self.tenant_a, '9000000001', Resident.Status.NOTICE_PERIOD)
        self.resident_b = self._resident(self.tenant_b, '9000000002', Resident.Status.NOTICE_PERIOD)

        with tenant_context(self.tenant_a.id):
            self.vacate_a = Vacate.objects.create(
                tenant_id=self.tenant_a.id, resident=self.resident_a,
                notice_given_date=date(2026, 7, 1), expected_vacate_date=date(2026, 8, 1),
            )
            self.absconded_a = AbscondedRecord.objects.create(
                tenant_id=self.tenant_a.id, resident=self.resident_a, absconded_date=date(2026, 7, 1),
                advance_applied_to_dues='0.00', remaining_dues='0.00',
            )
            self.blacklist_a = BlacklistEntry.objects.create(
                tenant_id=self.tenant_a.id, resident=self.resident_a, phone=self.resident_a.phone,
            )
        with tenant_context(self.tenant_b.id):
            Vacate.objects.create(
                tenant_id=self.tenant_b.id, resident=self.resident_b,
                notice_given_date=date(2026, 7, 1), expected_vacate_date=date(2026, 8, 1),
            )
            AbscondedRecord.objects.create(
                tenant_id=self.tenant_b.id, resident=self.resident_b, absconded_date=date(2026, 7, 1),
                advance_applied_to_dues='0.00', remaining_dues='0.00',
            )
            BlacklistEntry.objects.create(
                tenant_id=self.tenant_b.id, resident=self.resident_b, phone=self.resident_b.phone,
            )

    def test_tenant_context_sees_only_own_rows(self):
        with tenant_context(self.tenant_a.id):
            self.assertEqual(Vacate.objects.count(), 1)
            self.assertEqual(AbscondedRecord.objects.count(), 1)
            self.assertEqual(BlacklistEntry.objects.count(), 1)

    def test_no_context_sees_nothing(self):
        self.assertEqual(Vacate.objects.count(), 0)
        self.assertEqual(AbscondedRecord.objects.count(), 0)
        self.assertEqual(BlacklistEntry.objects.count(), 0)

    def test_super_admin_context_sees_all_tenants(self):
        with tenant_context(is_super_admin=True):
            self.assertEqual(Vacate.objects.count(), 2)
            self.assertEqual(AbscondedRecord.objects.count(), 2)
            self.assertEqual(BlacklistEntry.objects.count(), 2)

    def test_cross_tenant_write_is_rejected_by_database(self):
        with tenant_context(self.tenant_a.id):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    BlacklistEntry.objects.create(
                        tenant_id=self.tenant_b.id, resident=self.resident_a, phone='0000000000',
                    )
