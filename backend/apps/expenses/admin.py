from django.contrib import admin

from .models import Expense, ExpenseCategory


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'tenant_id', 'is_system', 'is_archived')
    list_filter = ('is_system', 'is_archived')


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('date', 'amount', 'category', 'property', 'payment_mode', 'deleted_at')
    list_filter = ('payment_mode',)
    raw_id_fields = ('property', 'category', 'created_by', 'updated_by', 'deleted_by')
