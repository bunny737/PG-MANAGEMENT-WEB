from django import forms
from django.contrib import admin
from django.shortcuts import render
from django.urls import path
from django.utils.translation import gettext_lazy as _

from apps.audit import log as audit_log
from apps.core.tenancy import tenant_context

from . import reports
from .models import AppInstallation, AppInstallationHistory, AppVersionPolicy

POLICY_AUDIT_FIELDS = (
    'platform', 'flavor', 'min_build', 'latest_build', 'latest_version', 'store_url',
    'release_notes', 'soft_update_enabled', 'maintenance_enabled', 'maintenance_message',
    'maintenance_expires_at', 'check_interval_seconds',
)


def policy_snapshot(policy):
    """JSON-safe dict of the policy's editable fields for the audit log."""
    snapshot = {}
    for name in POLICY_AUDIT_FIELDS:
        value = getattr(policy, name)
        snapshot[name] = value.isoformat() if hasattr(value, 'isoformat') else value
    return snapshot


def mask_token(token):
    if not token:
        return '—'
    if len(token) <= 12:
        return '•' * len(token)
    return f'{token[:4]}…{token[-4:]}'


class AppVersionPolicyForm(forms.ModelForm):
    confirm_min_build_raise = forms.BooleanField(
        required=False, label=_('Confirm raising min_build'),
        help_text=_(
            'Raising min_build force-updates every install below it. Tick only after the new '
            'build is fully live in the store (Play: staged rollout finished; App Store: released, '
            'not in review/TestFlight).'
        ),
    )

    class Meta:
        model = AppVersionPolicy
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk:
            old = AppVersionPolicy.objects.filter(pk=self.instance.pk).values_list('min_build', flat=True).first()
            new = cleaned.get('min_build')
            if old is not None and new is not None and new > old and not cleaned.get('confirm_min_build_raise'):
                raise forms.ValidationError(
                    _('You are raising min_build from %(old)s to %(new)s. Tick "Confirm raising min_build" to proceed.'),
                    params={'old': old, 'new': new}, code='confirm_min_build_raise',
                )
        return cleaned


@admin.register(AppVersionPolicy)
class AppVersionPolicyAdmin(admin.ModelAdmin):
    form = AppVersionPolicyForm
    list_display = (
        'platform', 'flavor', 'min_build', 'latest_build', 'latest_version',
        'soft_update_enabled', 'maintenance_enabled', 'updated_by', 'updated_at',
    )
    list_filter = ('platform', 'flavor', 'maintenance_enabled')
    readonly_fields = ('updated_by', 'updated_at')

    def save_model(self, request, obj, form, change):
        before = None
        if change:
            existing = AppVersionPolicy.objects.filter(pk=obj.pk).first()
            before = policy_snapshot(existing) if existing else None
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
        audit_log.record(
            action='app_version_policy.updated' if change else 'app_version_policy.created',
            actor=request.user, tenant_id=None, obj=obj,
            before=before, after=policy_snapshot(obj), request=request,
        )

    def delete_model(self, request, obj):
        before = policy_snapshot(obj)
        pk = obj.pk
        super().delete_model(request, obj)
        obj.pk = pk  # delete() clears it; the audit row still needs the id
        audit_log.record(
            action='app_version_policy.deleted', actor=request.user, tenant_id=None,
            obj=obj, before=before, request=request,
        )


class AppInstallationHistoryInline(admin.TabularInline):
    model = AppInstallationHistory
    extra = 0
    can_delete = False
    readonly_fields = ('build_number', 'version_name', 'os_version', 'recorded_at')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AppInstallation)
class AppInstallationAdmin(admin.ModelAdmin):
    """Read-only: installs are written only by the app's own registration call."""

    change_list_template = 'admin/devices/appinstallation/change_list.html'
    list_display = (
        'installation_id', 'user', 'platform', 'flavor', 'version_name', 'build_number',
        'device_model', 'os_version', 'masked_fcm_token', 'last_seen_at',
    )
    list_filter = ('platform', 'flavor', 'build_number', 'push_permission')
    search_fields = ('installation_id', 'user__email', 'device_model')
    raw_id_fields = ('user',)
    date_hierarchy = 'last_seen_at'
    inlines = [AppInstallationHistoryInline]
    # fcm_token is never rendered raw: it is excluded and shown masked.
    exclude = ('fcm_token',)

    def get_readonly_fields(self, request, obj=None):
        names = [f.name for f in AppInstallation._meta.fields if f.name != 'fcm_token']
        return names + ['masked_fcm_token']

    @admin.display(description=_('FCM token'))
    def masked_fcm_token(self, obj):
        return mask_token(obj.fcm_token)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    # Deleting an install nulls PushSubscription.installation; that table is
    # under RLS and admin requests carry no tenant context, so run as super admin.
    def delete_model(self, request, obj):
        with tenant_context(None, is_super_admin=True):
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        with tenant_context(None, is_super_admin=True):
            super().delete_queryset(request, queryset)

    def get_urls(self):
        custom = [
            path('adoption-report/', self.admin_site.admin_view(self.adoption_report_view),
                 name='devices_appinstallation_report'),
        ]
        return custom + super().get_urls()

    def adoption_report_view(self, request):
        context = {
            **self.admin_site.each_context(request),
            'title': _('App adoption report'),
            'window_days': reports.ACTIVE_WINDOW_DAYS,
            'summary': reports.adoption_summary(),
            'by_build': reports.active_installs_by_build(),
            'top_models': reports.top_device_models(),
            'top_os': reports.top_os_versions(),
            'opts': self.model._meta,
        }
        return render(request, 'admin/devices/appinstallation/adoption_report.html', context)
