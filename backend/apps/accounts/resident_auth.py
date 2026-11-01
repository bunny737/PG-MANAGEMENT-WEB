"""Resident app account authentication (Module 26): signup, login, email-code sign-in and
password reset for the RESIDENT pool.

A resident account is a person's own login. It is never created by staff, belongs to no tenant,
and is tied to PGs only through ResidentAccess. Its email/phone live in their own uniqueness pool
(see UserQuerySet), so the same address can also hold a staff account; these endpoints therefore
look accounts up through `User.objects.resident_pool()` and authenticate through
ResidentEmailBackend, which is deliberately not in AUTHENTICATION_BACKENDS.

Verification and password reset use emailed 6-digit codes, not links: the app has no page to open
a link in, and a code works the same on the web. Responses never reveal whether an address has an
account.
"""
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import log as audit_log
from apps.core.roles import Role
from apps.core.tasks import enqueue
from apps.core.throttles import ScopedRateThrottle

from . import otp as otp_service
from .backends import ResidentEmailBackend
from .models import OtpCode, User
from .normalization import normalize_email
from .serializers import LoginSerializer, TokenPairSerializer, _check_user_can_authenticate
from .tasks import (
    send_password_changed_task,
    send_resident_login_code_task,
    send_resident_password_reset_task,
    send_resident_signup_task,
)
from .throttles import ResidentOtpEmailThrottle, ResidentPasswordResetEmailThrottle


def _tokens_for(user):
    refresh = LoginSerializer.get_token(user)
    return {'refresh': str(refresh), 'access': str(refresh.access_token)}


