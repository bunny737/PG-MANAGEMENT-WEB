from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import Tenant
from apps.core.roles import Role

from .base import STRONG_PASSWORD, AuthAPITestCase


class LoginTests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)

    def login(self, email='owner@example.com', password=STRONG_PASSWORD):
        return self.client.post(reverse('auth-login'), {'email': email, 'password': password})

    def test_login_returns_tokens_with_tenant_and_role_claims(self):
        response = self.login()

        self.assertEqual(response.status_code, 200)
        claims = AccessToken(response.data['access'])
        self.assertEqual(claims['tenant_id'], str(self.tenant.id))
        self.assertEqual(claims['role'], Role.OWNER)

    def test_login_rejects_wrong_password(self):
        response = self.login(password='wrong-password')
        self.assertEqual(response.status_code, 401)

    def test_login_rejects_unverified_email(self):
        self.create_user(
            self.tenant, Role.MANAGER, 'manager@example.com', email_verified=False
        )
        response = self.login(email='manager@example.com')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data.get('code'), 'EMAIL_NOT_VERIFIED')

    def test_login_rejects_deactivated_user(self):
        self.owner.is_active = False
        self.owner.save(update_fields=['is_active'])
        response = self.login()
        self.assertEqual(response.status_code, 401)

    def test_suspended_tenant_blocks_login(self):
        self.tenant.status = Tenant.Status.SUSPENDED
        self.tenant.save(update_fields=['status'])

        response = self.login()

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data.get('code'), 'SUBSCRIPTION_SUSPENDED')

    def test_suspension_invalidates_existing_access_tokens(self):
        # Force logout on plan suspension (PRD Module 1).
        self.authenticate(self.owner)
        self.assertEqual(self.client.get(reverse('auth-me')).status_code, 200)

        self.tenant.status = Tenant.Status.SUSPENDED
        self.tenant.save(update_fields=['status'])

        response = self.client.get(reverse('auth-me'))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data.get('code'), 'SUBSCRIPTION_SUSPENDED')

    def test_suspension_blocks_token_refresh(self):
        refresh = self.login().data['refresh']
        self.tenant.status = Tenant.Status.SUSPENDED
        self.tenant.save(update_fields=['status'])

        response = self.client.post(reverse('auth-token-refresh'), {'refresh': refresh})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data.get('code'), 'SUBSCRIPTION_SUSPENDED')

    def test_cancelled_tenant_blocks_login(self):
        self.tenant.status = Tenant.Status.CANCELLED
        self.tenant.save(update_fields=['status'])
        response = self.login()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data.get('code'), 'SUBSCRIPTION_SUSPENDED')
