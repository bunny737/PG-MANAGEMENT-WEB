from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

from apps.core.roles import Role, STAFF_ROLES
from .models import OtpCode, Tenant, User
from .normalization import normalize_email, normalize_phone


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
        ('Important Dates', {'fields': ('last_login', 'created_at', 'updated_at')}),
    )
    readonly_fields = ('created_at', 'updated_at', 'last_login')

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'phone', 'first_name', 'last_name', 'role', 'tenant', 'password1', 'password2'),
        }),
    )


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'default_language', 'trial_ends_at', 'created_at')
    list_filter = ('status', 'default_language')
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(OtpCode)
class OtpCodeAdmin(admin.ModelAdmin):
    list_display = ('user', 'expires_at', 'attempts', 'used', 'created_at')
    list_filter = ('used',)
    search_fields = ('user__email', 'user__phone')
    readonly_fields = ('id', 'code_hash', 'created_at')
