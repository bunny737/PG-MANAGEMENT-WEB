from django.contrib import admin

from apps.audit import log as audit_log

from .models import NotificationLog, NotificationPreference, NotificationTemplate, PushSubscription, ScheduledNotification
from .registry import context_vars_for


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    """Read-only ops visibility into sent/failed/skipped notifications
    across every channel — residents/owners see their own subset via the
    /notifications/history/ API; this is the full, cross-recipient view."""

    list_display = ('notification_type', 'channel', 'recipient_email', 'status', 'reference', 'sent_at', 'created_at')
    list_filter = ('notification_type', 'channel', 'status')
    search_fields = ('recipient_email', 'reference', 'subject')
    readonly_fields = [f.name for f in NotificationLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    """Super-Admin-editable wording — the whole point of moving content out
    of Python (see the module spec's Decisions). Content changes are
    audit-logged (invariant 9): this reaches every tenant's residents."""

    list_display = ('notification_type', 'channel', 'language', 'is_active', 'updated_at')
    list_filter = ('notification_type', 'channel', 'language', 'is_active')
    search_fields = ('notification_type', 'subject', 'body')

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        notification_type = obj.notification_type if obj else None
        context_vars = context_vars_for(notification_type) if notification_type else []
        if context_vars:
            placeholders = ', '.join(f'{{{{ {var} }}}}' for var in context_vars)
            form.base_fields['body'].help_text = f'Available placeholders: {placeholders}'
        return form

    def save_model(self, request, obj, form, change):
        before = None
        if change:
            before = {
                'subject': form.initial.get('subject'),
                'body': form.initial.get('body'),
                'is_active': form.initial.get('is_active'),
            }
        super().save_model(request, obj, form, change)
        audit_log.record(
            action='notification_template.updated' if change else 'notification_template.created',
            actor=request.user, tenant_id=None, obj=obj,
            before=before,
            after={'subject': obj.subject, 'body': obj.body, 'is_active': obj.is_active},
            request=request,
        )


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'device_type', 'last_seen_at')
    list_filter = ('device_type',)
    readonly_fields = [f.name for f in PushSubscription._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'notification_type', 'channel', 'enabled')
    list_filter = ('notification_type', 'channel', 'enabled')
    readonly_fields = [f.name for f in NotificationPreference._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(ScheduledNotification)
class ScheduledNotificationAdmin(admin.ModelAdmin):
    """Ops can hand-author a one-off scheduled notification here (e.g. a
    maintenance notice at a specific time); the beat-polled
    `dispatch_scheduled_notifications` task sends it when due."""

    list_display = ('notification_type', 'recipient_user', 'send_at', 'status', 'created_by')
    list_filter = ('notification_type', 'status')
    readonly_fields = ('id', 'status', 'created_at', 'updated_at')

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
            if not obj.tenant_id and obj.recipient_user_id:
                obj.tenant_id = obj.recipient_user.tenant_id
        super().save_model(request, obj, form, change)
