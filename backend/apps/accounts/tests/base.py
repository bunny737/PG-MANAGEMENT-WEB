import re
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import Tenant, User
from apps.accounts.serializers import LoginSerializer
from apps.core.roles import Role

STRONG_PASSWORD = 'Vintage-Kite-77'


class AuthAPITestCase(APITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()  # reset throttle counters between tests

    @staticmethod
    def create_tenant(name='Sunrise PG', **kwargs):
        kwargs.setdefault('trial_ends_at', timezone.now() + timedelta(days=60))
        return Tenant.objects.create(name=name, **kwargs)

    @staticmethod
    def create_user(tenant, role, email, password=STRONG_PASSWORD, **kwargs):
        kwargs.setdefault('first_name', 'Test')
        kwargs.setdefault('email_verified', True)
        return User.objects.create_user(
            email=email, password=password, tenant=tenant, role=role, **kwargs
        )

    @classmethod
    def create_owner(cls, tenant, email='owner@example.com', **kwargs):
        return cls.create_user(tenant, Role.OWNER, email, **kwargs)

    @classmethod
    def create_super_admin(cls, email='admin@platform.example.com', **kwargs):
        return cls.create_user(None, Role.SUPER_ADMIN, email, **kwargs)

    def authenticate(self, user):
        """Real JWT credentials so TenantJWTAuthentication (suspension check +
        RLS context) runs exactly as in production. Do not use force_authenticate
        in this project — it skips the tenant context."""
        token = LoginSerializer.get_token(user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')

    @staticmethod
    def extract_query_param(email_body, param):
        match = re.search(rf'[?&]{param}=([^\s&]+)', email_body)
        return match.group(1) if match else None
