"""Signup email verification: the address-bound token (checked under a row
lock), the three delivery tasks (welcome / account-bound / address-based), the
always-queued resend endpoint, and the audited Django-admin paths. See
docs/modules/01-auth-tenancy.md (Decisions)."""
import threading
import time
from smtplib import SMTPException
from unittest import mock

from django.conf import settings
from django.contrib import admin
from django.core import mail, signing
from django.db import connection, transaction
from django.test import RequestFactory, TransactionTestCase
from django.urls import reverse
from kombu.exceptions import OperationalError
from rest_framework.throttling import SimpleRateThrottle

from apps.accounts.admin import UserAdmin
from apps.accounts.emails import send_verification_email
from apps.accounts.models import Tenant, User
from apps.accounts.serializers import EmailVerificationSerializer, LoginSerializer
from apps.accounts.tasks import (
    send_verification_email_to_address_task,
    send_verification_email_to_user_task,
    send_welcome_email_task,
)
from apps.accounts.tokens import EMAIL_VERIFICATION_SALT, make_email_verification_token
from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.notifications.models import NotificationLog

from .base import STRONG_PASSWORD, AuthAPITestCase

EMAIL = 'owner@example.com'
RESEND_GENERIC = 'If that email is registered, a verification link has been sent.'


class VerificationTestCase(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant, email=EMAIL, email_verified=False)

    def verify(self, token):
        return self.client.post(reverse('auth-verify-email'), {'token': token})

    def resend(self, email, **extra):
        return self.client.post(reverse('auth-resend-verification'), {'email': email}, **extra)

    def refresh(self, user):
        user.refresh_from_db()
        return user


class VerificationTokenTests(VerificationTestCase):
    def test_valid_token_verifies_and_is_idempotent(self):
        token = make_email_verification_token(self.owner)
        self.assertEqual(self.verify(token).status_code, 200)
        self.assertTrue(self.refresh(self.owner).email_verified)
        self.assertEqual(self.verify(token).status_code, 200)  # already verified: no-op success

    def test_expired_token_is_rejected(self):
        issued_at = 1_900_000_000
        with mock.patch('django.core.signing.time.time', return_value=issued_at):
            token = make_email_verification_token(self.owner)
        later = issued_at + settings.EMAIL_VERIFICATION_TTL_SECONDS + 1
        with mock.patch('django.core.signing.time.time', return_value=later):
            serializer = EmailVerificationSerializer(data={'token': token})
            self.assertFalse(serializer.is_valid())
        self.assertIn('token', serializer.errors)
        self.assertFalse(self.refresh(self.owner).email_verified)

    def test_legacy_uid_only_token_is_rejected(self):
        legacy = signing.dumps({'uid': str(self.owner.id)}, salt=EMAIL_VERIFICATION_SALT)
        response = self.verify(legacy)
        self.assertEqual(response.status_code, 400)
        self.assertIn('token', response.data)
        self.assertFalse(self.refresh(self.owner).email_verified)

    def test_inactive_users_token_is_rejected(self):
        token = make_email_verification_token(self.owner)
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.assertEqual(self.verify(token).status_code, 400)
        self.assertFalse(self.refresh(self.owner).email_verified)

    def test_link_for_the_old_address_cannot_verify_a_new_one(self):
        old_token = make_email_verification_token(self.owner)
        User.objects.filter(pk=self.owner.pk).update(email='moved@example.com')
        self.assertEqual(self.verify(old_token).status_code, 400)
        self.assertFalse(self.refresh(self.owner).email_verified)
        self.assertEqual(self.verify(make_email_verification_token(self.owner)).status_code, 200)

    def test_garbage_token_is_rejected(self):
        self.assertEqual(self.verify('not-a-token').status_code, 400)

    def test_link_carries_the_token_in_the_fragment(self):
        send_verification_email(self.owner)
        body = mail.outbox[0].body
        self.assertIn('/verify-email#token=', body)
        self.assertNotIn('?token=', body)
        token = self.extract_query_param(body, 'token')
        self.assertEqual(self.verify(token).status_code, 200)

    def test_email_is_written_in_the_users_language(self):
        User.objects.filter(pk=self.owner.pk).update(language_code='te')
        send_verification_email(self.refresh(self.owner))
        self.assertNotEqual(mail.outbox[0].subject, 'Verify your email address')


