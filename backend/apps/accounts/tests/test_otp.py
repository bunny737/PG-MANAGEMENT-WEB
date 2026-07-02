from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import OtpCode
from apps.core.roles import Role

from .base import AuthAPITestCase

PHONE = '+919876543210'


class OtpLoginTests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant, phone=PHONE)

    def request_code(self, phone=PHONE):
        """POST /otp/request/ and capture the plaintext code before hashing."""
        with mock.patch('apps.accounts.otp._deliver') as deliver:
            response = self.client.post(reverse('auth-otp-request'), {'phone': phone})
            code = deliver.call_args[0][1] if deliver.call_args else None
        return response, code

    def verify(self, code, phone=PHONE):
        return self.client.post(reverse('auth-otp-verify'), {'phone': phone, 'code': code})

    def test_otp_flow_returns_tokens(self):
        response, code = self.request_code()
        self.assertEqual(response.status_code, 200)

        verified = self.verify(code)
        self.assertEqual(verified.status_code, 200)
        self.assertIn('access', verified.data)
        self.assertIn('refresh', verified.data)

    def test_wrong_code_rejected(self):
        _, code = self.request_code()
        wrong = '000000' if code != '000000' else '111111'
        response = self.verify(wrong)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data.get('code'), 'INVALID_OTP')

    def test_code_is_single_use(self):
        _, code = self.request_code()
        self.assertEqual(self.verify(code).status_code, 200)
        self.assertEqual(self.verify(code).status_code, 401)

    def test_expired_code_rejected(self):
        _, code = self.request_code()
        OtpCode.objects.filter(user=self.owner).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(self.verify(code).status_code, 401)

    def test_attempts_are_limited(self):
        _, code = self.request_code()
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(settings.OTP_MAX_ATTEMPTS):
            self.verify(wrong)
        # Correct code no longer works once attempts are exhausted.
        self.assertEqual(self.verify(code).status_code, 401)

    def test_new_request_invalidates_previous_code(self):
        _, first = self.request_code()
        _, second = self.request_code()
        self.assertEqual(self.verify(first).status_code, 401)
        self.assertEqual(self.verify(second).status_code, 200)

    def test_unknown_phone_does_not_reveal_registration(self):
        response, code = self.request_code(phone='+911111111111')
        self.assertEqual(response.status_code, 200)  # silent — no enumeration
        self.assertIsNone(code)

    def test_otp_login_respects_email_verification_gate(self):
        self.create_user(
            self.tenant, Role.MANAGER, 'manager@example.com',
            phone='+919000000000', email_verified=False,
        )
        _, code = self.request_code(phone='+919000000000')
        response = self.verify(code, phone='+919000000000')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data.get('code'), 'EMAIL_NOT_VERIFIED')
