"""Account deletion (Module 22): requesting, confirming, the lock, cancelling and the login gate.
The purge itself is in test_account_deletion_purge.py."""
import uuid
from datetime import datetime, time, timedelta

from django.core import mail
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts import deletion, otp
from apps.accounts.models import AccountDeletionRequest, OtpCode, Tenant, User
from apps.accounts.serializers import LoginSerializer
from apps.audit.models import AuditLog
from apps.core.models import PlatformConfig
from apps.core.periods import first_midnight_ist_at_or_after, next_midnight_ist
from apps.core.roles import Role
from apps.core.tenancy import tenant_context

from .base import STRONG_PASSWORD, AuthAPITestCase

Status = AccountDeletionRequest.Status
Scope = AccountDeletionRequest.Scope


def ist(year, month, day, hour=0, minute=0, second=0):
    return timezone.make_aware(datetime(year, month, day, hour, minute, second))


class DeletionTestCase(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.manager = self.create_user(self.tenant, Role.MANAGER, 'manager@example.com')
        self.url = reverse('auth-account-deletion')

    def request_deletion(self, user, **extra):
        self.authenticate(User.objects.get(pk=user.pk))  # fresh auth_version, as a real client would hold
        return self.client.post(self.url, {'password': STRONG_PASSWORD, 'confirm': True, **extra}, format='json')

    def tokens_from(self, response):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")


class SchedulingTests(AuthAPITestCase):
    def test_next_midnight_is_always_the_following_calendar_day(self):
        self.assertEqual(next_midnight_ist(ist(2026, 10, 23, 14, 30)), ist(2026, 10, 24))
        # Exactly at midnight: still the *next* one, so a failure then is not retried in the same run.
        self.assertEqual(next_midnight_ist(ist(2026, 10, 24)), ist(2026, 10, 25))
        self.assertEqual(next_midnight_ist(ist(2026, 12, 31, 23, 59, 59)), ist(2027, 1, 1))

    def test_first_midnight_at_or_after_keeps_an_exact_midnight(self):
        self.assertEqual(first_midnight_ist_at_or_after(ist(2026, 10, 24)), ist(2026, 10, 24))
        self.assertEqual(first_midnight_ist_at_or_after(ist(2026, 10, 24, 0, 0, 1)), ist(2026, 10, 25))

    def test_grace_is_at_least_the_full_period(self):
        # A request at 23:59 IST must not lose a day to the midnight snapping: it is purged on the
        # first midnight that is >= 7 x 24h later, not "six days and one minute" later.
        requested = ist(2026, 10, 23, 23, 59)
        when = deletion.scheduled_for(requested, 7)
        self.assertGreaterEqual(when, requested + timedelta(days=7))
        self.assertEqual(when, ist(2026, 10, 31))
        self.assertEqual(timezone.localtime(when).time(), time.min)

    def test_grace_follows_platform_config(self):
        requested = ist(2026, 10, 23, 10)
        self.assertEqual(deletion.scheduled_for(requested, 1), ist(2026, 10, 25))
        self.assertEqual(deletion.scheduled_for(requested, 30), ist(2026, 11, 23))


class RoleHelperTests(AuthAPITestCase):
    def test_eligibility_is_by_role_never_by_missing_tenant(self):
        # A tenant-less *resident* (a future account type) must not be mistaken for a Super Admin.
        resident = User(role=Role.RESIDENT, tenant=None, first_name='R')
        super_admin = User(role=Role.SUPER_ADMIN, tenant=None, first_name='S')
        self.assertFalse(deletion.can_request_deletion(resident))
        self.assertFalse(deletion.can_request_deletion(super_admin))
        for role in (Role.OWNER, Role.MANAGER, Role.RECEPTIONIST):
            self.assertTrue(deletion.can_request_deletion(User(role=role, first_name='X')))

    def test_active_lookup_does_not_assume_a_tenant(self):
        resident = User(role=Role.RESIDENT, tenant=None, first_name='R')
        resident.id = uuid.uuid4()
        self.assertIsNone(deletion.active_request_for(resident))


class RequestTests(DeletionTestCase):
    def test_owner_request_is_tenant_scope_and_locks_the_business(self):
        response = self.request_deletion(self.owner, reason='closing down')
        self.assertEqual(response.status_code, 201, response.data)
        created = AccountDeletionRequest.objects.get()
        self.assertEqual(created.scope, Scope.TENANT)
        self.assertEqual(created.tenant_id, self.tenant.id)
        self.assertEqual(created.status, Status.PENDING)
        self.assertEqual(response.data['deletion']['scope'], 'tenant')
        self.assertTrue(response.data['deletion']['can_cancel'])
        self.assertGreaterEqual(created.scheduled_for, created.requested_at + timedelta(days=7))
        self.assertEqual(created.next_attempt_at, created.scheduled_for)

    def test_staff_request_is_user_scope(self):
        response = self.request_deletion(self.manager)
        self.assertEqual(response.status_code, 201, response.data)
        created = AccountDeletionRequest.objects.get()
        self.assertEqual((created.scope, created.user_id), (Scope.USER, self.manager.id))

    def test_scheduled_date_follows_platform_config(self):
        config = PlatformConfig.get()
        config.account_deletion_grace_days = 3
        config.save()
        self.request_deletion(self.manager)
        created = AccountDeletionRequest.objects.get()
        self.assertGreaterEqual(created.scheduled_for, created.requested_at + timedelta(days=3))
        self.assertLess(created.scheduled_for, created.requested_at + timedelta(days=4))

    def test_super_admin_cannot_use_the_flow(self):
        admin = self.create_super_admin()
        response = self.request_deletion(admin)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AccountDeletionRequest.objects.exists())

    def test_wrong_password_is_rejected(self):
        self.authenticate(self.owner)
        response = self.client.post(self.url, {'password': 'nope-nope-1', 'confirm': True}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AccountDeletionRequest.objects.exists())

    def test_confirm_flag_and_a_credential_are_required(self):
        self.authenticate(self.owner)
        self.assertEqual(self.client.post(self.url, {'password': STRONG_PASSWORD}, format='json').status_code, 400)
        self.assertEqual(
            self.client.post(self.url, {'password': STRONG_PASSWORD, 'confirm': False}, format='json').status_code, 400)
        self.assertEqual(self.client.post(self.url, {'confirm': True}, format='json').status_code, 400)
        self.assertEqual(
            self.client.post(self.url, {'confirm': True, 'password': STRONG_PASSWORD, 'otp': '123456'},
                             format='json').status_code, 400)

    def test_a_deletion_code_confirms_the_request(self):
        self.authenticate(self.owner)
        self.assertEqual(self.client.post(reverse('auth-account-deletion-otp')).status_code, 202)
        # The code is issued inside the worker (eager here); read it back through the real service.
        code = otp.issue(self.owner, otp.Channel.EMAIL, purpose=OtpCode.Purpose.ACCOUNT_DELETION)
        response = self.client.post(self.url, {'otp': code, 'confirm': True}, format='json')
        self.assertEqual(response.status_code, 201, response.data)

    def test_a_login_code_cannot_authorise_deletion(self):
        login_code = otp.issue(self.owner, otp.Channel.EMAIL)  # purpose=login
        self.authenticate(self.owner)
        response = self.client.post(self.url, {'otp': login_code, 'confirm': True}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AccountDeletionRequest.objects.exists())

    def test_a_deletion_code_cannot_log_in(self):
        code = otp.issue(self.owner, otp.Channel.EMAIL, purpose=OtpCode.Purpose.ACCOUNT_DELETION)
        self.assertFalse(otp.verify(self.owner, code, otp.Channel.EMAIL))  # default purpose = login

    def test_phone_code_is_unavailable_without_sms(self):
        self.authenticate(self.manager)
        # Staff in these tests have an email too, so the email code is offered; phone never is.
        self.assertNotIn('otp_phone', deletion.confirm_methods(self.manager))

    def test_a_phone_only_user_is_not_offered_a_code(self):
        phone_only = User.objects.create_user(
            tenant=self.tenant, role=Role.RECEPTIONIST, phone='9811111111', first_name='P', password=STRONG_PASSWORD)
        self.assertEqual(deletion.confirm_methods(phone_only), ['password'])
        self.authenticate(phone_only)
        response = self.client.post(reverse('auth-account-deletion-otp'))
        self.assertEqual(response.status_code, 400)

    def test_second_request_is_a_conflict(self):
        self.assertEqual(self.request_deletion(self.manager).status_code, 201)
        with self.assertRaises(Exception):
            deletion.create_request(self.manager)  # the partial unique index is the arbiter

    def test_staff_of_a_deleting_business_cannot_also_request(self):
        self.request_deletion(self.owner)
        self.authenticate(User.objects.get(pk=self.manager.pk))
        response = self.client.post(self.url, {'password': STRONG_PASSWORD, 'confirm': True}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_requesting_ends_other_sessions_but_the_returned_pair_works(self):
        self.authenticate(self.owner)
        old_access = self.client._credentials['HTTP_AUTHORIZATION']
        response = self.client.post(self.url, {'password': STRONG_PASSWORD, 'confirm': True}, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=old_access)
        self.assertEqual(self.client.get(reverse('auth-me')).status_code, 401)  # password_changed
        self.tokens_from(response)
        self.assertEqual(self.client.get(reverse('auth-me')).status_code, 200)

    def test_owner_request_ends_every_session_in_the_business(self):
        self.authenticate(self.manager)
        manager_auth = self.client._credentials['HTTP_AUTHORIZATION']
        self.request_deletion(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=manager_auth)
        self.assertEqual(self.client.get(reverse('auth-me')).status_code, 401)

    def test_a_confirmation_email_is_sent_with_the_date(self):
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.request_deletion(self.owner)
        subjects = [m.subject for m in mail.outbox]
        self.assertIn('Your account is scheduled for deletion', subjects)

    def test_request_is_audited(self):
        self.request_deletion(self.owner)
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='account.deletion_requested').exists())

    def test_emails_and_errors_follow_the_users_language(self):
        # Invariant 7: English and Telugu ship. A Telugu user gets a Telugu email and Telugu API errors.
        User.objects.filter(pk=self.owner.pk).update(language_code='te')
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.request_deletion(self.owner)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotEqual(mail.outbox[0].subject, 'Your account is scheduled for deletion')
        self.assertNotIn('Your account', mail.outbox[0].subject)
        other = self.create_user(self.create_tenant('Other Biz'), Role.MANAGER, 'm2@example.com')
        self.authenticate(other)
        response = self.client.post(
            self.url, {'password': 'wrong-password-1', 'confirm': True}, format='json', HTTP_ACCEPT_LANGUAGE='te')
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response.data['password'][0], 'Incorrect password.')


