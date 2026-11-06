"""Resident app accounts (Module 26): the second account pool and its auth endpoints.

A resident account is a person's own login, tenant-less, with its own email/phone uniqueness
pool, so one address can also hold a staff account. These tests prove the pools never mix and the
resident endpoints work end to end (signup, code verification, login, reset). See
docs/modules/26-resident-identity.md."""
import importlib
import io
import re

from django.apps import apps as django_apps
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import OtpCode, User
from apps.core.roles import Role

from .base import STRONG_PASSWORD, AuthAPITestCase

SHARED = 'person@example.com'
CODE_RE = re.compile(r'\b(\d{6})\b')


def last_code():
    """The 6-digit code in the most recent email."""
    return CODE_RE.search(mail.outbox[-1].body).group(1)


class ResidentPoolTestCase(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()

    def create_resident_account(self, email=SHARED, **kwargs):
        return self.create_user(None, Role.RESIDENT, email, **kwargs)

    def signup(self, email=SHARED, **extra):
        payload = {'email': email, 'first_name': 'Asha', **extra}
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('resident-signup'), payload)


class PoolSeparationTests(ResidentPoolTestCase):
    def test_same_email_can_hold_a_staff_and_a_resident_account(self):
        owner = self.create_owner(self.tenant, email=SHARED)
        resident = self.create_resident_account(SHARED)
        self.assertNotEqual(owner.pk, resident.pk)
        self.assertEqual(User.objects.staff_pool().get(email__iexact=SHARED).pk, owner.pk)
        self.assertEqual(User.objects.resident_pool().get(email__iexact=SHARED).pk, resident.pk)

    def test_resident_pool_is_unique_within_itself(self):
        self.create_resident_account(SHARED)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_resident_account(SHARED.upper())

    def test_staff_pool_is_still_unique(self):
        self.create_owner(self.tenant, email=SHARED)
        other = self.create_tenant('Other PG')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_owner(other, email=SHARED)

    def test_a_resident_account_cannot_belong_to_a_tenant(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(
                email='x@example.com', password=STRONG_PASSWORD, tenant=self.tenant,
                role=Role.RESIDENT, first_name='X',
            )

    def test_staff_login_ignores_the_resident_account_with_the_same_email(self):
        owner = self.create_owner(self.tenant, email=SHARED, password='Owner-Password-91')
        self.create_resident_account(SHARED, password='Resident-Password-77')
        ok = self.client.post(reverse('auth-login'), {'email': SHARED, 'password': 'Owner-Password-91'})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(AccessToken(ok.data['access'])['user_id'], str(owner.pk))
        # The resident's password does not work on the staff endpoint.
        bad = self.client.post(reverse('auth-login'), {'email': SHARED, 'password': 'Resident-Password-77'})
        self.assertEqual(bad.status_code, 401)

    def test_resident_login_ignores_the_staff_account_with_the_same_email(self):
        self.create_owner(self.tenant, email=SHARED, password='Owner-Password-91')
        resident = self.create_resident_account(SHARED, password='Resident-Password-77')
        ok = self.client.post(reverse('resident-login'), {'email': SHARED, 'password': 'Resident-Password-77'})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(AccessToken(ok.data['access'])['user_id'], str(resident.pk))
        bad = self.client.post(reverse('resident-login'), {'email': SHARED, 'password': 'Owner-Password-91'})
        self.assertEqual(bad.status_code, 401)

    def test_staff_email_code_never_goes_to_a_resident_only_address(self):
        self.create_resident_account(SHARED)
        self.client.post(reverse('auth-otp-email-request'), {'email': SHARED})
        self.assertEqual(len(mail.outbox), 0)

    def test_staff_password_reset_never_reaches_a_resident_account(self):
        self.create_resident_account(SHARED)
        self.client.post(reverse('auth-password-reset'), {'email': SHARED})
        self.assertEqual(len(mail.outbox), 0)

    def test_staff_signup_is_not_blocked_by_a_resident_account(self):
        self.create_resident_account('boss@example.com')
        response = self.client.post(reverse('auth-signup'), {
            'business_name': 'Boss PG', 'first_name': 'Boss', 'email': 'boss@example.com',
            'password': STRONG_PASSWORD,
        })
        self.assertEqual(response.status_code, 201)

    def test_django_admin_login_still_works_for_a_super_admin_sharing_an_email(self):
        admin = self.create_super_admin(email=SHARED, password='Admin-Password-55', is_staff=True, is_superuser=True)
        self.create_resident_account(SHARED, password='Resident-Password-77')
        self.assertTrue(self.client.login(email=SHARED, password='Admin-Password-55'))
        self.assertEqual(self.client.get('/admin/').status_code, 200)
        self.client.logout()
        # The resident account can never open the admin.
        self.assertFalse(self.client.login(email=SHARED, password='Resident-Password-77'))
        self.assertEqual(admin.email, SHARED)

    def test_natural_key_lookup_is_staff_only(self):
        owner = self.create_owner(self.tenant, email=SHARED)
        self.create_resident_account(SHARED)
        self.assertEqual(User.objects.get_by_natural_key(SHARED).pk, owner.pk)


class ResidentCannotUseStaffEndpointsTests(ResidentPoolTestCase):
    """The project default permission is closed to the resident pool, so a view nobody opted in
    cannot be reached by a resident."""

    def test_resident_gets_403_on_staff_endpoints(self):
        resident = self.create_resident_account()
        self.authenticate(resident)
        for name in ('staff-list', 'property-list', 'resident-list', 'invoice-list', 'complaint-list'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_resident_can_read_their_own_profile(self):
        resident = self.create_resident_account()
        self.authenticate(resident)
        response = self.client.get(reverse('auth-me'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['role'], Role.RESIDENT)
        self.assertIsNone(response.data['tenant'])


class ResidentSignupTests(ResidentPoolTestCase):
    def test_signup_creates_an_unverified_tenantless_account_and_emails_a_code(self):
        response = self.signup()
        self.assertEqual(response.status_code, 201)
        user = User.objects.resident_pool().get(email=SHARED)
        self.assertIsNone(user.tenant_id)
        self.assertFalse(user.email_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [SHARED])
        self.assertTrue(CODE_RE.search(mail.outbox[0].body))

    def test_signup_with_an_address_that_has_a_verified_account_answers_the_same(self):
        self.create_resident_account(SHARED)
        before = User.objects.count()
        response = self.signup()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(User.objects.count(), before)
        # They are told they already have an account; nothing else, and no code.
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('already have an account', mail.outbox[0].body)
        self.assertFalse(CODE_RE.search(mail.outbox[0].body))

    def test_signup_does_not_overwrite_an_existing_password(self):
        existing = self.create_resident_account(SHARED, password='Original-Password-12')
        self.signup(password='Attacker-Password-34')
        existing.refresh_from_db()
        self.assertTrue(existing.check_password('Original-Password-12'))

    def test_honeypot_creates_nothing_but_looks_like_success(self):
        response = self.signup(website='http://spam.example')
        self.assertEqual(response.status_code, 201)
        self.assertFalse(User.objects.resident_pool().filter(email=SHARED).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_a_weak_password_at_verification_is_rejected_without_spending_the_code(self):
        self.signup()
        code = last_code()
        weak = self.client.post(reverse('resident-otp-email-verify'), {'email': SHARED, 'code': code, 'password': 'password'})
        self.assertEqual(weak.status_code, 400)
        self.assertIn('password', weak.data)
        ok = self.client.post(reverse('resident-otp-email-verify'), {'email': SHARED, 'code': code, 'password': STRONG_PASSWORD})
        self.assertEqual(ok.status_code, 200)

    def test_login_is_refused_until_the_email_is_verified(self):
        self.signup(password=STRONG_PASSWORD)  # a password sent at signup is ignored
        response = self.client.post(reverse('resident-login'), {'email': SHARED, 'password': STRONG_PASSWORD})
        self.assertEqual(response.status_code, 401)

    def test_the_emailed_code_verifies_and_signs_in(self):
        self.signup()
        response = self.client.post(
            reverse('resident-otp-email-verify'),
            {'email': SHARED, 'code': last_code(), 'password': STRONG_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)
        self.assertTrue(User.objects.resident_pool().get(email=SHARED).email_verified)
        login = self.client.post(reverse('resident-login'), {'email': SHARED, 'password': STRONG_PASSWORD})
        self.assertEqual(login.status_code, 200)

    def test_an_attackers_signup_cannot_set_the_password_the_owner_ends_up_with(self):
        attacker_password = 'Attacker-Password-34'
        # The attacker signs up with the victim's address first, sending a password of their choice.
        self.signup(password=attacker_password)
        # The real owner then signs up and verifies with their own password.
        self.signup()
        self.client.post(
            reverse('resident-otp-email-verify'),
            {'email': SHARED, 'code': last_code(), 'password': STRONG_PASSWORD},
        )
        user = User.objects.resident_pool().get(email=SHARED)
        self.assertTrue(user.check_password(STRONG_PASSWORD))
        self.assertFalse(user.check_password(attacker_password))
        attacker = self.client.post(reverse('resident-login'), {'email': SHARED, 'password': attacker_password})
        self.assertEqual(attacker.status_code, 401)

    def test_verifying_without_a_password_leaves_password_sign_in_off(self):
        self.signup(password='Attacker-Password-34')
        self.client.post(reverse('resident-otp-email-verify'), {'email': SHARED, 'code': last_code()})
        user = User.objects.resident_pool().get(email=SHARED)
        self.assertTrue(user.email_verified)
        self.assertFalse(user.has_usable_password())

    def test_first_verification_does_not_overwrite_a_password_reset_that_finished_first(self):
        from unittest import mock

        from django.db.models import QuerySet

        self.signup()
        code = last_code()
        original = QuerySet.select_for_update
        done = []

        def reset_before_lock(queryset, *args, **kwargs):
            # A password reset completes after the request started, before it holds the user lock.
            if not done:
                done.append(True)
                reset = User.objects.resident_pool().get(email=SHARED)
                reset.set_password("Reset-Password-5678")
                reset.email_verified = True
                reset.save(update_fields=["password", "email_verified", "updated_at"])
            return original(queryset, *args, **kwargs)

        with mock.patch.object(QuerySet, "select_for_update", reset_before_lock):
            response = self.client.post(
                reverse("resident-otp-email-verify"),
                {"email": SHARED, "code": code, "password": STRONG_PASSWORD},
            )
        self.assertEqual(response.status_code, 200)
        user = User.objects.resident_pool().get(email=SHARED)
        self.assertTrue(user.check_password("Reset-Password-5678"))
        self.assertFalse(user.check_password(STRONG_PASSWORD))

    def test_a_verified_accounts_password_is_not_changed_by_a_sign_in_code(self):
        user = self.create_resident_account(SHARED, password='Original-Password-12')
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('resident-otp-email-request'), {'email': SHARED})
        response = self.client.post(
            reverse('resident-otp-email-verify'),
            {'email': SHARED, 'code': last_code(), 'password': 'Attacker-Password-34'},
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password('Original-Password-12'))

    def test_a_wrong_code_does_not_verify(self):
        self.signup()
        code = last_code()
        wrong = '000000' if code != '000000' else '111111'
        response = self.client.post(reverse('resident-otp-email-verify'), {'email': SHARED, 'code': wrong})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(User.objects.resident_pool().get(email=SHARED).email_verified)

    def test_code_request_answers_the_same_for_unknown_and_known_addresses(self):
        self.create_resident_account(SHARED)
        known = self.client.post(reverse('resident-otp-email-request'), {'email': SHARED})
        unknown = self.client.post(reverse('resident-otp-email-request'), {'email': 'nobody@example.com'})
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.data, unknown.data)


class ResidentPasswordResetTests(ResidentPoolTestCase):
    def request_reset(self, email=SHARED):
        return self.client.post(reverse('resident-password-reset'), {'email': email})

    def confirm(self, code, new_password='Brand-New-Passw0rd', email=SHARED):
        return self.client.post(
            reverse('resident-password-reset-confirm'),
            {'email': email, 'code': code, 'new_password': new_password},
        )

    def test_reset_by_code_changes_the_password_and_ends_old_sessions(self):
        user = self.create_resident_account(SHARED, password='Old-Password-1234')
        old_version = user.auth_version
        self.request_reset()
        response = self.confirm(last_code())
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password('Brand-New-Passw0rd'))
        self.assertGreater(user.auth_version, old_version)
        login = self.client.post(reverse('resident-login'), {'email': SHARED, 'password': 'Brand-New-Passw0rd'})
        self.assertEqual(login.status_code, 200)

    def test_a_weak_new_password_does_not_spend_the_code(self):
        self.create_resident_account(SHARED)
        self.request_reset()
        code = last_code()
        self.assertEqual(self.confirm(code, new_password='123').status_code, 400)
        self.assertEqual(self.confirm(code).status_code, 200)

    def test_a_login_code_cannot_reset_a_password(self):
        user = self.create_resident_account(SHARED)
        from apps.accounts import otp

        code = otp.issue(user, otp.Channel.EMAIL)  # purpose=login
        self.assertEqual(self.confirm(code).status_code, 400)

    def test_a_reset_code_cannot_sign_in(self):
        user = self.create_resident_account(SHARED)
        from apps.accounts import otp

        code = otp.issue(user, otp.Channel.EMAIL, purpose=OtpCode.Purpose.PASSWORD_RESET)
        response = self.client.post(reverse('resident-otp-email-verify'), {'email': SHARED, 'code': code})
        self.assertEqual(response.status_code, 401)

    def test_reset_request_is_silent_for_unknown_addresses(self):
        response = self.request_reset('nobody@example.com')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_marks_an_unverified_email_verified(self):
        user = self.create_resident_account(SHARED, email_verified=False)
        self.request_reset()
        self.assertEqual(self.confirm(last_code()).status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.email_verified)


class LegacyResidentGuardTests(ResidentPoolTestCase):
    """Migration accounts.0013 refuses to reinterpret pre-existing role=resident users."""

    def guard(self):
        module = importlib.import_module('apps.accounts.migrations.0013_resident_account_pool')
        return module.refuse_legacy_resident_users(django_apps, None)

    def test_guard_passes_with_no_resident_users(self):
        self.assertIsNone(self.guard())

    def test_guard_stops_the_release_when_a_resident_user_exists(self):
        self.create_resident_account(SHARED)
        with self.assertRaisesMessage(RuntimeError, 'role="resident"'):
            self.guard()

    def test_check_command_reports_and_fails(self):
        call_command('check_resident_users')  # clean: no error
        self.create_resident_account(SHARED)
        with self.assertRaises(CommandError):
            call_command('check_resident_users', stdout=io.StringIO())