class VerificationRegressionTests(VerificationTestCase):
    def test_unverified_email_still_blocks_password_login(self):
        response = self.client.post(reverse('auth-login'), {'email': EMAIL, 'password': STRONG_PASSWORD})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data.get('code'), 'EMAIL_NOT_VERIFIED')

    def test_verifying_unblocks_password_login(self):
        self.verify(make_email_verification_token(self.owner))
        response = self.client.post(reverse('auth-login'), {'email': EMAIL, 'password': STRONG_PASSWORD})
        self.assertEqual(response.status_code, 200)


class ResendEndpointTests(VerificationTestCase):
    def test_every_address_gets_the_same_response_and_is_queued(self):
        self.create_owner(self.create_tenant('Done PG'), email='verified@example.com')
        self.create_owner(self.create_tenant('Gone PG'), email='gone@example.com', is_active=False)
        addresses = [
            (' Owner@Example.COM ', EMAIL),  # normalized before queueing
            ('nobody@example.com', 'nobody@example.com'),
            ('verified@example.com', 'verified@example.com'),
            ('gone@example.com', 'gone@example.com'),
        ]
        with mock.patch('apps.accounts.serializers.enqueue') as enqueue:
            for n, (raw, normalized) in enumerate(addresses):
                response = self.resend(raw, REMOTE_ADDR=f'203.0.113.{n + 1}')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, {'detail': RESEND_GENERIC})
                enqueue.assert_called_with(send_verification_email_to_address_task, normalized)
        self.assertEqual(enqueue.call_count, len(addresses))
        self.assertEqual(mail.outbox, [])  # nothing sent on the request path

    def test_broker_unavailable_still_returns_generic_response(self):
        with mock.patch.object(send_verification_email_to_address_task, 'delay',
                               side_effect=OperationalError('down')), \
                self.assertLogs('apps.core.tasks', 'ERROR'):
            response = self.resend(EMAIL)
        self.assertEqual(response.status_code, 200)

    @mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {'resend_verification_email': '2/hour'})
    def test_resends_are_rate_limited_per_email_across_ips(self):
        with mock.patch('apps.accounts.serializers.enqueue'):
            self.assertEqual(self.resend(EMAIL, REMOTE_ADDR='203.0.113.1').status_code, 200)
            self.assertEqual(self.resend(' OWNER@example.com', REMOTE_ADDR='203.0.113.2').status_code, 200)
            self.assertEqual(self.resend(EMAIL, REMOTE_ADDR='203.0.113.3').status_code, 429)
            self.assertEqual(self.resend('other@example.com', REMOTE_ADDR='203.0.113.3').status_code, 200)

    def test_malformed_bodies_are_400_not_500(self):
        url = reverse('auth-resend-verification')
        bodies = [
            {'data': '{not json', 'content_type': 'application/json'},
            {'data': [EMAIL], 'format': 'json'},
            {'data': {'email': 123}, 'format': 'json'},
        ]
        with mock.patch('apps.accounts.serializers.enqueue') as enqueue:
            for n, body in enumerate(bodies):
                with self.subTest(body=body):
                    response = self.client.post(url, REMOTE_ADDR=f'198.51.100.{n + 1}', **body)
                    self.assertEqual(response.status_code, 400)
        enqueue.assert_not_called()

    def test_end_to_end_resend_delivers_a_working_link(self):
        # Eager Celery (dev/test settings) delivers into the locmem outbox.
        self.assertEqual(self.resend(EMAIL).status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        token = self.extract_query_param(mail.outbox[0].body, 'token')
        self.assertEqual(self.verify(token).status_code, 200)

    def test_eager_smtp_failure_still_returns_200_and_logs_no_address(self):
        with mock.patch('apps.core.email.EmailMultiAlternatives.send', side_effect=SMTPException('down')), \
                self.assertLogs('apps.accounts.tasks', 'ERROR') as logs:
            response = self.resend(EMAIL)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(EMAIL, '\n'.join(logs.output))


class AddressTaskTests(VerificationTestCase):
    def test_sends_only_to_the_active_unverified_owner_of_the_address(self):
        send_verification_email_to_address_task.apply(args=[EMAIL])
        self.assertEqual([m.to for m in mail.outbox], [[EMAIL]])

    def test_verified_inactive_and_unknown_addresses_get_nothing(self):
        self.create_owner(self.create_tenant('Done PG'), email='verified@example.com')
        self.create_owner(self.create_tenant('Gone PG'), email='gone@example.com', is_active=False,
                          email_verified=False)
        for email in ['verified@example.com', 'gone@example.com', 'nobody@example.com']:
            send_verification_email_to_address_task.apply(args=[email])
        self.assertEqual(mail.outbox, [])


class AccountTaskTests(VerificationTestCase):
    def run_task(self, user, expected_email):
        send_verification_email_to_user_task.apply(args=[str(user.id), expected_email])

    def test_sends_to_the_account_it_was_queued_for(self):
        self.run_task(self.owner, EMAIL)
        self.assertEqual([m.to for m in mail.outbox], [[EMAIL]])

    def test_skips_a_deactivated_account(self):
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.run_task(self.owner, EMAIL)
        self.assertEqual(mail.outbox, [])

    def test_skips_when_the_address_changed_after_queueing(self):
        User.objects.filter(pk=self.owner.pk).update(email='moved@example.com')
        self.run_task(self.owner, EMAIL)
        self.assertEqual(mail.outbox, [])

    def test_cannot_be_retargeted_to_an_account_that_reused_the_address(self):
        # Queued for the owner; before it runs the owner leaves and someone else takes the address.
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        newcomer = self.create_owner(self.create_tenant('New PG'), email=EMAIL, email_verified=False)
        self.run_task(self.owner, EMAIL)
        self.assertEqual(mail.outbox, [])
        self.run_task(newcomer, EMAIL)  # the newcomer's own job is fine
        self.assertEqual(len(mail.outbox), 1)

    def test_skips_an_already_verified_account(self):
        User.objects.filter(pk=self.owner.pk).update(email_verified=True)
        self.run_task(self.owner, EMAIL)
        self.assertEqual(mail.outbox, [])


class WelcomeTaskTests(VerificationTestCase):
    def welcome_logs(self):
        with tenant_context(self.tenant.id):
            return list(NotificationLog.objects.filter(notification_type='welcome'))

    def test_sends_and_records_the_welcome(self):
        send_welcome_email_task.apply(args=[str(self.owner.id), EMAIL])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(self.welcome_logs()), 1)

    def test_skips_inactive_or_verified_accounts_and_records_nothing(self):
        for change in ({'is_active': False}, {'is_active': True, 'email_verified': True}):
            with self.subTest(change=change):
                User.objects.filter(pk=self.owner.pk).update(**change)
                send_welcome_email_task.apply(args=[str(self.owner.id), EMAIL])
                self.assertEqual(mail.outbox, [])
                self.assertEqual(self.welcome_logs(), [])

    def test_a_failed_send_is_not_recorded_as_sent(self):
        with mock.patch('apps.core.email.EmailMultiAlternatives.send', side_effect=SMTPException('down')), \
                self.assertLogs('apps.accounts.tasks', 'ERROR') as logs:
            send_welcome_email_task.apply(args=[str(self.owner.id), EMAIL])
        self.assertEqual(self.welcome_logs(), [])
        self.assertNotIn(EMAIL, '\n'.join(logs.output))

    def test_jobs_queued_before_expected_email_existed_are_dropped(self):
        # Such a job can't prove which address it was queued for.
        send_welcome_email_task.apply(args=[str(self.owner.id)])
        self.assertEqual(mail.outbox, [])
        self.assertEqual(self.welcome_logs(), [])

    def test_async_smtp_failure_is_retried(self):
        class Retried(Exception):
            pass

        send_welcome_email_task.push_request(is_eager=False, retries=0)
        try:
            with mock.patch('apps.core.email.EmailMultiAlternatives.send', side_effect=SMTPException('down')), \
                    mock.patch.object(send_welcome_email_task, 'retry', return_value=Retried()) as retry, \
                    self.assertRaises(Retried):
                send_welcome_email_task.run(str(self.owner.id), EMAIL)
        finally:
            send_welcome_email_task.pop_request()
        self.assertEqual(retry.call_args.kwargs['countdown'], 5)
        self.assertEqual(self.welcome_logs(), [])


