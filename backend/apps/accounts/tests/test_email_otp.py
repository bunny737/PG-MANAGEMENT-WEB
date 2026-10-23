"""Email code login (optional path alongside password). Endpoint tests check
the request side answers every address alike and only queues work; delivery
tests drive the worker-side function and task directly; verify tests cover the
token exchange. See docs/modules/01-auth-tenancy.md (Decisions)."""
import re
import threading
import time
from datetime import timedelta
from smtplib import SMTPException
from unittest import mock

from django.conf import settings
from django.core import mail
from django.db import connection, transaction
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from kombu.exceptions import OperationalError
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts import otp
from apps.accounts.models import OtpCode, Tenant, User
from apps.accounts.tasks import _can_use_email_login, deliver_login_code, send_login_code_task
from apps.core.roles import Role

from .base import AuthAPITestCase

EMAIL = 'owner@example.com'
PHONE = '9876543210'
GENERIC = 'If that email can sign in with a code, a code has been sent.'

CODE_RE = re.compile(r'\b(\d{6})\b')


def email_code(user):
    return otp.issue(user, OtpCode.Channel.EMAIL)


class EmailOtpTestCase(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant, email=EMAIL, phone=PHONE)

    def request_code(self, email=EMAIL, **extra):
        return self.client.post(reverse('auth-otp-email-request'), {'email': email}, **extra)

    def verify(self, code, email=EMAIL):
        return self.client.post(reverse('auth-otp-email-verify'), {'email': email, 'code': code})

    @staticmethod
    def wrong(code):
        return '000000' if code != '000000' else '111111'


class EmailOtpRequestEndpointTests(EmailOtpTestCase):
    """The endpoint does no lookup and no SMTP: it queues the task for every
    address and answers identically."""

    def test_every_address_gets_the_same_response_and_is_queued(self):
        self.create_user(self.tenant, Role.OWNER, 'gone@example.com', is_active=False)
        self.create_super_admin(email='root@platform.example.com')
        blocked = self.create_tenant('Blocked PG', status=Tenant.Status.SUSPENDED)
        self.create_owner(blocked, email='suspended@example.com')

        addresses = [
            ('  Owner@Example.COM ', EMAIL),  # registered (normalized before queueing)
            ('nobody@example.com', 'nobody@example.com'),
            ('gone@example.com', 'gone@example.com'),
            ('root@platform.example.com', 'root@platform.example.com'),
            ('suspended@example.com', 'suspended@example.com'),
        ]
        responses = []
        with mock.patch('apps.accounts.serializers.enqueue') as enqueue:
            for n, (raw, normalized) in enumerate(addresses):
                    # A fresh IP each time so the per-IP limit stays out of the way.
                response = self.request_code(raw, REMOTE_ADDR=f'203.0.113.{n + 1}')
                self.assertEqual(response.status_code, 200)
                responses.append(response.data)
                enqueue.assert_called_with(send_login_code_task, normalized)
        self.assertEqual(len(enqueue.call_args_list), len(addresses))
        self.assertTrue(all(data == {'detail': GENERIC} for data in responses))
        self.assertFalse(OtpCode.objects.exists())  # nothing issued on the request path

    def test_broker_unavailable_still_returns_generic_response(self):
        with mock.patch.object(send_login_code_task, 'delay', side_effect=OperationalError('down')), \
                self.assertLogs('apps.core.tasks', 'ERROR'):
            response = self.request_code()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'detail': GENERIC})

    def test_invalid_email_is_rejected(self):
        self.assertEqual(self.request_code('not-an-email').status_code, 400)

    def test_malformed_bodies_are_400_not_500(self):
        url = reverse('auth-otp-email-request')
        bodies = [
            {'data': '{not json', 'content_type': 'application/json'},
            {'data': [EMAIL], 'format': 'json'},
            {'data': {'email': 123}, 'format': 'json'},
            {'data': {'email': ['x@example.com']}, 'format': 'json'},
        ]
        with mock.patch('apps.accounts.serializers.enqueue') as enqueue:
            for n, body in enumerate(bodies):
                with self.subTest(body=body):
                    response = self.client.post(url, REMOTE_ADDR=f'198.51.100.{n + 1}', **body)
                    self.assertEqual(response.status_code, 400)
        enqueue.assert_not_called()

    @mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {'otp_email_request': '2/min'})
    def test_requests_are_rate_limited_per_ip(self):
        with mock.patch('apps.accounts.serializers.enqueue'):
            for n in range(2):
                self.assertEqual(self.request_code(f'p{n}@example.com').status_code, 200)
            self.assertEqual(self.request_code('p9@example.com').status_code, 429)

    @mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {'otp_email_request_email': '2/hour'})
    def test_requests_are_rate_limited_per_email_across_ips(self):
        with mock.patch('apps.accounts.serializers.enqueue'):
            self.assertEqual(self.request_code(EMAIL, REMOTE_ADDR='203.0.113.1').status_code, 200)
            self.assertEqual(self.request_code(' OWNER@example.com', REMOTE_ADDR='203.0.113.2').status_code, 200)
            self.assertEqual(self.request_code(EMAIL, REMOTE_ADDR='203.0.113.3').status_code, 429)
            # A different address from the same fresh IP is unaffected.
            self.assertEqual(self.request_code('other@example.com', REMOTE_ADDR='203.0.113.3').status_code, 200)


