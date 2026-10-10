import logging
from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit import log as audit_log
from apps.core.authentication import BLOCKED_TENANT_STATUSES
from apps.core.models import PlatformConfig
from apps.core.roles import Role, STAFF_ROLES, permissions_for
from apps.subscriptions.models import Subscription

from . import otp as otp_service
from .emails import (
    send_password_reset_email,
    send_staff_invite_email,
    send_verification_email,
)
from .models import Tenant, User
from .normalization import normalize_email, normalize_phone
from .tasks import send_welcome_email_task
from .tokens import (
    check_password_reset_token,
    read_email_verification_token,
    read_password_reset_uid,
)

logger = logging.getLogger(__name__)


def _check_user_can_authenticate(user, *, require_verified_email=True):
    """Shared login gates for password and OTP flows."""
    if require_verified_email and user.email and not user.email_verified:
        raise AuthenticationFailed(
            _('Verify your email address to log in.'), code='email_not_verified'
        )
    if user.tenant_id is not None and user.tenant.status in BLOCKED_TENANT_STATUSES:
        raise AuthenticationFailed(
            _('This account is suspended.'), code='subscription_suspended'
        )


class SignupSerializer(serializers.Serializer):
    """Tenant onboarding: creates the Tenant (trial from PlatformConfig) and
    its Owner account, then sends the verification email."""

    business_name = serializers.CharField(max_length=200)
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20, required=False, allow_null=True, default=None)
    password = serializers.CharField(write_only=True, validators=[validate_password])
    language_code = serializers.ChoiceField(
        choices=['en', 'hi', 'te', 'ta', 'ml'], required=False, default='en'
    )

    def validate_email(self, value):
        try:
            normalized = normalize_email(value)
        except ValueError:
            raise serializers.ValidationError(_('Invalid email format.'), code='invalid_email')
        if not normalized:
            raise serializers.ValidationError(_('Email is required.'), code='invalid_email')
        if User.objects.filter(email__iexact=normalized, is_active=True).exists():
            raise serializers.ValidationError(
                _('An account with this email already exists.'), code='email_taken'
            )
        return normalized

    def validate_phone(self, value):
        if not value:
            return None
        try:
            normalized = normalize_phone(value)
        except ValueError:
            raise serializers.ValidationError(_('Invalid phone number.'), code='invalid_phone')
        if normalized and User.objects.filter(phone=normalized, is_active=True).exists():
            raise serializers.ValidationError(
                _('An account with this phone number already exists.'), code='phone_taken'
            )
        return normalized

    @transaction.atomic
    def create(self, validated_data):
        config = PlatformConfig.get()
        tenant = Tenant.objects.create(
            name=validated_data['business_name'],
            default_language=validated_data['language_code'],
            trial_ends_at=timezone.now() + timedelta(days=config.trial_days),
        )
        # Module 13: every tenant gets a blank Subscription (no plan yet —
        # trial limits, if any, come from the Super-Admin-flagged trial plan).
        Subscription.objects.create(tenant=tenant)
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            tenant=tenant,
            role=Role.OWNER,
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            phone=validated_data['phone'],
            language_code=validated_data['language_code'],
        )
        audit_log.record(
            action='tenant.signed_up',
            actor=user,
            obj=tenant,
            after={'name': tenant.name, 'trial_ends_at': tenant.trial_ends_at.isoformat()},
            request=self.context.get('request'),
        )
        # Module 14: dispatched after commit so the Celery worker (which may
        # run before this transaction's row is visible otherwise) always
        # finds the User it's looking for.
        transaction.on_commit(lambda: send_welcome_email_task.delay(str(user.id)))
        return user


class EmailVerificationSerializer(serializers.Serializer):
    token = serializers.CharField()

    def validate(self, attrs):
        user_id = read_email_verification_token(attrs['token'])
        user = User.objects.filter(pk=user_id).first() if user_id else None
        if user is None:
            raise serializers.ValidationError(
                {'token': _('This verification link is invalid or has expired.')},
                code='invalid_token',
            )
        attrs['user'] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data['user']
        if not user.email_verified:
            user.email_verified = True
            user.save(update_fields=['email_verified', 'updated_at'])
        return user


