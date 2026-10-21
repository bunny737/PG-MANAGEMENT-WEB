from collections import Counter

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from apps.audit import log as audit_log
from apps.core.roles import Role, STAFF_ROLES
from apps.core.tasks import enqueue
from .models import OtpCode, Tenant, User
from .normalization import normalize_email, normalize_phone
from .tasks import send_verification_email_to_user_task


def _queue_verification_on_commit(user):
    """Account-bound verification email after the admin transaction commits.
    Plain values are captured now; the worker re-checks the account still holds
    this address."""
    user_id, expected_email = str(user.pk), user.email
    transaction.on_commit(
        lambda: enqueue(send_verification_email_to_user_task, user_id, expected_email)
    )


def _verification_skip_reason(user):
    """Why an admin verification action leaves this user alone, or None."""
    if not user.is_active:
        return 'inactive'
    if not user.email:
        return 'no_email'
    if user.email_verified:
        return 'already_verified'
    return None


class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('email', 'phone', 'first_name', 'last_name', 'role', 'tenant')

    def clean_email(self):
        email = self.cleaned_data.get('email')
        try:
            return normalize_email(email)
        except ValueError as exc:
            raise forms.ValidationError(str(exc))

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        try:
            return normalize_phone(phone)
        except ValueError as exc:
            raise forms.ValidationError(str(exc))

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        phone = cleaned_data.get('phone')
        role = cleaned_data.get('role')

        if role in (Role.OWNER, Role.SUPER_ADMIN) and not email:
            self.add_error('email', forms.ValidationError(_('Email is required for Owner and Super Admin.')))
        if role in STAFF_ROLES and not phone:
            self.add_error('phone', forms.ValidationError(_('Phone number is required for staff.')))
        if not email and not phone:
            raise forms.ValidationError(_('At least one of email or phone is required.'))
        return cleaned_data


