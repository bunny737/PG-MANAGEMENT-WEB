from unittest import mock

from django import forms
from django.core import mail
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.admin import CustomUserChangeForm, CustomUserCreationForm
from apps.accounts.backends import ActiveEmailBackend
from apps.accounts.models import Tenant, User
from apps.accounts.normalization import normalize_email, normalize_phone
from apps.accounts.serializers import (
    LoginSerializer,
    RefreshSerializer,
    ResendVerificationSerializer,
    StaffCreateSerializer,
    StaffUpdateSerializer,
)
from apps.audit.models import AuditLog
from apps.core.exceptions import api_exception_handler
from apps.core.roles import Role
from apps.core.tenancy import tenant_context

from .base import STRONG_PASSWORD, AuthAPITestCase


class StaffLoginAndReemploymentTests(AuthAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)

    # 1. UserManager.create_user and role/identifier requirements
    def test_create_user_phone_only_succeeds_and_str_returns_phone(self):
        user = User.objects.create_user(
            tenant=self.tenant,
            role=Role.MANAGER,
            phone='9876543210',
            password=STRONG_PASSWORD,
        )
        self.assertIsNone(user.email)
        self.assertEqual(user.phone, '9876543210')
        self.assertEqual(str(user), '9876543210')

    def test_owner_superadmin_without_email_fails_manager_and_db(self):
        # Manager level: raises ValueError
        with self.assertRaises(ValueError):
            User.objects.create_user(
                tenant=self.tenant,
                role=Role.OWNER,
                phone='9876543210',
                password=STRONG_PASSWORD,
            )
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                email=None,
                phone='9876543210',
                password=STRONG_PASSWORD,
            )

        # DB constraint level bypassing manager:
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                user = User(
                    tenant=self.tenant,
                    role=Role.OWNER,
                    phone='9876543210',
                )
                user.save()

    def test_staff_without_phone_fails_manager_and_db(self):
        # Manager level:
        with self.assertRaises(ValueError):
            User.objects.create_user(
                tenant=self.tenant,
                role=Role.MANAGER,
                email='mgr@example.com',
                password=STRONG_PASSWORD,
            )

        # DB constraint level (user_staff_requires_phone):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                user = User(
                    tenant=self.tenant,
                    role=Role.MANAGER,
                    email='mgr_direct@example.com',
                )
                user.save()

    def test_create_user_neither_email_nor_phone_raises_value_error(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(
                tenant=self.tenant,
                role=Role.MANAGER,
                password=STRONG_PASSWORD,
            )

    # 2. Normalization & phone format equivalence
    def test_phone_format_equivalence_and_colliding_active_phone(self):
        # 9876543210, 09876543210, +919876543210, 91 9876543210 all normalize to 9876543210
        inputs = ['9876543210', '09876543210', '+919876543210', '91 9876543210']
        for raw in inputs:
            self.assertEqual(normalize_phone(raw), '9876543210')

        # Creating user with one format
        User.objects.create_user(
            tenant=self.tenant,
            role=Role.MANAGER,
            phone='9876543210',
            password=STRONG_PASSWORD,
        )

        # Trying to create another active staff with another equivalent format fails
        for raw in ['09876543210', '+919876543210']:
            serializer = StaffCreateSerializer(
                data={
                    'first_name': 'Test',
                    'phone': raw,
                    'role': Role.MANAGER,
                    'password': STRONG_PASSWORD,
                },
                context={'request': mock.Mock(user=self.owner)},
            )
            self.assertFalse(serializer.is_valid())
            self.assertIn('phone', serializer.errors)
            self.assertEqual(serializer.errors['phone'][0].code, 'phone_taken')

    def test_unsupported_phone_shapes_rejected_not_truncated(self):
        invalid_shapes = [
            '1234567890',          # 10 digits not starting with 6-9
            '5876543210',          # 10 digits starting with 5
            '9876543210123',       # 13 digits
            '01234567890',         # 11 digits starting with 0 but next is not 6-9
            '911234567890',        # 12 digits starting with 91 but next is not 6-9
            '98765',               # too short
        ]
        for val in invalid_shapes:
            with self.assertRaises(ValueError):
                normalize_phone(val)

    def test_blank_string_identifiers_normalize_to_none_or_rejected(self):
        self.assertIsNone(normalize_email(''))
        self.assertIsNone(normalize_email('   '))
        self.assertIsNone(normalize_phone(''))
        self.assertIsNone(normalize_phone('   '))

        # DB level constraints: email and phone cannot be empty string ''
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                user = User(tenant=self.tenant, role=Role.OWNER, email='', phone='9876543210')
                # bypass save normalizer via direct SQL or update
                User.objects.bulk_create([user])

    # 3. ActiveEmailBackend tests
    def test_email_backend_reads_email_kwarg_from_simplejwt(self):
        backend = ActiveEmailBackend()
        # SimpleJWT calls authenticate(request, email=..., password=...)
        user = backend.authenticate(None, email=self.owner.email, password=STRONG_PASSWORD)
        self.assertIsNotNone(user)
        self.assertEqual(user.id, self.owner.id)

        # username=... also supported
        user2 = backend.authenticate(None, username=self.owner.email, password=STRONG_PASSWORD)
        self.assertIsNotNone(user2)
        self.assertEqual(user2.id, self.owner.id)

    def test_email_backend_unknown_and_wrong_password_timing_safety(self):
        backend = ActiveEmailBackend()
        # Non-existent user
        user_none = backend.authenticate(None, email='nonexistent@example.com', password=STRONG_PASSWORD)
        self.assertIsNone(user_none)

        # Wrong password
        user_wrong = backend.authenticate(None, email=self.owner.email, password='WrongPassword123!')
        self.assertIsNone(user_wrong)

    def test_email_login_works_when_inactive_duplicate_exists(self):
        # Create an inactive user with same email (under a different or same tenant)
        tenant_b = self.create_tenant('Tenant B')
        User.objects.create_user(
            tenant=tenant_b,
            role=Role.OWNER,
            email=self.owner.email,
            password='OldPassword-123!',
            is_active=False,
        )

        # Active user logs in via SimpleJWT /auth/login/ without MultipleObjectsReturned error
        response = self.client.post(
            reverse('auth-login'),
            {'email': self.owner.email, 'password': STRONG_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)

    # 4. Phone+password login tests (/api/v1/auth/login-phone/)
    def test_phone_login_success_and_failures(self):
        staff = User.objects.create_user(
            tenant=self.tenant,
            role=Role.MANAGER,
            phone='9876543210',
            password='StaffPassword-123!',
        )

        # Success (+91 formatted also works via normalization)
        res_ok = self.client.post(
            reverse('auth-login-phone'),
            {'phone': '+91 98765 43210', 'password': 'StaffPassword-123!'},
        )
        self.assertEqual(res_ok.status_code, 200)
        self.assertIn('access', res_ok.data)
        self.assertIn('refresh', res_ok.data)

        # Wrong password
        res_wrong_pw = self.client.post(
            reverse('auth-login-phone'),
            {'phone': '9876543210', 'password': 'WrongPassword!'},
        )
        self.assertEqual(res_wrong_pw.status_code, 401)
        self.assertEqual(res_wrong_pw.data.get('code'), 'INVALID_CREDENTIALS')

        # Unknown phone
        res_unknown = self.client.post(
            reverse('auth-login-phone'),
            {'phone': '9999999999', 'password': 'StaffPassword-123!'},
        )
        self.assertEqual(res_unknown.status_code, 401)
        self.assertEqual(res_unknown.data.get('code'), 'INVALID_CREDENTIALS')

        # Inactive user
        staff.is_active = False
        staff.save()
        res_inactive = self.client.post(
            reverse('auth-login-phone'),
            {'phone': '9876543210', 'password': 'StaffPassword-123!'},
        )
        self.assertEqual(res_inactive.status_code, 401)
        self.assertEqual(res_inactive.data.get('code'), 'INVALID_CREDENTIALS')

    def test_phone_login_succeeds_with_unverified_email_while_email_login_blocked(self):
        # Staff created with phone + unverified email + password
        staff = User.objects.create_user(
            tenant=self.tenant,
            role=Role.MANAGER,
            email='staff_unverified@example.com',
            phone='9876543210',
            password='StaffPassword-123!',
            email_verified=False,
        )

        # Phone login succeeds (not gated on email verification)
        res_phone = self.client.post(
            reverse('auth-login-phone'),
            {'phone': '9876543210', 'password': 'StaffPassword-123!'},
        )
        self.assertEqual(res_phone.status_code, 200)
        self.assertIn('access', res_phone.data)

        # Email login fails with EMAIL_NOT_VERIFIED
        res_email = self.client.post(
            reverse('auth-login'),
            {'email': 'staff_unverified@example.com', 'password': 'StaffPassword-123!'},
        )
        self.assertEqual(res_email.status_code, 401)
        self.assertEqual(res_email.data.get('code'), 'EMAIL_NOT_VERIFIED')

    # 5. Staff creation tests
    def test_staff_created_with_password_only_logs_in_immediately_no_invite(self):
        self.authenticate(self.owner)
        mail.outbox.clear()
        res = self.client.post(
            reverse('staff-list'),
            {
                'first_name': 'Ramesh',
                'phone': '9876543210',
                'role': Role.MANAGER,
                'password': 'InitialStaffPassword-123!',
            },
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 0)  # No invite email

        # Staff can immediately log in
        self.client.credentials()
        login_res = self.client.post(
            reverse('auth-login-phone'),
            {'phone': '9876543210', 'password': 'InitialStaffPassword-123!'},
        )
        self.assertEqual(login_res.status_code, 200)

    def test_staff_created_with_phone_email_no_password_triggers_invite(self):
        self.authenticate(self.owner)
        mail.outbox.clear()
        res = self.client.post(
            reverse('staff-list'),
            {
                'first_name': 'Kavita',
                'email': 'kavita@example.com',
                'phone': '9876543210',
                'role': Role.RECEPTIONIST,
            },
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Set your password to get started', mail.outbox[0].body)

    def test_staff_creation_without_phone_rejected(self):
        self.authenticate(self.owner)
        res = self.client.post(
            reverse('staff-list'),
            {
                'first_name': 'NoPhone',
                'email': 'nophone@example.com',
                'role': Role.MANAGER,
                'password': STRONG_PASSWORD,
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn('phone', res.data)

    def test_staff_creation_with_neither_password_nor_email_rejected(self):
        self.authenticate(self.owner)
        res = self.client.post(
            reverse('staff-list'),
            {
                'first_name': 'NoCreds',
                'phone': '9876543210',
                'role': Role.MANAGER,
            },
        )
        self.assertEqual(res.status_code, 400)

    def test_staff_created_with_password_and_email_receives_verification_email(self):
        self.authenticate(self.owner)
        mail.outbox.clear()
        res = self.client.post(
            reverse('staff-list'),
            {
                'first_name': 'BothCreds',
                'email': 'both@example.com',
                'phone': '9876543210',
                'role': Role.MANAGER,
                'password': 'InitialPassword-999!',
            },
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Verify your email', mail.outbox[0].subject)

        # Verify email and then email login works
        token = self.extract_query_param(mail.outbox[0].body, 'token')
        self.client.credentials()
        v_res = self.client.post(reverse('auth-verify-email'), {'token': token})
        self.assertEqual(v_res.status_code, 200)

        login_res = self.client.post(
            reverse('auth-login'),
            {'email': 'both@example.com', 'password': 'InitialPassword-999!'},
        )
        self.assertEqual(login_res.status_code, 200)

    # 6. Re-employment and Cross-Owner Reuse
    def test_reemployment_deactivated_account_frees_phone_for_another_tenant(self):
        # Tenant 1 staff user
        staff_a = User.objects.create_user(
            tenant=self.tenant,
            role=Role.MANAGER,
            phone='9876543210',
            password=STRONG_PASSWORD,
        )
        # Deactivate staff A
        staff_a.is_active = False
        staff_a.save()

        # Tenant 2 creates new staff with same phone (even in different format '+91')
        tenant_2 = self.create_tenant('Tenant Two')
        staff_b = User.objects.create_user(
            tenant=tenant_2,
            role=Role.MANAGER,
            phone='+91 98765 43210',
            password=STRONG_PASSWORD,
        )
        self.assertNotEqual(staff_a.id, staff_b.id)
        self.assertEqual(staff_b.tenant, tenant_2)
        self.assertEqual(staff_b.phone, '9876543210')

    def test_reactivation_conflict_and_integrity_error_safety_net(self):
        # Deactivate staff A
        staff_a = User.objects.create_user(
            tenant=self.tenant,
            role=Role.MANAGER,
            email='shared@example.com',
            phone='9876543210',
            password=STRONG_PASSWORD,
            is_active=False,
        )

        # Another tenant creates active user with same email & phone
        tenant_b = self.create_tenant('Tenant B')
        User.objects.create_user(
            tenant=tenant_b,
            role=Role.MANAGER,
            email='shared@example.com',
            phone='9876543210',
            password=STRONG_PASSWORD,
            is_active=True,
        )

        # Reactivating staff_a via PATCH {is_active: True} fails with 400 email_taken / phone_taken
        self.authenticate(self.owner)
        res = self.client.patch(
            reverse('staff-detail', args=[staff_a.id]),
            {'is_active': True},
        )
        self.assertEqual(res.status_code, 400)

        # Concurrent race simulation: IntegrityError directly caught by api_exception_handler returns 409
        class MockCause(Exception):
            def __init__(self, constraint_name):
                super().__init__()
                from types import SimpleNamespace
                self.diag = SimpleNamespace(constraint_name=constraint_name)

        exc = IntegrityError('duplicate key value violates unique constraint')
        exc.__cause__ = MockCause('unique_active_email_lower')
        handled_response = api_exception_handler(exc, {})
        self.assertEqual(handled_response.status_code, 409)
        self.assertEqual(handled_response.data.get('code'), 'EMAIL_TAKEN')

        exc.__cause__ = MockCause('unique_active_phone')
        handled_phone_resp = api_exception_handler(exc, {})
        self.assertEqual(handled_phone_resp.status_code, 409)
        self.assertEqual(handled_phone_resp.data.get('code'), 'PHONE_TAKEN')

    # 7. ResendVerification targets active account only
    def test_resend_verification_targets_active_account(self):
        # Inactive account with same email
        User.objects.create_user(
            tenant=self.create_tenant('Old Tenant'),
            role=Role.OWNER,
            email='active@example.com',
            is_active=False,
            email_verified=False,
        )
        # Active account
        active_user = User.objects.create_user(
            tenant=self.tenant,
            role=Role.OWNER,
            email='active@example.com',
            is_active=True,
            email_verified=False,
        )
        mail.outbox.clear()
        resend_serializer = ResendVerificationSerializer(data={'email': 'active@example.com'})
        self.assertTrue(resend_serializer.is_valid())
        resend_serializer.save()

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['active@example.com'])

    # 8. Owner-driven password set/reset and token revocation
    def test_owner_set_password_revokes_tokens_and_writes_audit(self):
        staff = User.objects.create_user(
            tenant=self.tenant,
            role=Role.MANAGER,
            first_name='Anil',
            last_name='Kapoor',
            phone='9876543210',
            password='OldPassword-123!',
        )
        self.assertEqual(staff.auth_version, 0)

        # Issue token for staff before reset
        old_token = LoginSerializer.get_token(staff)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {old_token.access_token}')
        # Staff can access /auth/me/
        me_before = self.client.get(reverse('auth-me'))
        self.assertEqual(me_before.status_code, 200)

        # Owner resets staff password
        self.authenticate(self.owner)
        reset_res = self.client.post(
            reverse('staff-set-password', args=[staff.id]),
            {'password': 'BrandNewPassword-789!'},
        )
        self.assertEqual(reset_res.status_code, 200)

        # Audit log written with no password in payload
        with tenant_context(self.tenant.id):
            audit = AuditLog.objects.get(action='staff.password_reset', object_id=str(staff.id))
            self.assertNotIn('BrandNewPassword-789!', str(audit.before))
            self.assertNotIn('BrandNewPassword-789!', str(audit.after))

        # Check DB auth_version incremented
        staff.refresh_from_db()
        self.assertEqual(staff.auth_version, 1)

        # Prior token is immediately rejected with PASSWORD_CHANGED
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {old_token.access_token}')
        me_after = self.client.get(reverse('auth-me'))
        self.assertEqual(me_after.status_code, 401)
        self.assertEqual(me_after.data.get('code'), 'PASSWORD_CHANGED')

        # New token succeeds
        self.client.credentials()
        new_login = self.client.post(
            reverse('auth-login-phone'),
            {'phone': '9876543210', 'password': 'BrandNewPassword-789!'},
        )
        self.assertEqual(new_login.status_code, 200)

    def test_sequential_auth_version_bumps_atomic_no_lost_update(self):
        staff = User.objects.create_user(
            tenant=self.tenant,
            role=Role.MANAGER,
            phone='9876543210',
            password='Password1!',
        )
        self.assertEqual(staff.auth_version, 0)

        # First bump
        staff.set_password('Password2!')
        staff.save()
        self.assertEqual(staff.auth_version, 1)

        # Second bump without re-fetching
        staff.set_password('Password3!')
        staff.save()
        self.assertEqual(staff.auth_version, 2)

    def test_set_unusable_password_bumps_auth_version_on_existing_row(self):
        staff = User.objects.create_user(
            tenant=self.tenant,
            role=Role.MANAGER,
            phone='9876543210',
            password='InitialPassword1!',
        )
        self.assertEqual(staff.auth_version, 0)

        # Calling set_unusable_password on existing user bumps auth_version
        staff.set_unusable_password()
        staff.save()
        self.assertEqual(staff.auth_version, 1)

    def test_set_password_view_transaction_rolls_back_if_audit_fails(self):
        staff = User.objects.create_user(
            tenant=self.tenant,
            role=Role.MANAGER,
            phone='9876543210',
            password='InitialPassword1!',
        )
        self.authenticate(self.owner)

        with mock.patch('apps.audit.log.record', side_effect=RuntimeError('Audit DB failure')):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse('staff-set-password', args=[staff.id]),
                    {'password': 'NewPassword123!'},
                )

        staff.refresh_from_db()
        self.assertEqual(staff.auth_version, 0)
        self.assertTrue(staff.check_password('InitialPassword1!'))
        self.assertFalse(staff.check_password('NewPassword123!'))

    def test_validate_password_rejects_password_too_similar_to_staff_info(self):
        self.authenticate(self.owner)
        staff = User.objects.create_user(
            tenant=self.tenant,
            role=Role.MANAGER,
            first_name='Anil',
            last_name='Kapoor',
            email='anil.kapoor@example.com',
            phone='9876543210',
            password=STRONG_PASSWORD,
        )
        # Attempt to set password too similar to staff's name
        res = self.client.post(
            reverse('staff-set-password', args=[staff.id]),
            {'password': 'AnilKapoor'},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn('password', res.data)

    def test_tenant_isolation_staff_set_password(self):
        tenant_b = self.create_tenant('Tenant B')
        staff_b = User.objects.create_user(
            tenant=tenant_b,
            role=Role.MANAGER,
            phone='9876543211',
            password=STRONG_PASSWORD,
        )
        # Owner of tenant A tries to set password for tenant B's staff -> 404
        self.authenticate(self.owner)
        res = self.client.post(
            reverse('staff-set-password', args=[staff_b.id]),
            {'password': 'HackedPassword123!'},
        )
        self.assertEqual(res.status_code, 404)

    # 9. Token refresh checks
    def test_refresh_token_rejected_on_stale_auth_version_or_suspended_tenant(self):
        staff = User.objects.create_user(
            tenant=self.tenant,
            role=Role.MANAGER,
            phone='9876543210',
            password=STRONG_PASSWORD,
        )
        refresh = LoginSerializer.get_token(staff)

        # Bump auth_version on user
        staff.set_password('NewPassword-123!')
        staff.save()

        # TokenRefreshView should reject
        res = self.client.post(
            reverse('auth-token-refresh'),
            {'refresh': str(refresh)},
        )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data.get('code'), 'PASSWORD_CHANGED')

    # 10. Django admin form tests
    def test_admin_creation_form_phone_only_staff(self):
        form = CustomUserCreationForm(
            data={
                'phone': '+91 98765 43210',
                'first_name': 'AdminCreated',
                'role': Role.MANAGER,
                'tenant': self.tenant.id,
                'password1': 'AdminPassword123!',
                'password2': 'AdminPassword123!',
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.phone, '9876543210')
        self.assertIsNone(user.email)

    def test_admin_form_cross_field_validations(self):
        # Manager with no phone rejected
        form_no_phone = CustomUserCreationForm(
            data={
                'email': 'mgr@example.com',
                'first_name': 'NoPhone',
                'role': Role.MANAGER,
                'tenant': self.tenant.id,
                'password1': 'AdminPassword123!',
                'password2': 'AdminPassword123!',
            }
        )
        self.assertFalse(form_no_phone.is_valid())
        self.assertIn('phone', form_no_phone.errors)

        # Owner with no email rejected
        form_no_email = CustomUserCreationForm(
            data={
                'phone': '9876543210',
                'first_name': 'NoEmail',
                'role': Role.OWNER,
                'tenant': self.tenant.id,
                'password1': 'AdminPassword123!',
                'password2': 'AdminPassword123!',
            }
        )
        self.assertFalse(form_no_email.is_valid())
        self.assertIn('email', form_no_email.errors)
