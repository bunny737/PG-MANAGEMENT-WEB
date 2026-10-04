from django.contrib import admin

from .models import PlatformConfig


@admin.register(PlatformConfig)
class PlatformConfigAdmin(admin.ModelAdmin):
    list_display = (
        'trial_days',
        'payment_grace_days',
        'trial_reminder_first_days_before',
        'trial_reminder_second_days_before',
        'min_billable_amount',
        'updated_at',
    )
    readonly_fields = ('updated_at',)

    def has_delete_permission(self, request, obj=None):
        return False
