from django.contrib import admin

from .models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    """Read-only ops visibility into sent/failed/skipped notifications — no
    dedicated API endpoint yet (PRD Module 18 doesn't specify one; see spec
    Decisions)."""

    list_display = ('notification_type', 'recipient_email', 'status', 'reference', 'sent_at', 'created_at')
    list_filter = ('notification_type', 'status')
    search_fields = ('recipient_email', 'reference', 'subject')
    readonly_fields = [f.name for f in NotificationLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
