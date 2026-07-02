from django.urls import reverse

from apps.core.roles import Role, permissions_for

from .base import AuthAPITestCase


class MeEndpointTests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)

    def test_me_returns_profile_tenant_and_matrix_permissions(self):
        self.authenticate(self.owner)
        response = self.client.get(reverse('auth-me'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['email'], 'owner@example.com')
        self.assertEqual(response.data['role'], Role.OWNER)
        self.assertEqual(response.data['tenant']['id'], str(self.tenant.id))
        self.assertEqual(response.data['permissions'], permissions_for(Role.OWNER))
        self.assertIn('manage_staff_accounts', response.data['permissions'])

    def test_receptionist_permissions_match_matrix_exactly(self):
        receptionist = self.create_user(self.tenant, Role.RECEPTIONIST, 'reception@example.com')
        self.authenticate(receptionist)
        response = self.client.get(reverse('auth-me'))

        self.assertEqual(
            response.data['permissions'],
            sorted(['manage_visitors', 'view_resident_profile']),
        )

    def test_patch_updates_language_preference(self):
        # PRD i18n: language preference is per user, editable any time.
        self.authenticate(self.owner)
        response = self.client.patch(reverse('auth-me'), {'language_code': 'te'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['language_code'], 'te')
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.language_code, 'te')

    def test_me_requires_authentication(self):
        self.assertEqual(self.client.get(reverse('auth-me')).status_code, 401)