class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = '__all__'

    def clean_email(self):
        email = self.cleaned_data.get('email')
        try:
            return normalize_email(email)
        except ValueError as exc:
            raise forms.ValidationError(str(exc))

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        try:
            return normalize_phone(phone)
        except ValueError as exc:
            raise forms.ValidationError(str(exc))

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        phone = cleaned_data.get('phone')
        role = cleaned_data.get('role')

        if role in (Role.OWNER, Role.SUPER_ADMIN) and not email:
            self.add_error('email', forms.ValidationError(_('Email is required for Owner and Super Admin.')))
        if role in STAFF_ROLES and not phone:
            self.add_error('phone', forms.ValidationError(_('Phone number is required for staff.')))
        if not email and not phone:
            raise forms.ValidationError(_('At least one of email or phone is required.'))
        return cleaned_data


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = CustomUserChangeForm
    add_form = CustomUserCreationForm

    list_display = ('email', 'phone', 'first_name', 'last_name', 'role', 'tenant', 'is_staff', 'is_active')
    list_filter = ('role', 'is_staff', 'is_active', 'email_verified')
    search_fields = ('email', 'first_name', 'last_name', 'phone')
    ordering = ('created_at',)

    fieldsets = (
        (None, {'fields': ('email', 'phone', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'tenant', 'role', 'language_code')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'email_verified', 'groups', 'user_permissions')}),
        ('Module access (edit via Team Management)', {'fields': ('module_access',)}),
        ('Important Dates', {'fields': ('last_login', 'created_at', 'updated_at')}),
    )
    # email_verified only changes through the audited actions below (or the
    # owner's own verification link), never through a bare checkbox.
    readonly_fields = ('created_at', 'updated_at', 'last_login', 'module_access', 'email_verified')
    actions = ['send_verification_email', 'mark_email_verified']

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            # language_code: the first verification email goes out in it.
            'fields': ('email', 'phone', 'first_name', 'last_name', 'role', 'tenant', 'language_code',
                       'password1', 'password2'),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            super().save_model(request, obj, form, change)
            if obj.email and not obj.email_verified:
                _queue_verification_on_commit(obj)
            return
        with transaction.atomic():
            # `obj` already holds the form's values; the locked stored row is the
            # only reliable "before".
            stored = User.objects.select_for_update().get(pk=obj.pk)
            email_changed = normalize_email(stored.email) != normalize_email(obj.email)
            if email_changed:
                # A new sign-in/recovery address: unverified until its owner
                # confirms it, and every existing session ends (auth_version is
                # taken from the locked row, not the possibly stale form object).
                obj.email_verified = False
                obj.auth_version = stored.auth_version + 1
            super().save_model(request, obj, form, change)
            if email_changed:
                audit_log.record(
                    action='user.email_changed_by_admin',
                    actor=request.user,
                    tenant_id=obj.tenant_id,
                    obj=obj,
                    before={'email': stored.email, 'email_verified': stored.email_verified,
                            'auth_version': stored.auth_version},
                    after={'email': obj.email, 'email_verified': False,
                           'auth_version': obj.auth_version},
                    request=request,
                )
                if obj.email and obj.is_active:
                    _queue_verification_on_commit(obj)

    @admin.action(description=_('Send verification email'))
    def send_verification_email(self, request, queryset):
        counts = Counter()
        for user in queryset.order_by('pk'):
            reason = _verification_skip_reason(user)
            if reason:
                counts[reason] += 1
                continue
            # Audit first, so no email is ever queued without its record (if the
            # insert fails, nothing is queued). "Requested", not "sent": the
            # worker hasn't delivered anything yet. Audit rows are append-only,
            # so a broker failure is a second row rather than an edit.
            audit_log.record(
                action='user.verification_email_requested_by_admin',
                actor=request.user,
                tenant_id=user.tenant_id,
                obj=user,
                after={'email': user.email},
                request=request,
            )
            queued = enqueue(send_verification_email_to_user_task, str(user.pk), user.email) is not None
            counts['queued' if queued else 'broker_unavailable'] += 1
            if not queued:
                audit_log.record(
                    action='user.verification_email_queue_failed',
                    actor=request.user,
                    tenant_id=user.tenant_id,
                    obj=user,
                    after={'email': user.email, 'queued': False},
                    request=request,
                )
        self.message_user(
            request,
            gettext(
                'Verification emails queued: %(queued)d. Broker unavailable: %(broker)d. '
                'Skipped — inactive: %(inactive)d, no email: %(no_email)d, '
                'already verified: %(verified)d.'
            ) % {
                'queued': counts['queued'], 'broker': counts['broker_unavailable'],
                'inactive': counts['inactive'], 'no_email': counts['no_email'],
                'verified': counts['already_verified'],
            },
            messages.WARNING if counts['broker_unavailable'] else messages.SUCCESS,
        )

    @admin.action(description=_('Mark email verified'))
    def mark_email_verified(self, request, queryset):
        counts = Counter()
        with transaction.atomic():
            # pk order: two overlapping bulk actions take their row locks in the
            # same order instead of deadlocking.
            users = list(
                User.objects.select_for_update()
                .filter(pk__in=queryset.values('pk'))
                .order_by('pk')
            )
            now = timezone.now()
            for user in users:
                reason = _verification_skip_reason(user)
                if reason:
                    counts[reason] += 1
                    continue
                User.objects.filter(pk=user.pk).update(email_verified=True, updated_at=now)
                audit_log.record(
                    action='user.email_verified_by_admin',
                    actor=request.user,
                    tenant_id=user.tenant_id,
                    obj=user,
                    before={'email_verified': False},
                    after={'email_verified': True},
                    request=request,
                )
                counts['verified'] += 1
        self.message_user(
            request,
            gettext(
                'Marked verified: %(verified)d. Skipped — inactive: %(inactive)d, '
                'no email: %(no_email)d, already verified: %(already)d.'
            ) % {
                'verified': counts['verified'], 'inactive': counts['inactive'],
                'no_email': counts['no_email'], 'already': counts['already_verified'],
            },
            messages.SUCCESS,
        )


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'default_language', 'trial_ends_at', 'created_at')
    list_filter = ('status', 'default_language')
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change and 'status' in form.changed_data:
            # A suspension or cancellation made here is manual: Razorpay webhooks must not undo it
            # (apps.subscriptions.webhook_policy). Any other status clears the hold.
            from apps.subscriptions.services import set_manual_status_hold
            set_manual_status_hold(obj, obj.status in (Tenant.Status.SUSPENDED, Tenant.Status.CANCELLED))


@admin.register(OtpCode)
class OtpCodeAdmin(admin.ModelAdmin):
    list_display = ('user', 'expires_at', 'attempts', 'used', 'created_at')
    list_filter = ('used',)
    search_fields = ('user__email', 'user__phone')
    readonly_fields = ('id', 'code_hash', 'created_at')
