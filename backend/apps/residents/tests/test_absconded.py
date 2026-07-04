from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.audit.models import AuditLog
from apps.billing.models import Invoice, InvoiceLineItem
from apps.core.tenancy import tenant_context
from apps.properties.models import Bed
from apps.residents.models import Resident

from .base import ResidentAPITestCase


class AbscondedRecordTests(ResidentAPITestCase):
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

    def _issue_invoice(self, amount=Decimal('8000.00')):
        with tenant_context(self.tenant.id):
            invoice = Invoice.objects.create(
                tenant_id=self.tenant.id, resident=self.resident, period_start=date(2026, 6, 1),
                period_end=date(2026, 6, 30), billing_mode='monthly', due_date=date(2026, 6, 10),
                status=Invoice.Status.ISSUED, issue_date=date(2026, 6, 1),
            )
            InvoiceLineItem.objects.create(
                tenant_id=self.tenant.id, invoice=invoice, line_type='accommodation',
                label='Accommodation', amount=amount,
            )
            return invoice

    def _mark_absconded(self, **overrides):
        payload = {'resident': str(self.resident.id), 'absconded_date': '2026-07-01'}
        payload.update(overrides)
        return self.client.post(reverse('absconded-record-list'), payload)

    def test_marking_absconded_frees_bed_immediately(self):
        response = self._mark_absconded()

        self.assertEqual(response.status_code, 201, response.data)
        with tenant_context(self.tenant.id):
            self.resident.refresh_from_db()
            self.bed.refresh_from_db()
        self.assertEqual(self.resident.status, Resident.Status.ABSCONDED)
        self.assertEqual(self.bed.status, Bed.Status.AVAILABLE)

    def test_advance_forfeited_and_applied_against_outstanding_dues(self):
        self._issue_invoice(amount=Decimal('8000.00'))

        response = self._mark_absconded()

        self.assertEqual(response.data['advance_forfeited'], True)
        self.assertEqual(response.data['advance_applied_to_dues'], '1500.00')
        self.assertEqual(response.data['remaining_dues'], '6500.00')

    def test_advance_covers_dues_fully_when_dues_are_small(self):
        self._issue_invoice(amount=Decimal('1000.00'))

        response = self._mark_absconded()

        self.assertEqual(response.data['advance_applied_to_dues'], '1000.00')
        self.assertEqual(response.data['remaining_dues'], '0.00')

    def test_no_outstanding_invoices_means_no_dues(self):
        response = self._mark_absconded()

        self.assertEqual(response.data['advance_applied_to_dues'], '0.00')
        self.assertEqual(response.data['remaining_dues'], '0.00')

    def test_cannot_mark_non_active_resident_absconded(self):
        reserved = self.create_resident(self.property, phone='9000000002', status=Resident.Status.RESERVED)
        response = self._mark_absconded(resident=str(reserved.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn('resident', response.data)

    def test_marking_absconded_is_audit_logged(self):
        self._mark_absconded()
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='resident.absconded').exists())

    def test_receptionist_cannot_mark_absconded(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        response = self._mark_absconded()
        self.assertEqual(response.status_code, 403)


class AbscondedWriteOffTests(ResidentAPITestCase):
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
        self.record = self.client.post(reverse('absconded-record-list'), {
            'resident': str(self.resident.id), 'absconded_date': '2026-07-01',
        }).data

    def _write_off(self, note='Unable to trace resident, writing off remainder'):
        return self.client.post(
            reverse('absconded-record-write-off', args=[self.record['id']]), {'note': note}
        )

    def test_write_off_requires_a_note(self):
        response = self._write_off(note='')
        self.assertEqual(response.status_code, 400)
        self.assertIn('note', response.data)

    def test_write_off_sets_status_and_stamps_actor(self):
        response = self._write_off()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['dues_recovery_status'], 'written_off')
        self.assertEqual(response.data['dues_written_off_note'], 'Unable to trace resident, writing off remainder')

    def test_cannot_write_off_twice(self):
        self._write_off()
        response = self._write_off()
        self.assertEqual(response.status_code, 400)

    def test_write_off_is_audit_logged(self):
        self._write_off()
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='absconded.dues_written_off').exists())
