from django.contrib import admin

from .models import Discount, Invoice, InvoiceLineItem, Payment


class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['resident', 'period_start', 'period_end', 'status', 'due_date']
    list_filter = ['status', 'billing_mode']
    inlines = [InvoiceLineItemInline, PaymentInline]


@admin.register(InvoiceLineItem)
class InvoiceLineItemAdmin(admin.ModelAdmin):
    list_display = ['invoice', 'line_type', 'label', 'amount', 'order']
    list_filter = ['line_type']
    search_fields = ['label']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['invoice', 'amount', 'payment_date', 'payment_mode', 'recorded_by']
    list_filter = ['payment_mode']


admin.site.register(Discount)
