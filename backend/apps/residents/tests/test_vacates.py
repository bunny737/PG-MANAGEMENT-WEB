from decimal import Decimal

from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.properties.models import Bed
from apps.residents.models import Resident

from .base import ResidentAPITestCase


class VacateTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(self.floor)
        self.bed = self.create_bed(self.room, bed_number='101-A')
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.check_in(self.resident, self.bed, advance_amount=Decimal('1500.00'))
        self.authenticate(self.owner)

    def _give_notice(self, **overrides):
        payload = {'resident': str(self.resident.id), 'notice_given_date': '2026-07-01'}
        payload.update(overrides)
        return self.client.post(reverse('vacate-list'), payload)

    def test_give_notice_moves_resident_to_notice_period(self):
        response = self._give_notice()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['expected_vacate_date'], '2026-08-01')
        with tenant_context(self.tenant.id):
            self.resident.refresh_from_db()
        self.assertEqual(self.resident.status, Resident.Status.NOTICE_PERIOD)

    def test_expected_vacate_date_clamps_to_shorter_month(self):
        response = self._give_notice(notice_given_date='2026-01-31')
        self.assertEqual(response.data['expected_vacate_date'], '2026-02-28')

    def test_cannot_give_notice_for_non_active_resident(self):
        reserved = self.create_resident(self.property, phone='9000000002', status=Resident.Status.RESERVED)
        response = self._give_notice(resident=str(reserved.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn('resident', response.data)

    def test_cannot_give_notice_twice(self):
        self._give_notice()
        with tenant_context(self.tenant.id):
            self.resident.status = Resident.Status.ACTIVE
            self.resident.save(update_fields=['status', 'updated_at'])
        response = self._give_notice()
        self.assertEqual(response.status_code, 400)
        self.assertIn('resident', response.data)

    def test_give_notice_is_audit_logged(self):
        self._give_notice()
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='resident.notice_given').exists())
            self.assertTrue(AuditLog.objects.filter(action='resident.status_changed').exists())


class VacateFinalizeTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(self.floor)
        self.bed = self.create_bed(self.room, bed_number='101-A')
        self.resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.check_in(self.resident, self.bed, advance_amount=Decimal('1500.00'))
        self.authenticate(self.owner)
        self.vacate = self.client.post(reverse('vacate-list'), {
            'resident': str(self.resident.id), 'notice_given_date': '2026-07-01',
        }).data

    def _finalize(self, **overrides):
        payload = {'actual_vacate_date': '2026-08-01'}
        payload.update(overrides)
        return self.client.post(reverse('vacate-finalize', args=[self.vacate['id']]), payload)

    def test_finalize_with_zero_deduction_refunds_full_advance(self):
        response = self._finalize()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['refund_amount'], '1500.00')
        self.assertTrue(response.data['is_settled'])

        with tenant_context(self.tenant.id):
            self.resident.refresh_from_db()
            self.bed.refresh_from_db()
        self.assertEqual(self.resident.status, Resident.Status.VACATED)
        self.assertEqual(self.bed.status, Bed.Status.AVAILABLE)

    def test_finalize_with_deduction_reduces_refund(self):
        response = self._finalize(maintenance_deduction='500.00', maintenance_deduction_note='Wall damage')
        self.assertEqual(response.data['refund_amount'], '1000.00')

    def test_deduction_cannot_exceed_advance(self):
        response = self._finalize(maintenance_deduction='2000.00')
        self.assertEqual(response.status_code, 400)
        self.assertIn('maintenance_deduction', response.data)

    def test_deduction_cannot_be_negative(self):
        response = self._finalize(maintenance_deduction='-1.00')
        self.assertEqual(response.status_code, 400)
        self.assertIn('maintenance_deduction', response.data)

    def test_cannot_finalize_twice(self):
        self._finalize()
        response = self._finalize()
        self.assertEqual(response.status_code, 400)

    def test_finalize_is_audit_logged(self):
        self._finalize()
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='resident.vacated').exists())

    def test_receptionist_cannot_manage_vacates(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        self.assertEqual(self.client.get(reverse('vacate-list')).status_code, 403)
        self.assertEqual(self._finalize().status_code, 403)

    def test_manager_scoped_to_assigned_properties(self):
        other_property = self.create_property(self.tenant, name='Other Property')
        other_room = self.create_room(self.create_floor(other_property))
        other_resident = self.create_resident(other_property, phone='9000000002', status=Resident.Status.RESERVED)
        self.check_in(other_resident, self.create_bed(other_room))

        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        blocked = self.client.post(reverse('vacate-list'), {
            'resident': str(other_resident.id), 'notice_given_date': '2026-07-01',
        })
        self.assertEqual(blocked.status_code, 400)

    def test_vacate_detail_is_tenant_scoped(self):
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')
        self.authenticate(other_owner)

        response = self.client.get(reverse('vacate-detail', args=[self.vacate['id']]))
        self.assertEqual(response.status_code, 404)
