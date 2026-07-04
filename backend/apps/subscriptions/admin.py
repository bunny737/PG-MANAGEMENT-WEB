from django.contrib import admin

from .models import Plan, Subscription, SubscriptionPayment


class SubscriptionPaymentInline(admin.TabularInline):
    model = SubscriptionPayment
    extra = 0


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'price_per_month', 'max_properties', 'max_residents_per_property', 'is_active']


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['tenant', 'plan', 'razorpay_subscription_id']
    inlines = [SubscriptionPaymentInline]
