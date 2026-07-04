from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Append-only — no add/change, matches the model's own guarantee."""

    list_display = ('action', 'actor', 'object_type', 'object_id', 'tenant_id', 'created_at')
    list_filter = ('action', 'object_type')
    search_fields = ('action', 'object_type', 'object_id', 'actor__email')
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