class SignupAndStaffDeliveryTests(AuthAPITestCase):
    SIGNUP = {
        'business_name': 'Sunrise PG', 'first_name': 'Ramesh', 'email': 'ramesh@example.com',
        'password': STRONG_PASSWORD,
    }

    def test_signup_queues_the_welcome_task_with_the_address(self):
        with mock.patch('apps.accounts.serializers.enqueue') as enqueue, \
                self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(reverse('auth-signup'), self.SIGNUP).status_code, 201)
        user = User.objects.get(email='ramesh@example.com')
        enqueue.assert_called_once_with(send_welcome_email_task, str(user.id), 'ramesh@example.com')

    def test_signup_survives_an_smtp_failure(self):
        with mock.patch('apps.core.email.EmailMultiAlternatives.send', side_effect=SMTPException('down')), \
                self.assertLogs('apps.accounts.tasks', 'ERROR') as logs, \
                self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('auth-signup'), self.SIGNUP)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Tenant.objects.filter(name='Sunrise PG').exists())
        self.assertNotIn('ramesh@example.com', '\n'.join(logs.output))

    def test_staff_creation_queues_verification_and_survives_an_smtp_failure(self):
        tenant = self.create_tenant()
        self.authenticate(self.create_owner(tenant))
        payload = {
            'first_name': 'Desk', 'email': 'desk@example.com', 'phone': '9811100022',
            'role': Role.MANAGER, 'password': 'InitialPassword-999!',
        }
        with mock.patch('apps.core.email.EmailMultiAlternatives.send', side_effect=SMTPException('down')), \
                self.assertLogs('apps.accounts.tasks', 'ERROR'), \
                self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('staff-list'), payload)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(email='desk@example.com', is_active=True).exists())


