from django.contrib import admin

from .models import (
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


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['tenant', 'plan', 'razorpay_subscription_id']
    inlines = [SubscriptionPaymentInline]


class SubscriptionInvoiceLineInline(admin.TabularInline):
    model = SubscriptionInvoiceLine
    extra = 0


@admin.register(SubscriptionInvoice)
class SubscriptionInvoiceAdmin(admin.ModelAdmin):
    list_display = ['subscription', 'period_start', 'period_end', 'status', 'total_amount']
    list_filter = ['status']
    inlines = [SubscriptionInvoiceLineInline]
