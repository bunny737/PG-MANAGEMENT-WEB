from django.contrib import admin

from .models import Discount, Invoice, InvoiceLineItem


class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    inlines = [InvoiceLineItemInline]


admin.site.register(Discount)

