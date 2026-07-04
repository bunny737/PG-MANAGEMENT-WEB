from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.residents.models import Resident

from .base import ResidentAPITestCase


class BlacklistConfirmTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.authenticate(self.owner)

    def _confirm(self, resident, **overrides):
        payload = {'resident': str(resident.id), 'reason': 'Left without notice, dues unrecovered'}
        payload.update(overrides)
        return self.client.post(reverse('blacklist-entry-list'), payload)

    def test_confirm_blacklist_from_absconded(self):
        resident = self.create_resident(
            self.property, phone='9000000001', aadhaar_number='123456789012',
            status=Resident.Status.ABSCONDED,
        )
        response = self._confirm(resident)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['phone'], '9000000001')
        self.assertEqual(response.data['aadhaar_number'], '123456789012')
        with tenant_context(self.tenant.id):
            resident.refresh_from_db()
        self.assertEqual(resident.status, Resident.Status.BLACKLISTED)

    def test_confirm_blacklist_from_notice_period(self):
        resident = self.create_resident(self.property, status=Resident.Status.NOTICE_PERIOD)
        response = self._confirm(resident)
        self.assertEqual(response.status_code, 201, response.data)

    def test_cannot_blacklist_an_active_resident(self):
        resident = self.create_resident(self.property, status=Resident.Status.ACTIVE)
        response = self._confirm(resident)
        self.assertEqual(response.status_code, 400)
        self.assertIn('resident', response.data)

    def test_confirm_blacklist_is_audit_logged(self):
        resident = self.create_resident(self.property, status=Resident.Status.ABSCONDED)
        self._confirm(resident)
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='resident.blacklisted').exists())

    def test_receptionist_cannot_confirm_blacklist(self):
        resident = self.create_resident(self.property, status=Resident.Status.ABSCONDED)
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)

        response = self._confirm(resident)
        self.assertEqual(response.status_code, 403)


class BlacklistCheckTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property_a = self.create_property(self.tenant, name='Property A')
        self.property_b = self.create_property(self.tenant, name='Other Property B')
        self.resident = self.create_resident(
            self.property_a, phone='9000000001', aadhaar_number='123456789012',
            status=Resident.Status.ABSCONDED,
        )
        self.authenticate(self.owner)
        self.client.post(reverse('blacklist-entry-list'), {'resident': str(self.resident.id)})

    def test_check_by_phone_finds_a_match(self):
        response = self.client.get(reverse('blacklist-entry-check'), {'phone': '9000000001'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_check_by_aadhaar_finds_a_match(self):
        response = self.client.get(reverse('blacklist-entry-check'), {'aadhaar_number': '123456789012'})
        self.assertEqual(len(response.data), 1)

    def test_check_with_no_match_returns_empty(self):
        response = self.client.get(reverse('blacklist-entry-check'), {'phone': '9999999999'})
        self.assertEqual(response.data, [])

    def test_check_with_no_query_params_returns_empty(self):
        response = self.client.get(reverse('blacklist-entry-check'))
        self.assertEqual(response.data, [])

    def test_blacklist_is_visible_to_manager_not_assigned_to_the_original_property(self):
        # PRD: "Blacklist flag is visible across all properties of the tenant" —
        # a Manager assigned only to Property B (never Property A, where the
        # blacklisted resident actually lived) must still see the warning.
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property_b)
        self.authenticate(manager)

        response = self.client.get(reverse('blacklist-entry-check'), {'phone': '9000000001'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_check_does_not_leak_across_tenants(self):
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')
        self.authenticate(other_owner)

        response = self.client.get(reverse('blacklist-entry-check'), {'phone': '9000000001'})
        self.assertEqual(response.data, [])

    def test_receptionist_cannot_check_blacklist(self):
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property_a)
        self.authenticate(receptionist)

        response = self.client.get(reverse('blacklist-entry-check'), {'phone': '9000000001'})
        self.assertEqual(response.status_code, 403)