class AdminVerificationTests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_superuser(email='root@example.com', password='x', first_name='Root')
        self.client.force_login(self.admin_user)  # Django admin uses session auth
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant, email=EMAIL, email_verified=False)
        self.model_admin = UserAdmin(User, admin.site)

    def admin_request(self):
        request = RequestFactory().post('/admin/accounts/user/')
        request.user = self.admin_user
        return request

    def run_action(self, action, users):
        return self.client.post(
            reverse('admin:accounts_user_changelist'),
            {'action': action, '_selected_action': [str(u.pk) for u in users]},
            follow=True,
        )

    def audit_rows(self, action):
        with tenant_context(is_super_admin=True):
            return list(AuditLog.objects.filter(action=action))

    def skip_fixtures(self):
        return [
            self.create_owner(self.create_tenant('A'), email='done@example.com'),  # already verified
            self.create_owner(self.create_tenant('B'), email='gone@example.com', is_active=False,
                              email_verified=False),
            self.create_user(self.tenant, Role.MANAGER, None, email_verified=False),  # no email
        ]

    def test_send_action_queues_audits_and_reports_counts(self):
        targets = [self.owner, *self.skip_fixtures()]
        with mock.patch('apps.accounts.admin.enqueue', return_value=object()) as enqueue:
            response = self.run_action('send_verification_email', targets)
        enqueue.assert_called_once_with(send_verification_email_to_user_task, str(self.owner.pk), EMAIL)
        self.assertContains(
            response,
            'Verification emails queued: 1. Broker unavailable: 0. '
            'Skipped — inactive: 1, no email: 1, already verified: 1.',
        )
        rows = self.audit_rows('user.verification_email_requested_by_admin')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].object_id, str(self.owner.pk))
        self.assertEqual(rows[0].after, {'email': EMAIL})
        self.assertEqual(rows[0].tenant_id, self.tenant.id)
        self.assertEqual(self.audit_rows('user.verification_email_queue_failed'), [])

    def test_send_action_counts_a_broker_failure_as_not_queued(self):
        with mock.patch('apps.accounts.admin.enqueue', return_value=None):
            response = self.run_action('send_verification_email', [self.owner])
        self.assertContains(response, 'Verification emails queued: 0. Broker unavailable: 1.')
        self.assertEqual(len(self.audit_rows('user.verification_email_requested_by_admin')), 1)
        failed = self.audit_rows('user.verification_email_queue_failed')
        self.assertEqual([r.after for r in failed], [{'email': EMAIL, 'queued': False}])

    def test_send_action_queues_nothing_if_the_audit_cannot_be_written(self):
        with mock.patch('apps.accounts.admin.audit_log.record', side_effect=RuntimeError('db down')), \
                mock.patch('apps.accounts.admin.enqueue') as enqueue, \
                self.assertRaises(RuntimeError):
            self.model_admin.send_verification_email(self.admin_request(), User.objects.filter(pk=self.owner.pk))
        enqueue.assert_not_called()

    def test_mark_verified_action_verifies_audits_and_skips_the_rest(self):
        before = self.owner.updated_at
        targets = [self.owner, *self.skip_fixtures()]
        response = self.run_action('mark_email_verified', targets)
        self.assertContains(
            response,
            'Marked verified: 1. Skipped — inactive: 1, no email: 1, already verified: 1.',
        )
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.email_verified)
        self.assertGreater(self.owner.updated_at, before)
        rows = self.audit_rows('user.email_verified_by_admin')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].before, rows[0].after), ({'email_verified': False}, {'email_verified': True}))

    def test_create_queues_verification_in_the_users_language(self):
        user = User(email='new@example.com', first_name='New', role=Role.OWNER, tenant=self.create_tenant('New Biz'),
                    language_code='te')
        user.set_password(STRONG_PASSWORD)
        with self.captureOnCommitCallbacks(execute=True):
            self.model_admin.save_model(self.admin_request(), user, form=None, change=False)
        self.assertEqual([m.to for m in mail.outbox], [['new@example.com']])
        self.assertNotEqual(mail.outbox[0].subject, 'Verify your email address')  # Telugu

    def test_case_only_email_edit_changes_nothing(self):
        User.objects.filter(pk=self.owner.pk).update(email_verified=True)
        obj = User.objects.get(pk=self.owner.pk)
        version = obj.auth_version
        obj.email = 'OWNER@example.com'
        with self.captureOnCommitCallbacks(execute=True):
            self.model_admin.save_model(self.admin_request(), obj, form=None, change=True)
        obj.refresh_from_db()
        self.assertTrue(obj.email_verified)
        self.assertEqual(obj.auth_version, version)
        self.assertEqual(mail.outbox, [])
        self.assertEqual(self.audit_rows('user.email_changed_by_admin'), [])

    def test_email_change_resets_verification_ends_sessions_audits_and_queues(self):
        User.objects.filter(pk=self.owner.pk).update(email_verified=True)
        obj = User.objects.get(pk=self.owner.pk)
        old_access = LoginSerializer.get_token(obj).access_token
        stale_version = obj.auth_version
        User.objects.filter(pk=obj.pk).update(auth_version=stale_version + 3)  # form object is stale
        obj.email = 'moved@example.com'
        with self.captureOnCommitCallbacks(execute=True):
            self.model_admin.save_model(self.admin_request(), obj, form=None, change=True)

        obj.refresh_from_db()
        self.assertFalse(obj.email_verified)
        self.assertEqual(obj.auth_version, stale_version + 4)  # from the locked row, not the form object
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {old_access}')
        me = self.client.get(reverse('auth-me'))
        self.assertEqual(me.status_code, 401)
        self.assertEqual(me.data.get('code'), 'PASSWORD_CHANGED')
        self.assertEqual([m.to for m in mail.outbox], [['moved@example.com']])
        rows = self.audit_rows('user.email_changed_by_admin')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].before['email'], EMAIL)
        self.assertEqual(rows[0].after, {'email': 'moved@example.com', 'email_verified': False,
                                         'auth_version': stale_version + 4})

    def test_email_verified_is_read_only_and_language_is_on_the_add_form(self):
        self.assertIn('email_verified', self.model_admin.get_readonly_fields(self.admin_request(), self.owner))
        add_fields = [f for _, opts in self.model_admin.add_fieldsets for f in opts['fields']]
        self.assertIn('language_code', add_fields)


