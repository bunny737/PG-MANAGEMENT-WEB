import threading
from smtplib import SMTPException
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context

from .base import STRONG_PASSWORD, AuthAPITestCase

NEW_PASSWORD = 'Copper-Meadow-42'
OTHER_PASSWORD = 'Granite-Lantern-58'
SMTP_SEND = 'apps.core.email.EmailMultiAlternatives.send'


class PasswordChangeTests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.url = reverse('auth-password-change')

    def change(self, current=STRONG_PASSWORD, new=NEW_PASSWORD):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                self.url, {'current_password': current, 'new_password': new}, format='json'
            )

    def login(self, password):
        return self.client.post(
            reverse('auth-login'), {'email': 'owner@example.com', 'password': password}
        )

    def test_requires_authentication(self):
        response = self.client.post(
            self.url, {'current_password': 'x', 'new_password': NEW_PASSWORD}, format='json'
        )
        self.assertEqual(response.status_code, 401)

    def test_changes_the_password_and_returns_a_working_token_pair(self):
        self.authenticate(self.owner)
        response = self.change()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {'access', 'refresh'})

        self.client.credentials()
        self.assertEqual(self.login(STRONG_PASSWORD).status_code, 401)
        self.assertEqual(self.login(NEW_PASSWORD).status_code, 200)

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')
        self.assertEqual(self.client.get(reverse('auth-me')).status_code, 200)
        self.client.credentials()
        refreshed = self.client.post(
            reverse('auth-token-refresh'), {'refresh': response.data['refresh']}
        )
        self.assertEqual(refreshed.status_code, 200)

    def test_old_access_and_refresh_tokens_stop_working(self):
        login = self.login(STRONG_PASSWORD)
        old_access, old_refresh = login.data['access'], login.data['refresh']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {old_access}')
        self.assertEqual(self.client.get(reverse('auth-me')).status_code, 200)

        self.assertEqual(self.change().status_code, 200)

        self.assertEqual(self.client.get(reverse('auth-me')).status_code, 401)
        self.client.credentials()
        refreshed = self.client.post(reverse('auth-token-refresh'), {'refresh': old_refresh})
        self.assertEqual(refreshed.status_code, 401)

    def test_wrong_current_password_changes_nothing(self):
        self.authenticate(self.owner)
        response = self.change(current='Not-The-Password-1')
        self.assertEqual(response.status_code, 400)
        self.assertIn('current_password', str(response.data))
        self.client.credentials()
        self.assertEqual(self.login(STRONG_PASSWORD).status_code, 200)
        self.assertEqual(mail.outbox, [])

    def test_new_password_must_differ_from_the_current_one(self):
        self.authenticate(self.owner)
        self.assertEqual(self.change(new=STRONG_PASSWORD).status_code, 400)

    def test_weak_new_password_is_rejected(self):
        self.authenticate(self.owner)
        self.assertEqual(self.change(new='123').status_code, 400)
        self.assertEqual(self.change(new='password').status_code, 400)
        self.client.credentials()
        self.assertEqual(self.login(STRONG_PASSWORD).status_code, 200)

    def test_change_is_audited_with_the_user_as_actor(self):
        self.authenticate(self.owner)
        self.change()
        with tenant_context(self.tenant.id):
            entry = AuditLog.objects.get(action='user.password_changed')
        self.assertEqual(entry.actor_id, self.owner.id)
        self.assertEqual(entry.object_id, str(self.owner.id))
        self.assertEqual(entry.after['auth_version'], entry.before['auth_version'] + 1)
        self.assertNotIn(NEW_PASSWORD, str(entry.after))

    def test_a_security_notice_is_sent_after_commit(self):
        self.authenticate(self.owner)
        self.change()
        self.assertEqual([m.to for m in mail.outbox], [['owner@example.com']])
        self.assertEqual(mail.outbox[0].subject, 'Your password was changed')

    def test_the_notice_is_queued_not_sent_on_the_request_path(self):
        self.authenticate(self.owner)
        self.client.post(
            self.url, {'current_password': STRONG_PASSWORD, 'new_password': NEW_PASSWORD},
            format='json',
        )
        self.assertEqual(mail.outbox, [])

    def test_an_smtp_outage_never_blocks_the_change(self):
        self.authenticate(self.owner)
        with mock.patch(SMTP_SEND, side_effect=SMTPException('down')):
            response = self.change()
        self.assertEqual(response.status_code, 200)
        self.client.credentials()
        self.assertEqual(self.login(NEW_PASSWORD).status_code, 200)

    def test_a_user_can_only_change_their_own_password(self):
        other_tenant = self.create_tenant('Other PG')
        other = self.create_owner(other_tenant, email='other@example.com')
        other_login = self.client.post(
            reverse('auth-login'), {'email': 'other@example.com', 'password': STRONG_PASSWORD}
        )
        self.authenticate(self.owner)
        self.assertEqual(self.change().status_code, 200)

        other.refresh_from_db()
        self.assertTrue(other.check_password(STRONG_PASSWORD))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {other_login.data["access"]}')
        self.assertEqual(self.client.get(reverse('auth-me')).status_code, 200)

    def test_attempts_are_limited_per_user(self):
        self.authenticate(self.owner)
        statuses = [self.change(current='Wrong-Password-1').status_code for _ in range(6)]
        self.assertEqual(statuses, [400] * 5 + [429])


class PasswordChangeConcurrencyTests(TransactionTestCase):
    """Two changes presenting the same current password, released together."""

    ROUNDS = 6

    def _fixture_teardown(self):
        pass  # the default flush would wipe migration-seeded tables for the rest of the run

    def setUp(self):
        self.tenant = AuthAPITestCase.create_tenant('Change Race PG')
        self.owner = AuthAPITestCase.create_owner(self.tenant, email='race@change.example.com')

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            AuditLog.objects.filter(tenant_id=self.tenant.id).delete()
        self.tenant.delete()  # cascades to the user

    def test_the_current_password_is_checked_under_the_lock(self):
        from apps.accounts.serializers import LoginSerializer

        current = STRONG_PASSWORD
        for round_number in range(self.ROUNDS):
            cache.clear()  # throttle counters: 2 requests per round would exhaust the minute
            self.owner.refresh_from_db()
            token = LoginSerializer.get_token(self.owner)
            auth = f'Bearer {token.access_token}'
            barrier = threading.Barrier(2)
            results, errors = {}, []

            def change(new_password, current=current, auth=auth):
                try:
                    client = APIClient()
                    client.credentials(HTTP_AUTHORIZATION=auth)
                    barrier.wait(timeout=10)
                    results[new_password] = client.post(
                        reverse('auth-password-change'),
                        {'current_password': current, 'new_password': new_password},
                        format='json',
                    ).status_code
                except Exception as exc:  # noqa: BLE001 - surfaced through `errors`
                    errors.append(exc)
                finally:
                    connection.close()

            candidates = (f'Copper-Meadow-{round_number}1', f'Granite-Lantern-{round_number}2')
            threads = [threading.Thread(target=change, args=(candidate,)) for candidate in candidates]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

            self.assertEqual(errors, [])
            self.assertEqual(sorted(results.values()), [200, 400], results)
            winner = next(password for password, code in results.items() if code == 200)
            self.owner.refresh_from_db()
            self.assertTrue(self.owner.check_password(winner))
            current = winner