class _EmailField(serializers.EmailField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        try:
            normalized = normalize_email(value)
        except ValueError:
            raise serializers.ValidationError(_('Invalid email format.'), code='invalid_email')
        if not normalized:
            raise serializers.ValidationError(_('Email is required.'), code='invalid_email')
        return normalized


class ResidentSignupSerializer(serializers.Serializer):
    """Create the person's own app account. The response is the same whether or not the address
    already has an account (no enumeration): a new account gets a verification code by email, an
    existing verified one gets a "you already have an account" email.

    No password is accepted or stored here. Anyone can sign up with anyone's address, so a password
    chosen now could later be activated by the real owner's verification. The password is chosen
    in the verification step, by the person who holds the emailed code."""

    email = _EmailField()
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    language_code = serializers.ChoiceField(
        choices=['en', 'hi', 'te', 'ta', 'ml'], required=False, default='en',
    )
    # Honeypot: a person never sees this field. A bot that fills it gets the same success answer
    # and nothing is created.
    website = serializers.CharField(required=False, allow_blank=True, write_only=True)

    def save(self, **kwargs):
        data = self.validated_data
        if data.get('website'):
            return None
        email = data['email']
        exists = User.objects.resident_pool().filter(email__iexact=email, is_active=True).exists()
        if not exists:
            try:
                with transaction.atomic():
                    User.objects.create_user(
                        email=email, password=None, tenant=None, role=Role.RESIDENT,
                        first_name=data['first_name'], last_name=data['last_name'],
                        language_code=data['language_code'],
                    )
            except IntegrityError:
                pass  # a concurrent signup for the same address won; both get the same email
        transaction.on_commit(lambda: enqueue(send_resident_signup_task, email))
        return None


class ResidentLoginSerializer(serializers.Serializer):
    email = _EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = ResidentEmailBackend().authenticate(None, username=attrs['email'], password=attrs['password'])
        if user is None:
            raise AuthenticationFailed(_('No active account found with the given credentials.'), code='no_active_account')
        # Password login proves the password, not the inbox: an unverified address must verify first.
        _check_user_can_authenticate(user, require_verified_email=True)
        return _tokens_for(user)


class ResidentEmailCodeRequestSerializer(serializers.Serializer):
    email = _EmailField()

    def save(self, **kwargs):
        # Same work for every address: queue the task, which decides eligibility on the worker.
        enqueue(send_resident_login_code_task, self.validated_data['email'])


class ResidentEmailCodeVerifySerializer(serializers.Serializer):
    email = _EmailField()
    # Malformed codes are a 400 before any lookup, so they never use up one of the code's attempts.
    code = serializers.RegexField(r'^\d{6}$')
    # The password for password sign-in, chosen by the person holding the code. It only takes effect
    # when this code is what first verifies the address (a signup); a verified account's password is
    # never changed here. Strength is checked before the code is spent.
    password = serializers.CharField(write_only=True, required=False, validators=[validate_password])

    def validate(self, attrs):
        user = User.objects.resident_pool().filter(email__iexact=attrs['email'], is_active=True).first()
        was_unverified = user is not None and not user.email_verified
        # No outer transaction: verify() commits the failed-attempt counter even though this raises.
        if user is None or not otp_service.verify(user, attrs['code'], otp_service.Channel.EMAIL):
            raise AuthenticationFailed(_('The code is incorrect or has expired.'), code='invalid_otp')
        # A correct code proved inbox ownership (verify() marked the email verified).
        _check_user_can_authenticate(user, require_verified_email=False)
        if was_unverified:
            self._establish_password(user, attrs.get('password'))
        return _tokens_for(user)

    def _establish_password(self, user, password):
        """First verification of an address: whatever password the account held is discarded and
        only the one supplied now (by the verified owner) can sign in. Without one, password
        sign-in stays off until the person sets it through a password reset."""
        with transaction.atomic():
            locked = User.objects.resident_pool().select_for_update().get(pk=user.pk)
            if password:
                locked.set_password(password)
            else:
                locked.set_unusable_password()
            locked.save(update_fields=['password', 'updated_at'])
            audit_log.record(
                action='resident_account.password_established', actor=None, tenant_id=None, obj=locked,
                before={}, after={'password_set': bool(password)},
                request=self.context.get('request'),
            )
        user.password = locked.password
        user.auth_version = locked.auth_version


class ResidentPasswordResetRequestSerializer(serializers.Serializer):
    email = _EmailField()

    def save(self, **kwargs):
        enqueue(send_resident_password_reset_task, self.validated_data['email'])


class ResidentPasswordResetConfirmSerializer(serializers.Serializer):
    email = _EmailField()
    code = serializers.RegexField(r'^\d{6}$')
    # Strength is checked as a field validator, i.e. BEFORE the code is spent.
    new_password = serializers.CharField(write_only=True, validators=[validate_password])

    def validate(self, attrs):
        user = User.objects.resident_pool().filter(email__iexact=attrs['email'], is_active=True).first()
        if user is None or not otp_service.verify(
            user, attrs['code'], otp_service.Channel.EMAIL, purpose=OtpCode.Purpose.PASSWORD_RESET,
        ):
            raise serializers.ValidationError({'code': [_('The code is incorrect or has expired.')]}, code='invalid_otp')
        attrs['user'] = user
        return attrs

    def save(self, **kwargs):
        with transaction.atomic():
            user = User.objects.resident_pool().select_for_update().get(pk=self.validated_data['user'].pk)
            version_before = user.auth_version
            user.set_password(self.validated_data['new_password'])
            # The code proved email ownership (verify() already marked it).
            user.email_verified = True
            user.save(update_fields=['password', 'email_verified', 'updated_at'])
            audit_log.record(
                action='resident_account.password_reset', actor=None, tenant_id=None, obj=user,
                before={'auth_version': version_before}, after={'auth_version': user.auth_version},
                request=self.context.get('request'),
            )
            user_id, expected_email = str(user.id), user.email
            transaction.on_commit(lambda: enqueue(send_password_changed_task, user_id, expected_email))
        return user


class _AnonView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    serializer_class = None
    success_message = _('OK')
    success_status = status.HTTP_200_OK

    def get_authenticate_header(self, request):
        # Failed sign-ins answer 401 rather than DRF's 403 fallback.
        return 'Bearer realm="api"'

    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'detail': self.success_message}, status=self.success_status)


class _TokenView(_AnonView):
    @extend_schema(responses=TokenPairSerializer)
    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data)


class ResidentSignupView(_AnonView):
    serializer_class = ResidentSignupSerializer
    throttle_scope = 'resident_signup'
    success_status = status.HTTP_201_CREATED
    success_message = _('Check your email for a verification code.')


class ResidentLoginView(_TokenView):
    serializer_class = ResidentLoginSerializer
    throttle_scope = 'resident_login'


class ResidentEmailCodeRequestView(_AnonView):
    serializer_class = ResidentEmailCodeRequestSerializer
    throttle_classes = [ScopedRateThrottle, ResidentOtpEmailThrottle]
    throttle_scope = 'resident_otp_request'
    success_message = _('If that email has an account, a code has been sent.')


class ResidentEmailCodeVerifyView(_TokenView):
    serializer_class = ResidentEmailCodeVerifySerializer
    throttle_scope = 'resident_otp_verify'


class ResidentPasswordResetRequestView(_AnonView):
    serializer_class = ResidentPasswordResetRequestSerializer
    throttle_classes = [ScopedRateThrottle, ResidentPasswordResetEmailThrottle]
    throttle_scope = 'resident_password_reset_request'
    success_message = _('If that email has an account, a reset code has been sent.')


class ResidentPasswordResetConfirmView(_AnonView):
    serializer_class = ResidentPasswordResetConfirmSerializer
    throttle_scope = 'resident_password_reset_confirm'
    success_message = _('Password updated. You can sign in now.')
