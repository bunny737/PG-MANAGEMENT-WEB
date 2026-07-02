from datetime import timedelta

from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Tenant, User
from apps.audit.models import AuditLog
from apps.core.models import PlatformConfig
from apps.core.roles import Role
from apps.core.tenancy import tenant_context

from .base import STRONG_PASSWORD, AuthAPITestCase


def signup_payload(**overrides):
    payload = {
        'business_name': 'Sunrise PG',
        'first_name': 'Ramesh',
        'last_name': 'Kumar',
        'email': 'ramesh@example.com',
        'phone': '+919876543210',
        'password': STRONG_PASSWORD,
    }
    payload.update(overrides)
    return payload


class SignupTests(AuthAPITestCase):
    def test_signup_creates_tenant_and_owner_with_configured_trial(self):
        # Invariant 10: trial length comes from PlatformConfig, not a constant.
        config = PlatformConfig.get()
        config.trial_days = 30
        config.save()

        response = self.client.post(reverse('auth-signup'), signup_payload())

        self.assertEqual(response.status_code, 201)
        tenant = Tenant.objects.get(name='Sunrise PG')
        owner = User.objects.get(email='ramesh@example.com')
        self.assertEqual(tenant.status, Tenant.Status.TRIAL)
        self.assertEqual(owner.tenant, tenant)
        self.assertEqual(owner.role, Role.OWNER)
        self.assertFalse(owner.email_verified)
        expected_end = timezone.now() + timedelta(days=30)
        self.assertLess(abs(tenant.trial_ends_at - expected_end), timedelta(minutes=5))

    def test_signup_sends_verification_email_and_writes_audit_log(self):
        response = self.client.post(reverse('auth-signup'), signup_payload())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('verify-email', mail.outbox[0].body)
        tenant = Tenant.objects.get(name='Sunrise PG')
        with tenant_context(tenant.id):
            self.assertTrue(
                AuditLog.objects.filter(action='tenant.signed_up', tenant_id=tenant.id).exists()
            )

    def test_signup_rejects_duplicate_email(self):
        tenant = self.create_tenant('Existing PG')
        self.create_owner(tenant, email='ramesh@example.com')

        response = self.client.post(reverse('auth-signup'), signup_payload())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Tenant.objects.count(), 1)

    def test_email_verification_flow_enables_login(self):
        self.client.post(reverse('auth-signup'), signup_payload())
        token = self.extract_query_param(mail.outbox[0].body, 'token')

        blocked = self.client.post(
            reverse('auth-login'),
            {'email': 'ramesh@example.com', 'password': STRONG_PASSWORD},
        )
        self.assertEqual(blocked.status_code, 401)
        self.assertEqual(blocked.data.get('code'), 'EMAIL_NOT_VERIFIED')

        verified = self.client.post(reverse('auth-verify-email'), {'token': token})
        self.assertEqual(verified.status_code, 200)

        login = self.client.post(
            reverse('auth-login'),
            {'email': 'ramesh@example.com', 'password': STRONG_PASSWORD},
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn('access', login.data)

    def test_verify_email_rejects_garbage_token(self):
        response = self.client.post(reverse('auth-verify-email'), {'token': 'not-a-token'})
        self.assertEqual(response.status_code, 400)