class VerificationLockTests(TransactionTestCase):
    """Verification compares and marks under the user-row lock (needs real
    commits, so no TestCase wrap)."""

    def _fixture_teardown(self):
        pass  # see residents/tests/test_lock_ordering.py: the default flush wipes seeded tables

    def setUp(self):
        self.tenant = AuthAPITestCase.create_tenant('Verify Lock PG')
        self.owner = AuthAPITestCase.create_owner(
            self.tenant, email='lock@verify.example.com', email_verified=False
        )
        self.token = make_email_verification_token(self.owner)

    def tearDown(self):
        self.tenant.delete()

    def _verify_while_locked(self, change_inside_lock=None):
        holding, release, done = threading.Event(), threading.Event(), threading.Event()
        result = {}

        def hold_lock():
            try:
                with transaction.atomic():
                    User.objects.select_for_update().get(pk=self.owner.pk)
                    holding.set()
                    release.wait(timeout=10)
                    if change_inside_lock:
                        change_inside_lock()
            finally:
                connection.close()

        def verifier():
            try:
                serializer = EmailVerificationSerializer(data={'token': self.token})
                result['valid'] = serializer.is_valid()
                try:
                    serializer.save()
                    result['saved'] = True
                except Exception as exc:  # noqa: BLE001 — asserted below
                    result['saved'] = False
                    result['error'] = exc
            finally:
                done.set()
                connection.close()

        holder = threading.Thread(target=hold_lock)
        holder.start()
        self.assertTrue(holding.wait(timeout=10))
        thread = threading.Thread(target=verifier)
        thread.start()
        time.sleep(0.6)
        blocked = not done.is_set()
        release.set()
        holder.join(timeout=10)
        thread.join(timeout=10)
        return blocked, result

    def test_verification_waits_on_the_user_row_lock(self):
        blocked, result = self._verify_while_locked()
        self.assertTrue(blocked)
        self.assertEqual(result, {'valid': True, 'saved': True})
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.email_verified)

    def test_email_change_committed_while_waiting_makes_the_old_link_fail(self):
        blocked, result = self._verify_while_locked(
            lambda: User.objects.filter(pk=self.owner.pk).update(email='moved@verify.example.com')
        )
        self.assertTrue(blocked)
        self.assertTrue(result['valid'])  # signature fine; the account check happens under the lock
        self.assertFalse(result['saved'])
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.email_verified)
