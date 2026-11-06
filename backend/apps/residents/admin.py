from django.contrib import admin

from .models import (
    AbscondedRecord,
    Admission,
    Allocation,
    BlacklistEntry,
    ResidencyLinkRequest,
    Resident,
    ResidentAccess,
    ResidentInvite,
    Transfer,
    Vacate,
)

admin.site.register(Resident)
admin.site.register(Admission)
admin.site.register(Allocation)
admin.site.register(Transfer)
admin.site.register(Vacate)
admin.site.register(AbscondedRecord)
admin.site.register(BlacklistEntry)


class _ReadOnlyAdmin(admin.ModelAdmin):
    """Resident app access (Module 26) is changed only through its services, which hold the locks,
    re-check eligibility and write the audit trail. A hand edit here would bypass all three, so
    these screens are for looking, not changing."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ResidentAccess)
class ResidentAccessAdmin(_ReadOnlyAdmin):
    list_display = ('id', 'user', 'resident', 'status', 'origin', 'activated_at', 'access_expires_at')
    list_filter = ('status', 'origin')
    raw_id_fields = ('user', 'resident', 'granted_by', 'revoked_by')


@admin.register(ResidentInvite)
class ResidentInviteAdmin(_ReadOnlyAdmin):
    # The token hash is deliberately not shown.
    list_display = ('id', 'resident', 'email', 'status', 'expires_at', 'created_at')
    list_filter = ('status',)
    exclude = ('token_hash',)
    raw_id_fields = ('resident', 'invited_by', 'cancelled_by', 'accepted_by', 'resulting_access')


@admin.register(ResidencyLinkRequest)
class ResidencyLinkRequestAdmin(_ReadOnlyAdmin):
    list_display = ('id', 'requester', 'property', 'status', 'created_at')
    list_filter = ('status',)
    raw_id_fields = ('requester', 'property', 'resolved_by', 'resolved_resident', 'resulting_access')
