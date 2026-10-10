import uuid

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models, transaction
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.core.roles import Role, STAFF_ROLES
from .normalization import normalize_email, normalize_phone


class Tenant(models.Model):
    """One customer account. The root of all tenant-scoped data — has no
    tenant_id itself. Status transitions are managed by Module 13; here the
    status only gates API access (suspended/cancelled = login blocked)."""

    class Status(models.TextChoices):
        TRIAL = 'trial', _('Trial')
        ACTIVE = 'active', _('Active')
        PAYMENT_FAILED = 'payment_failed', _('Payment Failed')
        SUSPENDED = 'suspended', _('Suspended')
        CANCELLED = 'cancelled', _('Cancelled')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('business name'), max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)
    default_language = models.CharField(max_length=8, choices=settings.LANGUAGES, default='en')
    # Computed at signup from PlatformConfig.trial_days — never from a constant.
    trial_ends_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenants'

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email=None, password=None, **extra_fields):
        email = normalize_email(email)
        phone = normalize_phone(extra_fields.get('phone'))
        if phone is not None:
            extra_fields['phone'] = phone

        role = extra_fields.get('role')
        if role in (Role.OWNER, Role.SUPER_ADMIN) and not email:
            raise ValueError('Email is required for owner and super admin accounts')
        if role in STAFF_ROLES and not phone:
            raise ValueError('Phone number is required for staff accounts')
        if not email and not phone:
            raise ValueError('At least one of email or phone is required')

        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('role', Role.SUPER_ADMIN)
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('email_verified', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """All platform users. tenant is NULL only for Super Admins (platform staff).

    Not under RLS: authentication (login, OTP, password reset) must look up
    users before any tenant context exists. Views scope user queries at the
    app level instead.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, null=True, blank=True, on_delete=models.CASCADE, related_name='users'
    )
    email = models.EmailField(_('email address'), null=True, blank=True)
    phone = models.CharField(max_length=15, null=True, blank=True)
    auth_version = models.PositiveIntegerField(default=0)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices)
    language_code = models.CharField(max_length=8, choices=settings.LANGUAGES, default='en')
    email_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Django admin access only
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name']

    class Meta:
        db_table = 'users'
        constraints = [
            models.CheckConstraint(
                # Super Admins are platform-level (no tenant); everyone else must belong to one.
                condition=(
                    Q(role=Role.SUPER_ADMIN, tenant__isnull=True)
                    | (~Q(role=Role.SUPER_ADMIN) & Q(tenant__isnull=False))
                ),
                name='user_role_matches_tenant_presence',
            ),
            models.UniqueConstraint(
                Lower('email'),
                condition=Q(is_active=True),
                name='unique_active_email_lower',
            ),
            models.UniqueConstraint(
                fields=['phone'],
                condition=Q(is_active=True),
                name='unique_active_phone',
            ),
            models.CheckConstraint(
                condition=Q(email__isnull=True) | ~Q(email=''),
                name='user_email_not_blank',
            ),
            models.CheckConstraint(
                condition=Q(phone__isnull=True) | ~Q(phone=''),
                name='user_phone_not_blank',
            ),
            models.CheckConstraint(
                condition=~Q(role__in=[Role.OWNER, Role.SUPER_ADMIN]) | Q(email__isnull=False),
                name='user_owner_superadmin_requires_email',
            ),
            models.CheckConstraint(
                condition=Q(email__isnull=False) | Q(phone__isnull=False),
                name='user_requires_email_or_phone',
            ),
            models.CheckConstraint(
                condition=~Q(role__in=[Role.MANAGER, Role.RECEPTIONIST]) | Q(phone__isnull=False),
                name='user_staff_requires_phone',
            ),
        ]

    def set_password(self, raw_password):
        super().set_password(raw_password)
        self._bump_auth_version = True

    def set_unusable_password(self):
        super().set_unusable_password()
        self._bump_auth_version = True

    def save(self, *args, **kwargs):
        self.email = normalize_email(self.email)
        self.phone = normalize_phone(self.phone)
        if getattr(self, '_bump_auth_version', False) and not self._state.adding:
            with transaction.atomic():
                # Atomic DB-level increment — safe under concurrent password
                # changes on the same row without needing select_for_update;
                # a single UPDATE...SET x = x + 1 can't lose an update.
                User.objects.filter(pk=self.pk).update(auth_version=F('auth_version') + 1)
                self.refresh_from_db(fields=['auth_version'])
                self._bump_auth_version = False
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

    def __str__(self):
        return self.email or self.phone or str(self.id)


class OtpCode(models.Model):
    """One-time login codes (PRD Module 1: Mobile OTP). Auth-layer table like
    users — pre-tenant, so not under RLS. Codes are stored hashed."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otp_codes')
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'otp_codes'
