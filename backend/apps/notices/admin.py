from django.contrib import admin

from .models import Announcement, FoodHoliday, FoodHolidayCredit


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'property', 'category', 'is_pinned', 'expires_on', 'created_at')
    list_filter = ('category', 'is_pinned')
    raw_id_fields = ('property', 'created_by')


@admin.register(FoodHoliday)
class FoodHolidayAdmin(admin.ModelAdmin):
    list_display = ('name', 'property', 'start_date', 'end_date', 'adjust_in_bill', 'rate_per_day')
    list_filter = ('adjust_in_bill',)
    raw_id_fields = ('property', 'announcement', 'created_by')


@admin.register(FoodHolidayCredit)
class FoodHolidayCreditAdmin(admin.ModelAdmin):
    """Read-only: credits only change through apps.notices.credits (their
    PROTECT foreign keys would reject most hand edits anyway)."""

    list_display = ('holiday', 'resident', 'status', 'days', 'amount', 'clawback_amount')
    list_filter = ('status',)
    readonly_fields = [field.name for field in FoodHolidayCredit._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