class DeliverLoginCodeTests(EmailOtpTestCase):
    """Worker side: eligibility is decided here, silently."""

    def test_eligible_user_gets_one_email_with_a_working_code(self):
        deliver_login_code(EMAIL)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [EMAIL])
        code = CODE_RE.search(mail.outbox[0].body).group(1)
        self.assertIn('5 minutes', mail.outbox[0].body)
        self.assertEqual(self.verify(code).status_code, 200)

    def test_ineligible_addresses_issue_nothing_and_send_nothing(self):
        self.create_user(self.tenant, Role.OWNER, 'gone@example.com', is_active=False)
        self.create_super_admin(email='root@platform.example.com')
        for status in (Tenant.Status.SUSPENDED, Tenant.Status.CANCELLED):
            tenant = self.create_tenant(f'{status} PG', status=status)
            self.create_owner(tenant, email=f'{status}@example.com')

        for email in ['nobody@example.com', 'gone@example.com', 'root@platform.example.com',
                      'suspended@example.com', 'cancelled@example.com']:
            deliver_login_code(email)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(OtpCode.objects.exists())

    def test_staff_with_email_can_receive_a_code(self):
        self.create_user(self.tenant, Role.RECEPTIONIST, 'desk@example.com')
        deliver_login_code('desk@example.com')
        self.assertEqual(len(mail.outbox), 1)

    def test_email_is_sent_in_the_users_language(self):
        User.objects.filter(pk=self.owner.pk).update(language_code='te')
        deliver_login_code(EMAIL)
        self.assertNotEqual(mail.outbox[0].subject, 'Your sign-in code')

    def test_state_change_after_lookup_is_seen_on_the_locked_row(self):
        """The task looked the user up, then the account changed before
        otp.issue locked the row: the re-check on the locked row wins."""
        eligible = lambda locked: _can_use_email_login(locked, EMAIL)  # noqa: E731
        changes = [
            lambda: User.objects.filter(pk=self.owner.pk).update(is_active=False),
            lambda: Tenant.objects.filter(pk=self.tenant.pk).update(status=Tenant.Status.SUSPENDED),
            lambda: User.objects.filter(pk=self.owner.pk).update(email='moved@example.com'),
        ]
        for change in changes:
            with self.subTest(change=change), transaction.atomic():
                stale = User.objects.select_related('tenant').get(pk=self.owner.pk)
                change()
                self.assertIsNone(otp.issue(stale, OtpCode.Channel.EMAIL, still_eligible=eligible))
                self.assertFalse(OtpCode.objects.exists())
                transaction.set_rollback(True)

    def test_issue_returns_none_for_a_user_deleted_before_the_lock(self):
        stale = User.objects.get(pk=self.owner.pk)
        User.objects.filter(pk=self.owner.pk).delete()
        self.assertIsNone(otp.issue(stale, OtpCode.Channel.EMAIL))

    def test_a_retry_issues_a_new_code_and_only_the_newest_works(self):
        codes = []

        def flaky_send(user, code):
            codes.append(code)
            if len(codes) == 1:
                raise SMTPException('temporary failure')

        with mock.patch('apps.accounts.emails.send_login_code_email', side_effect=flaky_send):
            with self.assertRaises(SMTPException):
                deliver_login_code(EMAIL)  # the task would retry this
            deliver_login_code(EMAIL)  # the retry
        first, second = codes
        self.assertEqual(self.verify(first).status_code, 401)
        self.assertEqual(self.verify(second).status_code, 200)


