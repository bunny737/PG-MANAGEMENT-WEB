import uuid

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils import timezone
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
        # Module 22: set only by the account-deletion purge, in its last phase,
        # once every login of the tenant is gone. The row stays as the tax tombstone.
        DELETED = 'deleted', _('Deleted')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('business name'), max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)
    default_language = models.CharField(max_length=8, choices=settings.LANGUAGES, default='en')
    # First month of the reporting year for YTD analytics (D0): 4 = the Indian
    # financial year (April–March), 1 = calendar year. A tenant preference,
    # not a plan limit.
    fiscal_year_start_month = models.PositiveSmallIntegerField(
        default=4, validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
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
    # Owner-configured module access for staff roles (apps/core/modules.py).
    # NULL = role defaults. Shape: {"base_role": <role>, "levels": {module: level}}.
    module_access = models.JSONField(null=True, blank=True)
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
            # Module 22: whole-tenant deletion is the Owner's decision, so there must be
            # exactly one person who can take it.
            models.UniqueConstraint(
                fields=['tenant'],
                condition=Q(role=Role.OWNER, is_active=True),
                name='unique_active_owner_per_tenant',
            ),
        ]

    def set_password(self, raw_password):
        super().set_password(raw_password)
        self._bump_auth_version = True

    def set_unusable_password(self):
        super().set_unusable_password()
        self._bump_auth_version = True

    def save(self, *args, **kwargs):
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            update_fields_set = set(update_fields)
            if 'email' in update_fields_set:
                self.email = normalize_email(self.email)
            if 'phone' in update_fields_set:
                self.phone = normalize_phone(self.phone)
        else:
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
    """One-time login codes (PRD Module 1: mobile OTP, plus the optional email
    code login). Auth-layer table like users — pre-tenant, so not under RLS.
    Codes are stored hashed. Each channel has its own active code: a new email
    code never cancels an outstanding phone code, and a code only verifies on
    the channel it was issued for."""

    class Channel(models.TextChoices):
        PHONE = 'phone', _('Phone')
        EMAIL = 'email', _('Email')

    class Purpose(models.TextChoices):
        LOGIN = 'login', _('Login')
        ACCOUNT_DELETION = 'account_deletion', _('Account deletion')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otp_codes')
    channel = models.CharField(max_length=10, choices=Channel.choices)
    # A code only verifies for the purpose it was issued for: a login code must
    # never authorise deleting the account.
    purpose = models.CharField(max_length=20, choices=Purpose.choices, default=Purpose.LOGIN)
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'otp_codes'
        indexes = [
            # verify(): filter(user, channel, used) ordered newest first.
            models.Index(fields=['user', 'channel', 'used', '-created_at'], name='otp_user_chan_used_idx'),
        ]


# Module 22. A request that is still unresolved: it keeps the account locked, blocks a
# duplicate request and is what GET /auth/account/deletion/ and /auth/me/ report. `failed`
# is deliberately in here: a purge that gave up is not a purge that finished.
ACTIVE_DELETION_STATUSES = ('pending', 'processing', 'failed')


class AccountDeletionQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status__in=ACTIVE_DELETION_STATUSES)

    def active_for(self, user):
        """The ACTIVE request that locks `user`: their own, or — for anyone in a
        tenant that is being deleted — the Owner's tenant-scope request. Keys on the
        user first and only looks at the tenant when there is one, so tenant-less
        accounts (Super Admins today, residents later) work unchanged. This is the one
        lookup shared by JWT auth, login and refresh; keep it import-light."""
        condition = Q(user_id=user.pk)
        if user.tenant_id is not None:
            condition |= Q(tenant_id=user.tenant_id, scope=AccountDeletionRequest.Scope.TENANT)
        return self.active().filter(condition)


class AccountDeletionRequest(models.Model):
    """A user's request to delete their account (Google Play requirement). Auth-layer
    table like `users` and `otp_codes`: not under RLS, because it is read before any
    tenant context exists (login, refresh) and outlives the tenant's own rows.

    Kept after completion as proof of deletion; it holds ids and timestamps only —
    `reason` and `last_error` are scrubbed when the request leaves `pending`.
    See docs/modules/22-account-deletion.md."""

    class Scope(models.TextChoices):
        USER = 'user', _('User')
        TENANT = 'tenant', _('Whole business')

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        PROCESSING = 'processing', _('Processing')
        COMPLETED = 'completed', _('Completed')
        CANCELLED = 'cancelled', _('Cancelled')
        FAILED = 'failed', _('Failed')
        SUPERSEDED = 'superseded', _('Superseded')

    class NoticeChannel(models.TextChoices):
        EMAIL = 'email', _('Email')
        SMS = 'sms', _('SMS')
        NONE = 'none', _('None')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='deletion_requests',
    )
    tenant = models.ForeignKey(
        Tenant, null=True, blank=True, on_delete=models.SET_NULL, related_name='deletion_requests',
    )
    scope = models.CharField(max_length=10, choices=Scope.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)

    requested_at = models.DateTimeField(default=timezone.now)
    # requested_at + grace days × 24h, rounded UP to the next 00:00 IST: always at least the
    # full grace period, and the purge lands on exactly that night's run.
    scheduled_for = models.DateTimeField()
    # Retry pacing: the request is only claimable once this has passed. Starts at
    # scheduled_for; a failed attempt pushes it to the next midnight IST.
    next_attempt_at = models.DateTimeField()

    # Lease: the worker that holds the request stamps its token and heartbeats claimed_at.
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_token = models.UUIDField(null=True, blank=True)

    # Phase stamps — a rerun resumes at the first unstamped phase.
    notified_at = models.DateTimeField(null=True, blank=True)
    notice_channel = models.CharField(max_length=5, choices=NoticeChannel.choices, blank=True, default='')
    razorpay_closed_at = models.DateTimeField(null=True, blank=True)
    db_purged_at = models.DateTimeField(null=True, blank=True)
    files_purged_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=200, blank=True, default='')  # class + model name, never PII
    reason = models.CharField(max_length=500, blank=True, default='')

    objects = AccountDeletionQuerySet.as_manager()

    class Meta:
        db_table = 'account_deletion_requests'
        ordering = ['-requested_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=Q(status__in=ACTIVE_DELETION_STATUSES),
                name='one_active_deletion_per_user',
            ),
            models.UniqueConstraint(
                fields=['tenant'],
                condition=Q(scope='tenant', status__in=ACTIVE_DELETION_STATUSES),
                name='one_active_deletion_per_tenant',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'scheduled_for'], name='acct_del_status_sched_idx'),
            models.Index(fields=['status', 'next_attempt_at'], name='acct_del_status_next_idx'),
        ]

    def __str__(self):
        return f'{self.scope} deletion {self.id} [{self.status}]'

    @property
    def is_reversible(self):
        """True until the first irreversible phase has been stamped: Razorpay closure for a
        tenant-scope request, the database purge for a user-scope one. After that the only
        valid recovery is retry-to-completion, never cancel/unlock."""
        if self.scope == self.Scope.TENANT:
            return self.razorpay_closed_at is None and self.db_purged_at is None
        return self.db_purged_at is None