class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def save(self, **kwargs):
        # Always succeed — never reveal whether an email is registered.
        # Targets the active account when duplicate inactive accounts exist.
        user = User.objects.filter(email__iexact=self.validated_data['email'], is_active=True).first()
        if user and not user.email_verified:
            send_verification_email(user)


class LoginSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['role'] = user.role
        token['tenant_id'] = str(user.tenant_id) if user.tenant_id else None
        token['language'] = user.language_code
        token['auth_version'] = user.auth_version
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        _check_user_can_authenticate(self.user, require_verified_email=True)
        return data


class RefreshSerializer(TokenRefreshSerializer):
    """Refresh that re-checks tenant status and auth_version before minting
    a replacement access token."""

    def validate(self, attrs):
        token = RefreshToken(attrs['refresh'])
        user_id = token.get('user_id')
        user = User.objects.select_related('tenant').filter(pk=user_id).first()
        if user is None or not user.is_active:
            raise AuthenticationFailed(
                _('No active account found.'), code='no_active_account'
            )
        if user.tenant_id is not None and user.tenant.status in BLOCKED_TENANT_STATUSES:
            raise AuthenticationFailed(
                _('This account is suspended.'), code='subscription_suspended'
            )
        if token.get('auth_version') != user.auth_version:
            raise AuthenticationFailed(
                _('Password has been changed. Please log in again.'), code='password_changed'
            )
        return super().validate(attrs)


class OtpRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)

    def validate_phone(self, value):
        try:
            normalized = normalize_phone(value)
        except ValueError:
            raise serializers.ValidationError(_('Invalid phone number.'), code='invalid_phone')
        return normalized

    def save(self, **kwargs):
        # Always succeed — never reveal whether a phone is registered.
        user = User.objects.filter(phone=self.validated_data['phone'], is_active=True).first()
        if user:
            otp_service.issue(user)


class OtpVerifySerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    code = serializers.CharField(max_length=6)

    def validate_phone(self, value):
        try:
            normalized = normalize_phone(value)
        except ValueError:
            raise serializers.ValidationError(_('Invalid phone number.'), code='invalid_phone')
        return normalized

    def validate(self, attrs):
        phone = attrs['phone']
        user = (
            User.objects.select_related('tenant')
            .filter(phone=phone, is_active=True)
            .first()
        )
        if user is None or not otp_service.verify(user, attrs['code']):
            raise AuthenticationFailed(
                _('The code is incorrect or has expired.'), code='invalid_otp'
            )
        _check_user_can_authenticate(user, require_verified_email=False)
        refresh = LoginSerializer.get_token(user)
        return {'refresh': str(refresh), 'access': str(refresh.access_token)}


class PhoneLoginSerializer(serializers.Serializer):
    phone = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        raw_phone = attrs.get('phone')
        password = attrs.get('password')
        try:
            phone = normalize_phone(raw_phone)
        except ValueError:
            User().set_password(password or '')
            raise AuthenticationFailed(
                _('Invalid credentials.'),
                code='invalid_credentials',
            )

        if not phone or not password:
            User().set_password(password or '')
            raise AuthenticationFailed(
                _('Invalid credentials.'),
                code='invalid_credentials',
            )

        try:
            user = (
                User.objects.select_related('tenant')
                .get(phone=phone, is_active=True)
            )
        except User.DoesNotExist:
            User().set_password(password)
            raise AuthenticationFailed(
                _('Invalid credentials.'),
                code='invalid_credentials',
            )
        except User.MultipleObjectsReturned:
            logger.error('Multiple active users share phone %r', phone)
            raise AuthenticationFailed(
                _('Invalid credentials.'),
                code='invalid_credentials',
            )

        if not user.check_password(password):
            raise AuthenticationFailed(
                _('Invalid credentials.'),
                code='invalid_credentials',
            )

        _check_user_can_authenticate(user, require_verified_email=False)
        refresh = LoginSerializer.get_token(user)
        return {'refresh': str(refresh), 'access': str(refresh.access_token)}


