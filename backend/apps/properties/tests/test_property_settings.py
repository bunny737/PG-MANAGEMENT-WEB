from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context

from .base import PropertyAPITestCase


def settings_url(prop):
    return reverse('property-settings', args=[prop.id])


class PropertySettingsTests(PropertyAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)

    def test_settings_are_lazily_created_with_prd_defaults(self):
        self.authenticate(self.owner)

        response = self.client.get(settings_url(self.property))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['room_transfer_rent_timing'], 'next_billing_cycle')
        self.assertEqual(response.data['late_payment_penalty_type'], 'none')
        self.assertIsNone(response.data['penalty_value'])
        self.assertEqual(response.data['penalty_grace_days'], 5)
        self.assertEqual(response.data['penalty_applies_to'], 'full_invoice')
        self.assertEqual(response.data['penalty_compounding'], 'one_time')

    def test_owner_updates_settings_and_it_is_audit_logged(self):
        self.authenticate(self.owner)

        response = self.client.patch(settings_url(self.property), {
            'room_transfer_rent_timing': 'immediate',
            'late_payment_penalty_type': 'fixed',
            'penalty_value': '200.00',
            'penalty_grace_days': 3,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['room_transfer_rent_timing'], 'immediate')
        self.assertEqual(response.data['penalty_value'], '200.00')
        with tenant_context(self.tenant.id):
            entry = AuditLog.objects.get(action='property_settings.updated')
        self.assertEqual(entry.before['late_payment_penalty_type'], 'none')
        self.assertEqual(entry.after['late_payment_penalty_type'], 'fixed')

    def test_manager_can_update_settings_for_assigned_property(self):
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        response = self.client.patch(settings_url(self.property), {'penalty_grace_days': 10})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['penalty_grace_days'], 10)

    def test_manager_cannot_access_settings_for_unassigned_property(self):
        manager = self.create_manager(self.tenant)  # not assigned
        self.authenticate(manager)

        response = self.client.get(settings_url(self.property))

        self.assertEqual(response.status_code, 404)

    def test_receptionist_and_resident_cannot_access_settings(self):
        for role, email in [(Role.RECEPTIONIST, 'reception@example.com'), (Role.RESIDENT, 'resident@example.com')]:
            user = self.create_user(self.tenant, role, email)
            self.authenticate(user)
            self.assertEqual(self.client.get(settings_url(self.property)).status_code, 403)

    def test_penalty_value_required_when_penalty_type_is_set(self):
        self.authenticate(self.owner)

        response = self.client.patch(settings_url(self.property), {'late_payment_penalty_type': 'fixed'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('penalty_value', response.data)

    def test_percentage_penalty_must_be_between_0_and_100(self):
        self.authenticate(self.owner)

        response = self.client.patch(settings_url(self.property), {
            'late_payment_penalty_type': 'percentage', 'penalty_value': '150.00',
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn('penalty_value', response.data)

    def test_switching_penalty_type_to_none_clears_penalty_value(self):
        self.authenticate(self.owner)
        self.client.patch(settings_url(self.property), {
            'late_payment_penalty_type': 'fixed', 'penalty_value': '200.00',
        })

        response = self.client.patch(settings_url(self.property), {'late_payment_penalty_type': 'none'})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['penalty_value'])

    def test_penalty_grace_days_capped_at_30(self):
        self.authenticate(self.owner)

        response = self.client.patch(settings_url(self.property), {'penalty_grace_days': 31})

        self.assertEqual(response.status_code, 400)
        self.assertIn('penalty_grace_days', response.data)

    def test_settings_are_tenant_scoped(self):
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')
        self.authenticate(other_owner)

        response = self.client.get(settings_url(self.property))

        self.assertEqual(response.status_code, 404)
