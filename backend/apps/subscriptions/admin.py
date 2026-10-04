from django.contrib import admin

from .models import (
    BedLedgerEntry,
    Plan,
    PlanBedTier,
    Subscription,
    SubscriptionInvoice,
    SubscriptionInvoiceLine,
    SubscriptionPayment,
)


class SubscriptionPaymentInline(admin.TabularInline):
    model = SubscriptionPayment
    extra = 0


class PlanBedTierInline(admin.TabularInline):
    """Super Admin's editing surface for a PER_BED_MONTHLY plan's pricing
    ladder (invariant 10 — the tier rates/thresholds are config here, never
    literals in code)."""
    model = PlanBedTier
    extra = 1


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'pricing_type', 'price_per_month',
        'max_properties', 'max_residents_per_property', 'is_active',
    ]
    inlines = [PlanBedTierInline]


@admin.register(PlanBedTier)
class PlanBedTierAdmin(admin.ModelAdmin):
    list_display = ['plan', 'up_to_beds', 'rate_per_bed']


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['tenant', 'plan', 'razorpay_subscription_id']
    inlines = [SubscriptionPaymentInline]


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = ['subscription', 'amount', 'status', 'razorpay_payment_id', 'paid_at', 'created_at']
    list_filter = ['status']
    search_fields = ['subscription__tenant__name', 'razorpay_payment_id']


class SubscriptionInvoiceLineInline(admin.TabularInline):
    model = SubscriptionInvoiceLine
    extra = 0


@admin.register(SubscriptionInvoice)
class SubscriptionInvoiceAdmin(admin.ModelAdmin):
    list_display = ['subscription', 'period_start', 'period_end', 'status', 'total_amount']
    list_filter = ['status']
    inlines = [SubscriptionInvoiceLineInline]


@admin.register(SubscriptionInvoiceLine)
class SubscriptionInvoiceLineAdmin(admin.ModelAdmin):
    list_display = ['invoice', 'description', 'quantity', 'unit_rate', 'amount']


@admin.register(BedLedgerEntry)
class BedLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ['tenant_id', 'bed_id', 'event', 'occurred_at']
    list_filter = ['event']
    readonly_fields = [f.name for f in BedLedgerEntry._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
