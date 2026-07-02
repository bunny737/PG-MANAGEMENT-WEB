from django.core import mail
from django.urls import reverse

from .base import STRONG_PASSWORD, AuthAPITestCase

NEW_PASSWORD = 'Copper-Meadow-42'


class PasswordResetTests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)

    def test_reset_flow_changes_password(self):
        response = self.client.post(
            reverse('auth-password-reset'), {'email': 'owner@example.com'}
        )
        self.assertEqual(response.status_code, 200)
        body = mail.outbox[0].body
        uid = self.extract_query_param(body, 'uid')
        token = self.extract_query_param(body, 'token')

        confirm = self.client.post(
            reverse('auth-password-reset-confirm'),
            {'uid': uid, 'token': token, 'new_password': NEW_PASSWORD},
        )
        self.assertEqual(confirm.status_code, 200)

        old = self.client.post(
            reverse('auth-login'),
            {'email': 'owner@example.com', 'password': STRONG_PASSWORD},
        )
        self.assertEqual(old.status_code, 401)
        new = self.client.post(
            reverse('auth-login'),
            {'email': 'owner@example.com', 'password': NEW_PASSWORD},
        )
        self.assertEqual(new.status_code, 200)

    def test_invalid_token_rejected(self):
        self.client.post(reverse('auth-password-reset'), {'email': 'owner@example.com'})
        uid = self.extract_query_param(mail.outbox[0].body, 'uid')

        response = self.client.post(
            reverse('auth-password-reset-confirm'),
            {'uid': uid, 'token': 'bogus-token', 'new_password': NEW_PASSWORD},
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_email_does_not_reveal_registration(self):
        response = self.client.post(
            reverse('auth-password-reset'), {'email': 'nobody@example.com'}
        )
        self.assertEqual(response.status_code, 200)  # silent — no enumeration
        self.assertEqual(len(mail.outbox), 0)

    def test_weak_password_rejected(self):
        self.client.post(reverse('auth-password-reset'), {'email': 'owner@example.com'})
        body = mail.outbox[0].body
        response = self.client.post(
            reverse('auth-password-reset-confirm'),
            {
                'uid': self.extract_query_param(body, 'uid'),
                'token': self.extract_query_param(body, 'token'),
                'new_password': '123',
            },
        )
        self.assertEqual(response.status_code, 400)