class LockTests(DeletionTestCase):
    def locked_owner(self):
        response = self.request_deletion(self.owner)
        self.tokens_from(response)
        return response

    def test_me_get_and_deletion_get_work_while_locked(self):
        self.locked_owner()
        me = self.client.get(reverse('auth-me'))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data['deletion']['status'], 'pending')
        self.assertTrue(me.data['deletion']['can_cancel'])
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_everything_else_is_a_403_with_the_deletion_code(self):
        self.locked_owner()
        response = self.client.get(reverse('tenant-current'))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'ACCOUNT_DELETION_PENDING')

    def test_me_patch_is_blocked_by_method(self):
        self.locked_owner()
        response = self.client.patch(reverse('auth-me'), {'first_name': 'New'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_staff_of_a_deleting_business_get_the_tenant_code_and_cannot_cancel(self):
        self.request_deletion(self.owner)
        self.authenticate(self.manager)
        # Their old token died with the bump; log in again — allowed, to see the state.
        login = self.client.post(
            reverse('auth-login'), {'email': 'manager@example.com', 'password': STRONG_PASSWORD}, format='json')
        self.assertEqual(login.status_code, 200, login.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        blocked = self.client.get(reverse('tenant-current'))
        self.assertEqual((blocked.status_code, blocked.data['code']), (403, 'TENANT_DELETION_PENDING'))
        me = self.client.get(reverse('auth-me'))
        self.assertEqual(me.data['deletion']['scope'], 'tenant')
        self.assertFalse(me.data['deletion']['can_cancel'])
        self.assertEqual(self.client.delete(self.url).status_code, 403)

    def test_tenant_suspended_during_grace_still_lets_the_owner_in(self):
        self.request_deletion(self.owner)
        Tenant.objects.filter(pk=self.tenant.pk).update(status=Tenant.Status.SUSPENDED)
        login = self.client.post(
            reverse('auth-login'), {'email': 'owner@example.com', 'password': STRONG_PASSWORD}, format='json')
        self.assertEqual(login.status_code, 200, login.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        self.assertEqual(self.client.get(reverse('auth-me')).status_code, 200)
        blocked = self.client.get(reverse('tenant-current'))
        self.assertEqual(blocked.data['code'], 'ACCOUNT_DELETION_PENDING')  # not subscription_suspended
        refresh = self.client.post(reverse('auth-token-refresh'), {'refresh': login.data['refresh']}, format='json')
        self.assertEqual(refresh.status_code, 200, refresh.data)

    def test_without_a_request_a_suspended_tenant_is_still_refused_everywhere(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(status=Tenant.Status.SUSPENDED)
        login = self.client.post(
            reverse('auth-login'), {'email': 'owner@example.com', 'password': STRONG_PASSWORD}, format='json')
        self.assertEqual(login.status_code, 401)
        token = LoginSerializer.get_token(self.owner)
        refresh = self.client.post(reverse('auth-token-refresh'), {'refresh': str(token)}, format='json')
        self.assertEqual(refresh.status_code, 401)

    def test_failed_requests_stay_locked_and_visible(self):
        self.request_deletion(self.owner)
        AccountDeletionRequest.objects.update(status=Status.FAILED)
        token = LoginSerializer.get_token(User.objects.get(pk=self.owner.pk))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        me = self.client.get(reverse('auth-me'))
        self.assertEqual((me.data['deletion']['status'], me.data['deletion']['can_cancel']), ('failed', False))
        self.assertEqual(self.client.get(reverse('tenant-current')).status_code, 403)
        # And no duplicate request can be created on top of it.
        with self.assertRaises(Exception):
            deletion.create_request(User.objects.get(pk=self.owner.pk))


class CancelTests(DeletionTestCase):
    def test_owner_cancels_a_pending_request_and_is_unlocked(self):
        response = self.request_deletion(self.owner, reason='private')
        self.tokens_from(response)
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        cancelled = AccountDeletionRequest.objects.get()
        self.assertEqual((cancelled.status, cancelled.reason), (Status.CANCELLED, ''))
        self.assertIsNotNone(cancelled.cancelled_at)
        self.assertEqual(self.client.get(reverse('tenant-current')).status_code, 200)
        with tenant_context(self.tenant.id):
            self.assertTrue(AuditLog.objects.filter(action='account.deletion_cancelled').exists())

    def test_a_new_request_is_possible_after_cancelling(self):
        self.tokens_from(self.request_deletion(self.manager))
        self.client.delete(self.url)
        self.assertEqual(self.request_deletion(self.manager).status_code, 201)

    def test_nothing_to_cancel_is_a_404(self):
        self.authenticate(self.owner)
        self.assertEqual(self.client.delete(self.url).status_code, 404)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_user_cannot_cancel_once_processing_failed_or_completed(self):
        self.tokens_from(self.request_deletion(self.manager))
        for status in (Status.PROCESSING, Status.FAILED):
            AccountDeletionRequest.objects.update(status=status)
            self.assertEqual(self.client.delete(self.url).status_code, 409, status)

    def test_admin_resolution_only_while_reversible(self):
        self.request_deletion(self.owner)
        row = AccountDeletionRequest.objects.get()
        row.status = Status.FAILED
        row.razorpay_closed_at = timezone.now()
        row.save()
        with self.assertRaises(Exception):
            deletion.resolve_as_cancelled(row, actor=self.create_super_admin(), note='x')
        row.razorpay_closed_at = None
        row.save()
        resolved = deletion.resolve_as_cancelled(row, actor=self.create_super_admin(email='a2@x.com'), note='x')
        self.assertEqual(resolved.status, Status.CANCELLED)

    def test_admin_resolution_after_the_notice_sends_a_cancellation_email(self):
        self.request_deletion(self.manager)
        row = AccountDeletionRequest.objects.get()
        row.notified_at = timezone.now()
        row.save()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            deletion.resolve_as_cancelled(row, actor=self.create_super_admin(), note='verified by phone')
        self.assertIn('Your account deletion was cancelled', [m.subject for m in mail.outbox])


class OneOwnerTests(AuthAPITestCase):
    def test_a_second_active_owner_is_rejected_by_the_database(self):
        tenant = self.create_tenant()
        self.create_owner(tenant)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_owner(tenant, email="second@example.com")

    def test_an_inactive_owner_does_not_count(self):
        tenant = self.create_tenant()
        old = self.create_owner(tenant)
        User.objects.filter(pk=old.pk).update(is_active=False)
        self.create_owner(tenant, email='new@example.com')  # re-employment of the Owner role is fine