class TokenPairSerializer(serializers.Serializer):
    """Response shape for token-issuing endpoints (schema documentation only)."""

    access = serializers.CharField()
    refresh = serializers.CharField()


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def save(self, **kwargs):
        # Always succeed — never reveal whether an email is registered.
        user = User.objects.filter(email__iexact=self.validated_data['email'], is_active=True).first()
        if user:
            send_password_reset_email(user)


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(validators=[validate_password])

    def validate(self, attrs):
        user_id = read_password_reset_uid(attrs['uid'])
        user = User.objects.filter(pk=user_id, is_active=True).first() if user_id else None
        if user is None or not check_password_reset_token(user, attrs['token']):
            raise serializers.ValidationError(
                {'token': _('This reset link is invalid or has expired.')},
                code='invalid_token',
            )
        attrs['user'] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data['user']
        user.set_password(self.validated_data['new_password'])
        # Completing the flow proves email ownership (also finishes staff invites).
        user.email_verified = True
        user.save(update_fields=['password', 'email_verified', 'updated_at'])
        return user


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ['id', 'name', 'status', 'default_language', 'trial_ends_at']
        read_only_fields = fields


class TenantUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ['default_language']


class MeSerializer(serializers.ModelSerializer):
    tenant = TenantSerializer(read_only=True)
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'phone', 'role',
            'language_code', 'email_verified', 'tenant', 'permissions',
        ]
        read_only_fields = ['id', 'email', 'role', 'email_verified', 'tenant', 'permissions']

    def get_permissions(self, obj) -> list[str]:
        return permissions_for(obj.role)


class MeUpdateSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(max_length=20, required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone', 'language_code']

    def validate_phone(self, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            if self.instance and self.instance.role in STAFF_ROLES:
                raise serializers.ValidationError(
                    _('Phone number is required for staff accounts.'),
                    code='phone_required',
                )
            if self.instance and not self.instance.email:
                raise serializers.ValidationError(
                    _('Phone number cannot be removed because this account has no email.'),
                    code='identifier_required',
                )
            return None
        try:
            normalized = normalize_phone(value)
        except ValueError:
            raise serializers.ValidationError(_('Invalid phone number.'), code='invalid_phone')
        if normalized and User.objects.exclude(pk=self.instance.pk).filter(phone=normalized, is_active=True).exists():
            raise serializers.ValidationError(
                _('An account with this phone number already exists.'), code='phone_taken'
            )
        return normalized


class StaffSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'phone', 'role',
            'is_active', 'email_verified', 'created_at',
        ]
        read_only_fields = ['id', 'email', 'is_active', 'email_verified', 'created_at']


class StaffCreateSerializer(serializers.ModelSerializer):
    """Owner creates Manager/Receptionist accounts. Staff creation requires a phone
    number and at least one of password or email. If password is provided, the account
    is usable immediately (and a verification-only email is sent if email is also provided).
    If no password is provided, an invite email is sent with a set-password link."""

    email = serializers.EmailField(required=False, allow_null=True)
    phone = serializers.CharField(max_length=20, required=True)
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'phone', 'role', 'password']
        read_only_fields = ['id']

    def validate_role(self, value):
        if value not in STAFF_ROLES:
            raise serializers.ValidationError(
                _('Staff accounts must be Manager or Receptionist.'), code='invalid_role'
            )
        return value

    def validate_email(self, value):
        if not value:
            return None
        try:
            normalized = normalize_email(value)
        except ValueError:
            raise serializers.ValidationError(_('Invalid email format.'), code='invalid_email')
        if not normalized:
            return None
        if User.objects.filter(email__iexact=normalized, is_active=True).exists():
            raise serializers.ValidationError(
                _('An account with this email already exists.'), code='email_taken'
            )
        return normalized

    def validate_phone(self, value):
        if not value:
            raise serializers.ValidationError(
                _('Phone number is required.'), code='invalid_phone'
            )
        try:
            normalized = normalize_phone(value)
        except ValueError:
            raise serializers.ValidationError(
                _('Invalid phone number.'), code='invalid_phone'
            )
        if not normalized:
            raise serializers.ValidationError(
                _('Phone number is required.'), code='invalid_phone'
            )
        if User.objects.filter(phone=normalized, is_active=True).exists():
            raise serializers.ValidationError(
                _('An account with this phone number already exists.'), code='phone_taken'
            )
        return normalized

    def validate(self, attrs):
        phone = attrs.get('phone')
        if not phone:
            raise serializers.ValidationError(
                {'phone': [_('Phone number is required.')]}, code='invalid_phone'
            )

        password = attrs.get('password')
        email = attrs.get('email')
        if not password and not email:
            raise serializers.ValidationError(
                _('At least one of password or email must be provided.'),
                code='identifier_required',
            )

        if password:
            user_instance = User(
                email=email,
                first_name=attrs.get('first_name', ''),
                last_name=attrs.get('last_name', ''),
            )
            try:
                validate_password(password, user=user_instance)
            except Exception as exc:
                raise serializers.ValidationError({'password': list(exc.messages)})

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context['request']
        tenant = request.user.tenant
        password = validated_data.pop('password', None)
        email = validated_data.get('email')

        user = User.objects.create_user(
            tenant=tenant,
            language_code=tenant.default_language,
            password=password,
            **validated_data,
        )
        audit_log.record(
            action='staff.created',
            actor=request.user,
            obj=user,
            after={'email': user.email, 'phone': user.phone, 'role': user.role},
            request=request,
        )
        if password:
            if email:
                send_verification_email(user)
        else:
            send_staff_invite_email(user, tenant)
        return user


class StaffUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone', 'role', 'is_active']

    def validate_role(self, value):
        if value not in STAFF_ROLES:
            raise serializers.ValidationError(
                _('Staff accounts must be Manager or Receptionist.'), code='invalid_role'
            )
        return value

    def validate_phone(self, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            raise serializers.ValidationError(
                _('Phone number is required for staff.'), code='invalid_phone'
            )
        try:
            normalized = normalize_phone(value)
        except ValueError:
            raise serializers.ValidationError(
                _('Invalid phone number.'), code='invalid_phone'
            )
        if not normalized:
            raise serializers.ValidationError(
                _('Phone number is required for staff.'), code='invalid_phone'
            )
        if User.objects.exclude(pk=self.instance.pk).filter(phone=normalized, is_active=True).exists():
            raise serializers.ValidationError(
                _('An account with this phone number already exists.'), code='phone_taken'
            )
        return normalized

    def validate(self, attrs):
        # Reactivation safety check: when is_active flips False -> True
        if attrs.get('is_active') is True and self.instance and not self.instance.is_active:
            email_to_check = normalize_email(self.instance.email)
            if email_to_check and User.objects.exclude(pk=self.instance.pk).filter(email__iexact=email_to_check, is_active=True).exists():
                raise serializers.ValidationError(
                    {'email': [_('An account with this email already exists.')]},
                    code='email_taken',
                )
            phone_to_check = (
                attrs.get('phone')
                if 'phone' in attrs
                else normalize_phone(self.instance.phone)
            )
            if phone_to_check and User.objects.exclude(pk=self.instance.pk).filter(phone=phone_to_check, is_active=True).exists():
                raise serializers.ValidationError(
                    {'phone': [_('An account with this phone number already exists.')]},
                    code='phone_taken',
                )
        return attrs

    def update(self, instance, validated_data):
        request = self.context['request']
        before = {'role': instance.role, 'is_active': instance.is_active}
        instance = super().update(instance, validated_data)
        after = {'role': instance.role, 'is_active': instance.is_active}
        if before != after:
            audit_log.record(
                action='staff.updated',
                actor=request.user,
                obj=instance,
                before=before,
                after=after,
                request=request,
            )
        return instance