class SendLoginCodeTaskTests(EmailOtpTestCase):
    def _run_async(self, retries):
        """Run the task body as a worker would (not eager) at a given retry count."""
        send_login_code_task.push_request(is_eager=False, retries=retries)
        try:
            return send_login_code_task.run(EMAIL)
        finally:
            send_login_code_task.pop_request()

    @mock.patch('apps.core.email.EmailMultiAlternatives.send', side_effect=SMTPException('down'))
    def test_async_smtp_failure_is_retried(self, _send):
        class Retried(Exception):
            pass

        with mock.patch.object(send_login_code_task, 'retry', return_value=Retried()) as retry:
            with self.assertRaises(Retried):
                self._run_async(retries=0)
        self.assertEqual(retry.call_args.kwargs['countdown'], 5)
        self.assertIsInstance(retry.call_args.kwargs['exc'], SMTPException)

    @mock.patch('apps.core.email.EmailMultiAlternatives.send', side_effect=SMTPException('down'))
    def test_exhausted_retries_log_without_code_or_address(self, _send):
        with mock.patch.object(send_login_code_task, 'retry') as retry, \
                self.assertLogs('apps.accounts.tasks', 'ERROR') as logs:
            self._run_async(retries=send_login_code_task.max_retries)
        retry.assert_not_called()
        output = '\n'.join(logs.output)
        self.assertNotIn(EMAIL, output)
        code = CODE_RE.search(output)
        self.assertIsNone(code)

    @mock.patch('apps.core.email.EmailMultiAlternatives.send', side_effect=SMTPException('down'))
    def test_eager_smtp_failure_never_reaches_the_request(self, _send):
        # Real enqueue: dev/test settings run the task eagerly with propagation on.
        self.assertTrue(settings.CELERY_TASK_ALWAYS_EAGER)
        with self.assertLogs('apps.accounts.tasks', 'ERROR') as logs:
            response = self.request_code()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'detail': GENERIC})
        self.assertNotIn(EMAIL, '\n'.join(logs.output))

    def test_task_expires_with_the_code_lifetime(self):
        self.assertEqual(send_login_code_task.expires, settings.OTP_TTL_SECONDS)


