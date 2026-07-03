from datetime import date

from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context

from .base import BillingAPITestCase


def discount_payload(resident, **overrides):
    payload = {
        'resident': str(resident.id),
        'discount_type': 'fixed',
        'discount_value': '500.00',
        'reason': 'loyalty',
        'valid_from': '2026-07-01',
    }
    payload.update(overrides)
    return payload


class DiscountManagementTests(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.resident = self.create_resident(self.property)

    def test_owner_creates_discount_stamps_approver_and_audit_log(self):
        self.authenticate(self.owner)

        response = self.client.post(reverse('discount-list'), discount_payload(self.resident))

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(str(response.data['approved_by']), str(self.owner.id))
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='discount.created').exists())

    def test_manager_can_create_discount_in_assigned_property(self):
        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        response = self.client.post(reverse('discount-list'), discount_payload(self.resident))

        self.assertEqual(response.status_code, 201, response.data)

    def test_manager_cannot_create_discount_in_unassigned_property(self):
        manager = self.create_manager(self.tenant)  # not assigned
        self.authenticate(manager)

        response = self.client.post(reverse('discount-list'), discount_payload(self.resident))

        self.assertEqual(response.status_code, 400)
        self.assertIn('resident', response.data)

    def test_receptionist_and_resident_cannot_manage_discounts(self):
        for role, email in [(Role.RECEPTIONIST, 'reception@example.com'), (Role.RESIDENT, 'resident@example.com')]:
            user = self.create_user(self.tenant, role, email)
            self.authenticate(user)
            self.assertEqual(self.client.get(reverse('discount-list')).status_code, 403)
            self.assertEqual(
                self.client.post(reverse('discount-list'), discount_payload(self.resident)).status_code, 403
            )

    def test_percentage_discount_cannot_exceed_100(self):
        self.authenticate(self.owner)
        response = self.client.post(
            reverse('discount-list'),
            discount_payload(self.resident, discount_type='percentage', discount_value='150'),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('discount_value', response.data)

    def test_discount_value_must_be_positive(self):
        self.authenticate(self.owner)
        response = self.client.post(
            reverse('discount-list'), discount_payload(self.resident, discount_value='0'),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('discount_value', response.data)

    def test_valid_until_cannot_precede_valid_from(self):
        self.authenticate(self.owner)
        response = self.client.post(
            reverse('discount-list'),
            discount_payload(self.resident, valid_from='2026-07-01', valid_until='2026-06-01'),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('valid_until', response.data)

    def test_overlapping_discount_for_same_resident_is_rejected(self):
        self.create_discount(self.resident, valid_from=date(2026, 7, 1), valid_until=None)  # indefinite
        self.authenticate(self.owner)

        response = self.client.post(
            reverse('discount-list'), discount_payload(self.resident, valid_from='2026-08-01'),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('valid_from', response.data)

    def test_touching_windows_count_as_overlap(self):
        self.create_discount(self.resident, valid_from=date(2026, 7, 1), valid_until=date(2026, 7, 31))
        self.authenticate(self.owner)

        response = self.client.post(
            reverse('discount-list'),
            discount_payload(self.resident, valid_from='2026-07-31', valid_until='2026-08-31'),
        )

        self.assertEqual(response.status_code, 400)  # shares 2026-07-31

    def test_non_overlapping_windows_are_allowed(self):
        self.create_discount(self.resident, valid_from=date(2026, 7, 1), valid_until=date(2026, 7, 31))
        self.authenticate(self.owner)

        response = self.client.post(
            reverse('discount-list'), discount_payload(self.resident, valid_from='2026-08-01'),
        )

        self.assertEqual(response.status_code, 201, response.data)

    def test_two_residents_can_hold_overlapping_discounts(self):
        second = self.create_resident(self.property, phone='9000000002')
        self.create_discount(self.resident, valid_from=date(2026, 7, 1), valid_until=None)
        self.authenticate(self.owner)

        response = self.client.post(reverse('discount-list'), discount_payload(second, valid_from='2026-07-01'))

        self.assertEqual(response.status_code, 201, response.data)

    def test_discount_has_no_delete_endpoint(self):
        discount = self.create_discount(self.resident)
        self.authenticate(self.owner)
        response = self.client.delete(reverse('discount-detail', args=[discount.id]))
        self.assertEqual(response.status_code, 405)

    def test_ending_a_discount_via_patch_is_audit_logged(self):
        discount = self.create_discount(self.resident, valid_from=date(2026, 7, 1), valid_until=None)
        self.authenticate(self.owner)

        response = self.client.patch(
            reverse('discount-detail', args=[discount.id]), {'valid_until': '2026-07-31'}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['valid_until'], '2026-07-31')
        with tenant_context(self.tenant.id):
            entry = AuditLog.objects.get(action='discount.updated', object_id=str(discount.id))
        self.assertIsNone(entry.before['valid_until'])
        self.assertEqual(entry.after['valid_until'], '2026-07-31')

    def test_discount_list_is_property_scoped_for_manager(self):
        self.create_discount(self.resident)
        other_property = self.create_property(self.tenant, name='Other Property')
        other_resident = self.create_resident(other_property, phone='9000000003')
        self.create_discount(other_resident)

        manager = self.create_manager(self.tenant)
        self.assign_staff(manager, self.property)
        self.authenticate(manager)

        response = self.client.get(reverse('discount-list'))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(str(response.data[0]['resident']), str(self.resident.id))

    def test_discount_detail_is_tenant_scoped(self):
        discount = self.create_discount(self.resident)
        other_tenant = self.create_tenant('Other PG')
        other_owner = self.create_owner(other_tenant, email='other-owner@example.com')

        self.authenticate(other_owner)
        response = self.client.get(reverse('discount-detail', args=[discount.id]))
        self.assertEqual(response.status_code, 404)
