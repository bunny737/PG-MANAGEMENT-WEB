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