class EmailOtpVerifyTests(EmailOtpTestCase):
    def test_correct_code_returns_tokens_with_current_claims(self):
        self.owner.set_password('Another-Kite-88')
        self.owner.save()  # bumps auth_version
        self.owner.refresh_from_db()
        response = self.verify(email_code(self.owner))
        self.assertEqual(response.status_code, 200)
        self.assertIn('refresh', response.data)
        claims = AccessToken(response.data['access'])
        self.assertEqual(claims['role'], Role.OWNER)
        self.assertEqual(claims['tenant_id'], str(self.tenant.id))
        self.assertEqual(claims['auth_version'], self.owner.auth_version)
        self.assertEqual(claims['auth_version'], 1)

    def test_email_is_case_insensitive(self):
        self.assertEqual(self.verify(email_code(self.owner), email=' OWNER@Example.com').status_code, 200)

    def test_success_marks_the_email_verified(self):
        User.objects.filter(pk=self.owner.pk).update(email_verified=False)
        self.owner.refresh_from_db()
        before = self.owner.updated_at
        # Unverified email does not gate this path: the code proves the inbox.
        self.assertEqual(self.verify(email_code(self.owner)).status_code, 200)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.email_verified)
        self.assertGreater(self.owner.updated_at, before)

    def test_already_verified_email_stays_verified_and_untouched(self):
        before = self.owner.updated_at
        self.assertEqual(self.verify(email_code(self.owner)).status_code, 200)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.email_verified)
        self.assertEqual(self.owner.updated_at, before)

    def test_wrong_code_does_not_verify_the_email(self):
        User.objects.filter(pk=self.owner.pk).update(email_verified=False)
        code = email_code(self.owner)
        response = self.verify(self.wrong(code))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data.get('code'), 'INVALID_OTP')
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.email_verified)

    def test_malformed_code_is_400_and_uses_no_attempt(self):
        email_code(self.owner)
        for code in ['12ab56', '1234567', '12345', '', ' 123456x']:
            with self.subTest(code=code):
                self.assertEqual(self.verify(code).status_code, 400)
        self.assertEqual(OtpCode.objects.get(user=self.owner, used=False).attempts, 0)

    def test_code_is_single_use(self):
        code = email_code(self.owner)
        self.assertEqual(self.verify(code).status_code, 200)
        self.assertEqual(self.verify(code).status_code, 401)

    def test_expired_code_rejected(self):
        code = email_code(self.owner)
        OtpCode.objects.filter(user=self.owner).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.verify(code).status_code, 401)

    def test_attempts_are_limited_and_the_count_persists(self):
        code = email_code(self.owner)
        for _ in range(settings.OTP_MAX_ATTEMPTS):
            self.assertEqual(self.verify(self.wrong(code)).status_code, 401)
        self.assertEqual(
            OtpCode.objects.get(user=self.owner, used=False).attempts, settings.OTP_MAX_ATTEMPTS
        )
        self.assertEqual(self.verify(code).status_code, 401)

    def test_new_email_code_invalidates_only_the_previous_email_code(self):
        phone_code = otp.issue(self.owner, OtpCode.Channel.PHONE)
        first = email_code(self.owner)
        second = email_code(self.owner)
        self.assertEqual(self.verify(first).status_code, 401)
        self.assertEqual(self.verify(second).status_code, 200)
        phone = self.client.post(reverse('auth-otp-verify'), {'phone': PHONE, 'code': phone_code})
        self.assertEqual(phone.status_code, 200)

    def test_codes_do_not_cross_channels(self):
        phone_code = otp.issue(self.owner, OtpCode.Channel.PHONE)
        email_only = email_code(self.owner)
        self.assertEqual(self.verify(phone_code).status_code, 401)
        phone = self.client.post(reverse('auth-otp-verify'), {'phone': PHONE, 'code': email_only})
        self.assertEqual(phone.status_code, 401)

    def test_a_code_for_one_user_cannot_authenticate_another(self):
        other_tenant = self.create_tenant('Other PG')
        self.create_owner(other_tenant, email='other@example.com')
        code = email_code(self.owner)
        self.assertEqual(self.verify(code, email='other@example.com').status_code, 401)

    def test_deactivated_accounts_code_cannot_authenticate_a_reused_address(self):
        code = email_code(self.owner)
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        # Re-employment: a new active account takes the freed address.
        self.create_owner(self.create_tenant('New PG'), email=EMAIL)
        self.assertEqual(self.verify(code).status_code, 401)

    def test_blocked_tenants_get_no_tokens(self):
        for status in (Tenant.Status.SUSPENDED, Tenant.Status.CANCELLED):
            with self.subTest(status=status):
                Tenant.objects.filter(pk=self.tenant.pk).update(status=status)
                response = self.verify(email_code(self.owner))
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.data.get('code'), 'SUBSCRIPTION_SUSPENDED')
                self.assertNotIn('access', response.data)

    def test_super_admin_cannot_use_email_code_login(self):
        admin = self.create_super_admin()
        response = self.verify(email_code(admin), email=admin.email)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data.get('code'), 'INVALID_OTP')

    @mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {'otp_email_verify': '2/min'})
    def test_verify_is_rate_limited_per_ip(self):
        for _ in range(2):
            self.assertEqual(self.verify('000000').status_code, 401)
        self.assertEqual(self.verify('000000').status_code, 429)


class EmailOtpIntegrationTests(EmailOtpTestCase):
    def test_request_then_verify_end_to_end(self):
        # Eager Celery (dev/test settings) delivers into the locmem outbox.
        self.assertEqual(self.request_code(' Owner@Example.com').status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        code = CODE_RE.search(mail.outbox[0].body).group(1)
        response = self.verify(code)
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)


class PhoneOtpDeliveryLogTests(AuthAPITestCase):
    def test_phone_code_is_never_logged_outside_debug(self):
        tenant = self.create_tenant()
        owner = self.create_owner(tenant, phone=PHONE)
        with self.settings(DEBUG=False), self.assertLogs('apps.accounts.otp', 'INFO') as logs:
            code = otp.issue(owner, OtpCode.Channel.PHONE)
            otp._deliver(owner, code)
        self.assertNotIn(code, '\n'.join(logs.output))


