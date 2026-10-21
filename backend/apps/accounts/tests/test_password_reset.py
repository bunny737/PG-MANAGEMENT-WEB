import threading
from smtplib import SMTPException
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, User
from apps.accounts.tokens import make_password_reset_credentials
from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context

from .base import STRONG_PASSWORD, AuthAPITestCase

NEW_PASSWORD = 'Copper-Meadow-42'
OTHER_PASSWORD = 'Granite-Lantern-58'
SMTP_SEND = 'apps.core.email.EmailMultiAlternatives.send'


class PasswordResetTests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)

    def request_reset(self, email='owner@example.com'):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('auth-password-reset'), {'email': email})

    def confirm(self, body, password=NEW_PASSWORD, **overrides):
        payload = {
            'uid': self.extract_query_param(body, 'uid'),
            'token': self.extract_query_param(body, 'token'),
            'new_password': password,
            **overrides,
        }
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('auth-password-reset-confirm'), payload)

    def reset_body(self):
        self.assertEqual(self.request_reset().status_code, 200)
        return mail.outbox[0].body

    def test_reset_flow_changes_password(self):
        confirm = self.confirm(self.reset_body())
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

    def test_link_carries_uid_and_token_in_the_fragment(self):
        body = self.reset_body()
        self.assertIn('/reset-password#uid=', body)
        self.assertNotIn('?uid=', body)
        self.assertNotIn('?token=', body)

    def test_invalid_token_rejected(self):
        body = self.reset_body()
        self.assertEqual(self.confirm(body, token='bogus-token').status_code, 400)

    def test_unknown_email_does_not_reveal_registration(self):
        response = self.request_reset('nobody@example.com')
        self.assertEqual(response.status_code, 200)  # silent — no enumeration
        self.assertEqual(len(mail.outbox), 0)

    def test_weak_password_rejected(self):
        self.assertEqual(self.confirm(self.reset_body(), password='123').status_code, 400)

    def test_request_only_queues_the_email(self):
        """Nothing is sent on the request path: the worker does it after commit."""
        response = self.client.post(reverse('auth-password-reset'), {'email': 'owner@example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox, [])

    def test_smtp_outage_looks_the_same_for_every_address(self):
        with mock.patch(SMTP_SEND, side_effect=SMTPException('down')):
            known = self.request_reset('owner@example.com')
            unknown = self.request_reset('nobody@example.com')
        self.assertEqual((known.status_code, known.data), (unknown.status_code, unknown.data))
        self.assertEqual(known.status_code, 200)

    def test_inactive_super_admin_and_suspended_tenant_get_no_link(self):
        self.create_super_admin(email='root@platform.example.com')
        self.assertEqual(self.request_reset('root@platform.example.com').status_code, 200)
        self.assertEqual(mail.outbox, [])

        Tenant.objects.filter(pk=self.tenant.pk).update(status=Tenant.Status.SUSPENDED)
        self.request_reset()
        self.assertEqual(mail.outbox, [])

        Tenant.objects.filter(pk=self.tenant.pk).update(status=Tenant.Status.ACTIVE)
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.request_reset()
        self.assertEqual(mail.outbox, [])

    def test_token_works_once(self):
        body = self.reset_body()
        self.assertEqual(self.confirm(body).status_code, 200)
        again = self.confirm(body, password=OTHER_PASSWORD)
        self.assertEqual(again.status_code, 400)
        self.assertIn('token', str(again.data))
        login = self.client.post(
            reverse('auth-login'), {'email': 'owner@example.com', 'password': NEW_PASSWORD},
        )
        self.assertEqual(login.status_code, 200)

    def test_reset_ends_existing_sessions(self):
        login = self.client.post(
            reverse('auth-login'), {'email': 'owner@example.com', 'password': STRONG_PASSWORD},
        )
        refresh = login.data['refresh']
        self.confirm(self.reset_body())
        response = self.client.post(reverse('auth-token-refresh'), {'refresh': refresh})
        self.assertEqual(response.status_code, 401)

    def test_reset_marks_the_email_verified(self):
        User.objects.filter(pk=self.owner.pk).update(email_verified=False)
        self.confirm(self.reset_body())
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.email_verified)

    def test_reset_is_audited_as_an_anonymous_action_on_the_user(self):
        self.confirm(self.reset_body())
        with tenant_context(self.tenant.id):
            entry = AuditLog.objects.get(action='user.password_reset')
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.tenant_id, self.tenant.id)
        self.assertEqual(entry.object_type, 'User')
        self.assertEqual(entry.object_id, str(self.owner.id))
        self.assertEqual(entry.after['auth_version'], entry.before['auth_version'] + 1)
        self.assertNotIn(NEW_PASSWORD, str(entry.after))

    def test_reset_sends_a_password_changed_notice(self):
        body = self.reset_body()
        mail.outbox.clear()
        self.confirm(body)
        self.assertEqual([m.to for m in mail.outbox], [['owner@example.com']])
        self.assertEqual(mail.outbox[0].subject, 'Your password was changed')

    def test_smtp_outage_does_not_block_a_reset(self):
        body = self.reset_body()
        with mock.patch(SMTP_SEND, side_effect=SMTPException('down')):
            response = self.confirm(body)
        self.assertEqual(response.status_code, 200)

    def test_requests_and_confirmations_are_throttled_separately(self):
        body = self.reset_body()
        statuses = [self.request_reset(f'nobody{n}@example.com').status_code for n in range(6)]
        self.assertEqual(statuses[-1], 429)  # request scope: 5/min per IP (one already used)
        self.assertEqual(self.confirm(body).status_code, 200)  # confirm has its own allowance

    def test_the_same_address_is_limited_across_ips(self):
        statuses = []
        for n in range(6):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    reverse('auth-password-reset'), {'email': 'Owner@Example.com'},
                    REMOTE_ADDR=f'10.0.0.{n + 1}',
                )
            statuses.append(response.status_code)
        self.assertEqual(statuses, [200] * 5 + [429])  # 5/hour per address


