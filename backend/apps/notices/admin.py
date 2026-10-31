from django.contrib import admin

from .models import Announcement, FoodHoliday, FoodHolidayCredit


class ReadOnlyAdmin(admin.ModelAdmin):
    """View-only. Holidays, their notices and credits change only through
    apps.notices.services / credits — the edit lock, overlap check, credit
    reconciliation and audit trail all live there, and a plain admin save
    would skip every one of them (PROTECT only guards deletes)."""

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Announcement)
class AnnouncementAdmin(ReadOnlyAdmin):
    list_display = ('title', 'property', 'category', 'is_pinned', 'expires_on', 'created_at')
    list_filter = ('category', 'is_pinned')


@admin.register(FoodHoliday)
class FoodHolidayAdmin(ReadOnlyAdmin):
    list_display = ('name', 'property', 'start_date', 'end_date', 'adjust_in_bill', 'rate_per_day')
    list_filter = ('adjust_in_bill',)


@admin.register(FoodHolidayCredit)
class FoodHolidayCreditAdmin(ReadOnlyAdmin):
    list_display = ('holiday', 'resident', 'status', 'days', 'amount', 'clawback_amount')
    list_filter = ('status',)
