from datetime import date

from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.residents.models import Resident

from .base import ResidentAPITestCase


def status_url(resident):
    return reverse('resident-status', args=[resident.id])


class ResidentStatusTransitionTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.authenticate(self.owner)

    def test_full_happy_path_lifecycle(self):
        resident = self.create_resident(self.property)

        for target in ['reserved', 'active', 'notice_period', 'vacated']:
            response = self.client.patch(status_url(resident), {'status': target})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['status'], target)

    def test_active_can_go_to_absconded_then_blacklisted(self):
        resident = self.create_resident(self.property, status=Resident.Status.ACTIVE)

        response = self.client.patch(status_url(resident), {'status': 'absconded'})
        self.assertEqual(response.status_code, 200)

        response = self.client.patch(status_url(resident), {'status': 'blacklisted'})
        self.assertEqual(response.status_code, 200)

    def test_notice_period_can_go_to_blacklisted_directly(self):
        resident = self.create_resident(self.property, status=Resident.Status.NOTICE_PERIOD)

        response = self.client.patch(status_url(resident), {'status': 'blacklisted'})

        self.assertEqual(response.status_code, 200)

    def test_cannot_skip_stages(self):
        resident = self.create_resident(self.property)  # inquiry

        response = self.client.patch(status_url(resident), {'status': 'active'})

        self.assertEqual(response.status_code, 400)

    def test_vacated_and_blacklisted_are_terminal(self):
        vacated = self.create_resident(self.property, status=Resident.Status.VACATED, phone='9000000002')
        blacklisted = self.create_resident(self.property, status=Resident.Status.BLACKLISTED, phone='9000000003')

        self.assertEqual(self.client.patch(status_url(vacated), {'status': 'active'}).status_code, 400)
        self.assertEqual(self.client.patch(status_url(blacklisted), {'status': 'active'}).status_code, 400)

    def test_active_cannot_go_directly_to_vacated(self):
        resident = self.create_resident(self.property, status=Resident.Status.ACTIVE)

        response = self.client.patch(status_url(resident), {'status': 'vacated'})

        self.assertEqual(response.status_code, 400)

    def test_status_change_writes_audit_log(self):
        resident = self.create_resident(self.property)

        self.client.patch(status_url(resident), {'status': 'reserved'})

        with tenant_context(self.tenant.id):
            entry = AuditLog.objects.get(action='resident.status_changed', object_id=str(resident.id))
        self.assertEqual(entry.before['status'], 'inquiry')
        self.assertEqual(entry.after['status'], 'reserved')

    def test_receptionist_cannot_change_status(self):
        resident = self.create_resident(self.property)
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        response = self.client.patch(status_url(resident), {'status': 'reserved'})

        self.assertEqual(response.status_code, 403)

    def test_notice_period_can_return_to_active(self):
        """Owner request 2026-10-07 — a resident may withdraw their notice.
        Allowed on this endpoint only when there is no open Vacate row to
        close (a data-fix path); the test below covers the guarded case."""
        resident = self.create_resident(self.property, status=Resident.Status.NOTICE_PERIOD)

        response = self.client.patch(status_url(resident), {'status': 'active'})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'active')

    def test_notice_period_to_active_is_blocked_while_a_vacate_is_open(self):
        """A bare flip here would leave an open Vacate attached to an Active
        resident, which give-notice then reads as 'already has a vacate
        record' — locking them out of ever giving notice again. The dedicated
        /vacates/{id}/cancel/ endpoint is the way through."""
        bed = self.create_bed(self.create_room(self.create_floor(self.property)), bed_number='101-A')
        resident = self.create_resident(self.property, status=Resident.Status.RESERVED)
        self.check_in(resident, bed)
        vacate = self.create_vacate(resident)
        with tenant_context(self.tenant.id):
            resident.status = Resident.Status.NOTICE_PERIOD
            resident.save(update_fields=['status', 'updated_at'])

        response = self.client.patch(status_url(resident), {'status': 'active'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('status', response.data)
        with tenant_context(self.tenant.id):
            resident.refresh_from_db()
            vacate.refresh_from_db()
        self.assertEqual(resident.status, Resident.Status.NOTICE_PERIOD)
        self.assertTrue(vacate.is_open)

    def test_a_settled_vacate_does_not_block_the_generic_flip(self):
        """Only an *open* vacate guards the transition. A resident whose
        earlier notice was already settled or cancelled has nothing to close."""
        bed = self.create_bed(self.create_room(self.create_floor(self.property)), bed_number='102-A')
        resident = self.create_resident(
            self.property, phone='9000000009', status=Resident.Status.RESERVED
        )
        self.check_in(resident, bed)
        self.create_vacate(resident, cancelled_date=date(2026, 7, 5))
        with tenant_context(self.tenant.id):
            resident.status = Resident.Status.NOTICE_PERIOD
            resident.save(update_fields=['status', 'updated_at'])

        response = self.client.patch(status_url(resident), {'status': 'active'})

        self.assertEqual(response.status_code, 200, response.data)