class PasswordResetConcurrencyTests(TransactionTestCase):
    """Two confirmations carrying one token, released together (needs real commits)."""

    ROUNDS = 6

    def _fixture_teardown(self):
        pass  # the default flush would wipe migration-seeded tables for the rest of the run

    def setUp(self):
        self.tenant = AuthAPITestCase.create_tenant('Reset Race PG')
        self.owner = AuthAPITestCase.create_owner(self.tenant, email='race@reset.example.com')

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            AuditLog.objects.filter(tenant_id=self.tenant.id).delete()
        self.tenant.delete()  # cascades to the user

    def test_a_token_changes_the_password_exactly_once(self):
        for _ in range(self.ROUNDS):
            cache.clear()  # throttle counters: 2 requests per round would exhaust the minute
            self.owner.refresh_from_db()
            creds = make_password_reset_credentials(self.owner)
            barrier = threading.Barrier(2)
            results, errors = {}, []

            def confirm(password):
                try:
                    client = APIClient()
                    barrier.wait(timeout=10)
                    results[password] = client.post(
                        reverse('auth-password-reset-confirm'),
                        {**creds, 'new_password': password},
                    ).status_code
                except Exception as exc:  # noqa: BLE001 - surfaced through `errors`
                    errors.append(exc)
                finally:
                    connection.close()

            threads = [
                threading.Thread(target=confirm, args=(NEW_PASSWORD,)),
                threading.Thread(target=confirm, args=(OTHER_PASSWORD,)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

            self.assertEqual(errors, [])
            self.assertEqual(sorted(results.values()), [200, 400], results)
            winner = next(password for password, code in results.items() if code == 200)
            self.owner.refresh_from_db()
            self.assertTrue(self.owner.check_password(winner))
            # Rotate so the next round starts from a password both candidates differ from.
            winner_other = OTHER_PASSWORD if winner == NEW_PASSWORD else NEW_PASSWORD
            self.assertFalse(self.owner.check_password(winner_other))
