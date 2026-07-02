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

from . import otp as otp_service
from .emails import (
    send_password_reset_email,
    send_staff_invite_email,
    send_verification_email,
)
from .models import Tenant, User
from .tokens import (
    check_password_reset_token,
    read_email_verification_token,
    read_password_reset_uid,
)


def _check_user_can_authenticate(user):
    """Shared login gates for password and OTP flows."""
    if not user.email_verified:
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
    phone = serializers.CharField(max_length=15, required=False, allow_null=True, default=None)
    password = serializers.CharField(write_only=True, validators=[validate_password])
    language_code = serializers.ChoiceField(
        choices=['en', 'hi', 'te', 'ta', 'ml'], required=False, default='en'
    )

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                _('An account with this email already exists.'), code='email_taken'
            )
        return value.lower()

    def validate_phone(self, value):
        if value and User.objects.filter(phone=value).exists():
            raise serializers.ValidationError(
                _('An account with this phone number already exists.'), code='phone_taken'
            )
        return value or None

    @transaction.atomic
    def create(self, validated_data):
        config = PlatformConfig.get()
        tenant = Tenant.objects.create(
            name=validated_data['business_name'],
            default_language=validated_data['language_code'],
            trial_ends_at=timezone.now() + timedelta(days=config.trial_days),
        )
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
        send_verification_email(user)
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
        user = User.objects.filter(email__iexact=self.validated_data['email']).first()
        if user and not user.email_verified:
            send_verification_email(user)


class LoginSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['role'] = user.role
        token['tenant_id'] = str(user.tenant_id) if user.tenant_id else None
        token['language'] = user.language_code
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        _check_user_can_authenticate(self.user)
        return data


class RefreshSerializer(TokenRefreshSerializer):
    """Refresh that re-checks tenant status so suspension forces logout
    within one access-token lifetime (15 min)."""

    def validate(self, attrs):
        data = super().validate(attrs)
        user_id = RefreshToken(attrs['refresh']).get('user_id')
        user = User.objects.select_related('tenant').filter(pk=user_id).first()
        if user is None or not user.is_active:
            raise AuthenticationFailed(
                _('No active account found.'), code='no_active_account'
            )
        if user.tenant_id is not None and user.tenant.status in BLOCKED_TENANT_STATUSES:
            raise AuthenticationFailed(
                _('This account is suspended.'), code='subscription_suspended'
            )
        return data


class OtpRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=15)

    def save(self, **kwargs):
        # Always succeed — never reveal whether a phone is registered.
        user = User.objects.filter(phone=self.validated_data['phone'], is_active=True).first()
        if user:
            otp_service.issue(user)


class OtpVerifySerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=15)
    code = serializers.CharField(max_length=6)

    def validate(self, attrs):
        user = (
            User.objects.select_related('tenant')
            .filter(phone=attrs['phone'], is_active=True)
            .first()
        )
        if user is None or not otp_service.verify(user, attrs['code']):
            raise AuthenticationFailed(
                _('The code is incorrect or has expired.'), code='invalid_otp'
            )
        _check_user_can_authenticate(user)
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
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone', 'language_code']

    def validate_phone(self, value):
        if value and User.objects.exclude(pk=self.instance.pk).filter(phone=value).exists():
            raise serializers.ValidationError(
                _('An account with this phone number already exists.'), code='phone_taken'
            )
        return value or None


class StaffSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'phone', 'role',
            'is_active', 'email_verified', 'created_at',
        ]
        read_only_fields = ['id', 'email', 'is_active', 'email_verified', 'created_at']


class StaffCreateSerializer(serializers.ModelSerializer):
    """Owner creates Manager/Receptionist accounts. The account starts with no
    password; the invite email carries a set-password link. Property assignment
    is Module 02."""

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'phone', 'role']
        read_only_fields = ['id']

    def validate_role(self, value):
        if value not in STAFF_ROLES:
            raise serializers.ValidationError(
                _('Staff accounts must be Manager or Receptionist.'), code='invalid_role'
            )
        return value

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                _('An account with this email already exists.'), code='email_taken'
            )
        return value.lower()

    def validate_phone(self, value):
        if value and User.objects.filter(phone=value).exists():
            raise serializers.ValidationError(
                _('An account with this phone number already exists.'), code='phone_taken'
            )
        return value or None

    @transaction.atomic
    def create(self, validated_data):
        request = self.context['request']
        tenant = request.user.tenant
        user = User.objects.create_user(
            tenant=tenant,
            language_code=tenant.default_language,
            **validated_data,
        )
        audit_log.record(
            action='staff.created',
            actor=request.user,
            obj=user,
            after={'email': user.email, 'role': user.role},
            request=request,
        )
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
        if value and User.objects.exclude(pk=self.instance.pk).filter(phone=value).exists():
            raise serializers.ValidationError(
                _('An account with this phone number already exists.'), code='phone_taken'
            )
        return value or None

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
