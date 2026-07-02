from unittest import mock

from django.urls import reverse
from rest_framework.throttling import SimpleRateThrottle

from .base import AuthAPITestCase

# DRF binds THROTTLE_RATES to the settings dict at import time, so
# override_settings(REST_FRAMEWORK=...) has no effect — patch the dict in place.
low_rates = mock.patch.dict(
    SimpleRateThrottle.THROTTLE_RATES, {'login': '2/min', 'otp_request': '2/min'}
)


class AuthThrottleTests(AuthAPITestCase):
    @low_rates
    def test_login_attempts_are_rate_limited(self):
        payload = {'email': 'nobody@example.com', 'password': 'wrong'}
        for _ in range(2):
            self.assertEqual(
                self.client.post(reverse('auth-login'), payload).status_code, 401
            )
        self.assertEqual(self.client.post(reverse('auth-login'), payload).status_code, 429)

    @low_rates
    def test_otp_requests_are_rate_limited(self):
        payload = {'phone': '+919876543210'}
        for _ in range(2):
            self.assertEqual(
                self.client.post(reverse('auth-otp-request'), payload).status_code, 200
            )
        self.assertEqual(
            self.client.post(reverse('auth-otp-request'), payload).status_code, 429
        )