class EmailOtpIssueConcurrencyTests(TransactionTestCase):
    """Issuance serializes on the user row (needs real commits, so no TestCase wrap)."""

    def _fixture_teardown(self):
        pass  # see residents/tests/test_lock_ordering.py: the default flush wipes seeded tables

    def setUp(self):
        self.tenant = AuthAPITestCase.create_tenant('Concurrency PG')
        self.owner = AuthAPITestCase.create_owner(self.tenant, email='race@email-otp.example.com')

    def tearDown(self):
        self.tenant.delete()  # cascades to users and their codes

    def test_issue_waits_for_the_user_row_lock(self):
        holding, release, done = threading.Event(), threading.Event(), threading.Event()

        def hold_lock():
            try:
                with transaction.atomic():
                    User.objects.select_for_update().get(pk=self.owner.pk)
                    holding.set()
                    release.wait(timeout=10)
            finally:
                connection.close()

        def issuer():
            try:
                otp.issue(self.owner, OtpCode.Channel.EMAIL)
            finally:
                done.set()
                connection.close()

        holder = threading.Thread(target=hold_lock)
        holder.start()
        self.assertTrue(holding.wait(timeout=10))
        thread = threading.Thread(target=issuer)
        thread.start()
        time.sleep(0.6)
        self.assertFalse(done.is_set())  # blocked on the row lock
        release.set()
        holder.join(timeout=10)
        thread.join(timeout=10)
        self.assertTrue(done.is_set())

    def test_verify_locks_the_user_row_before_the_code_row(self):
        """Same lock order as issue(). While verify waits on a user lock (as held
        by a resend in progress), it must not already hold the code row; if it
        did, the resend's invalidation would wait on verify, and verify's
        email_verified update on the resend: a deadlock."""
        User.objects.filter(pk=self.owner.pk).update(email_verified=False)
        code = otp.issue(self.owner, OtpCode.Channel.EMAIL)
        holding, release, done = threading.Event(), threading.Event(), threading.Event()
        result = {}

        def hold_user_lock():
            try:
                with transaction.atomic():
                    User.objects.select_for_update().get(pk=self.owner.pk)
                    holding.set()
                    release.wait(timeout=10)
            finally:
                connection.close()

        def verifier():
            try:
                result['ok'] = otp.verify(self.owner, code, OtpCode.Channel.EMAIL)
            finally:
                done.set()
                connection.close()

        holder = threading.Thread(target=hold_user_lock)
        holder.start()
        self.assertTrue(holding.wait(timeout=10))
        thread = threading.Thread(target=verifier)
        thread.start()
        time.sleep(0.6)
        try:
            self.assertFalse(done.is_set())  # verify is waiting on the user row
            with transaction.atomic():
                # Raises DatabaseError if verify had locked the code row first.
                list(OtpCode.objects.select_for_update(nowait=True).filter(user=self.owner))
        finally:
            release.set()
            holder.join(timeout=10)
            thread.join(timeout=10)
        self.assertTrue(result.get('ok'))
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.email_verified)

    def test_concurrent_resend_and_verify_both_complete(self):
        """A resend racing a first-time email verification: no deadlock, and
        each finishes (verify either consumed the old code or found it replaced)."""
        User.objects.filter(pk=self.owner.pk).update(email_verified=False)
        rounds = 10
        errors = []
        for _ in range(rounds):
            code = otp.issue(self.owner, OtpCode.Channel.EMAIL)
            barrier = threading.Barrier(2)

            def run(fn):
                try:
                    barrier.wait(timeout=10)
                    fn()
                except Exception as exc:  # noqa: BLE001 — collected and asserted below
                    errors.append(exc)
                finally:
                    connection.close()

            threads = [
                threading.Thread(target=run, args=(lambda: otp.issue(self.owner, OtpCode.Channel.EMAIL),)),
                threading.Thread(target=run, args=(lambda c=code: otp.verify(self.owner, c, OtpCode.Channel.EMAIL),)),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20)
            User.objects.filter(pk=self.owner.pk).update(email_verified=False)
        self.assertEqual(errors, [])

    def test_concurrent_requests_leave_exactly_one_usable_code(self):
        workers = 5
        barrier = threading.Barrier(workers)
        codes = []

        def issuer():
            try:
                barrier.wait(timeout=10)
                codes.append(otp.issue(self.owner, OtpCode.Channel.EMAIL))
            finally:
                connection.close()

        threads = [threading.Thread(target=issuer) for _ in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        self.assertEqual(len(codes), workers)
        self.assertEqual(
            OtpCode.objects.filter(user=self.owner, channel=OtpCode.Channel.EMAIL, used=False).count(), 1
        )
        usable = [code for code in codes if otp.verify(self.owner, code, OtpCode.Channel.EMAIL)]
        self.assertEqual(len(usable), 1)
