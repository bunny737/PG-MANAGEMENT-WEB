from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.audit import log as audit_log

from . import services
from .models import (
    PRICING_LOCKED_MESSAGE,
    BedLedgerEntry,
    Plan,
    PlanBedTier,
    RazorpaySubscription,
    RazorpayWebhookEvent,
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

    # Inline deletes never call clean(), so permissions are what freeze a live
    # plan's pricing ladder.
    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and not (obj and obj.is_locked())

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and not (obj and obj.is_locked())

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and not (obj and obj.is_locked())


def _lock_plan(plan_id):
    """Row-lock a Plan when inside a transaction (admin change/delete views run in
    one). Same lock `select_plan` and the plan API take, so a tenant picking the
    plan can't land between this form's validation and its save."""
    if connection.in_atomic_block:
        Plan.objects.select_for_update().filter(pk=plan_id).first()


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'pricing_type', 'price_per_month', 'max_beds',
        'max_properties', 'max_residents_per_property', 'is_trial_plan', 'is_active',
    ]
    inlines = [PlanBedTierInline]
    # Set by select_plan, never by hand: an editable copy would let a form opened
    # before a tenant picked the plan blank the Razorpay link on save.
    readonly_fields = ['razorpay_plan_id']

    def get_object(self, request, object_id, from_field=None):
        # Lock first, then read: the form validates and saves against what we return,
        # so a pre-lock read could write back a stale razorpay_plan_id or price.
        obj = super().get_object(request, object_id, from_field)
        if obj is None:
            return None
        _lock_plan(obj.pk)
        return super().get_object(request, object_id, from_field)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or obj.is_deletable())

    def get_actions(self, request):
        # Bulk delete skips the per-object check above.
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions


@admin.register(PlanBedTier)
class PlanBedTierAdmin(admin.ModelAdmin):
    list_display = ['plan', 'up_to_beds', 'rate_per_bed']

    # Deletes never call clean(), and removing a live plan's open-ended tier
    # breaks pricing for every tenant on it, so permissions freeze the ladder
    # here exactly as they do in the inline.
    def get_object(self, request, object_id, from_field=None):
        obj = super().get_object(request, object_id, from_field)
        if obj is None:
            return None
        _lock_plan(obj.plan_id)
        return super().get_object(request, object_id, from_field)

    def save_model(self, request, obj, form, change):
        # Adding a tier, or moving one to another plan, has no object to lock in
        # get_object — lock the target plan and re-check it just before writing.
        with transaction.atomic():
            _lock_plan(obj.plan_id)
            if Plan.objects.get(pk=obj.plan_id).is_locked():
                raise PermissionDenied(str(PRICING_LOCKED_MESSAGE))
            super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and not (obj and obj.plan.is_locked())

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and not (obj and obj.plan.is_locked())

    def get_actions(self, request):
        # Bulk delete skips the per-object check above.
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions


@admin.register(RazorpaySubscription)
class RazorpaySubscriptionAdmin(admin.ModelAdmin):
    """Read-only ledger of every Razorpay subscription. Filter state=replaced or
    abandoned to see cancellations Razorpay hasn't yet confirmed (cancel_attempts and
    last_cancel_error say why); the retry task keeps working through them."""
    list_display = ['razorpay_subscription_id', 'subscription', 'plan', 'state', 'cancel_attempts', 'updated_at']
    list_filter = ['state']
    search_fields = ['razorpay_subscription_id', 'subscription__tenant__name']
    readonly_fields = [f.name for f in RazorpaySubscription._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RazorpayWebhookEvent)
class RazorpayWebhookEventAdmin(admin.ModelAdmin):
    """Every webhook received, including stale and ignored ones: the trail for out-of-order and conflicting
    deliveries. Filter outcome=needs_verification / verification_declined for events ops should reconcile
    against the Razorpay dashboard."""
    list_display = ['received_at', 'event_type', 'razorpay_subscription_id', 'occurred_at', 'outcome', 'detail']
    list_filter = ['outcome', 'event_type']
    search_fields = ['event_id', 'razorpay_subscription_id']
    readonly_fields = [f.name for f in RazorpayWebhookEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['tenant', 'plan', 'razorpay_subscription_id']
    inlines = [SubscriptionPaymentInline]

    def has_change_permission(self, request, obj=None):
        # Module 22: a subscription whose billing is closed for account deletion is view-only.
        if obj is not None and obj.status_hold == Subscription.STATUS_HOLD_DELETED:
            return False
        return super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        # The permission check above used the row as loaded for this form; re-check under the
        # row lock so a deletion closing it in between can't be overwritten.
        if change:
            try:
                services.assert_not_deleting(services.lock_subscription(obj.tenant))
            except services.TenantDeleted:
                messages.error(request, _('This account has been deleted; its billing can no longer be changed.'))
                return
        super().save_model(request, obj, form, change)


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    """Payments, and the refund queue: filter `refund_status=pending` for charges that must be
    returned by hand in the Razorpay dashboard, then set the status to refunded (with the
    Razorpay refund id) or waived (with a reason code). The refund fields hold codes and ids only —
    never free text — because this table outlives a deleted tenant."""
    list_display = ['subscription', 'amount', 'status', 'refund_status', 'razorpay_payment_id', 'paid_at', 'created_at']
    list_filter = ['status', 'refund_status']
    search_fields = ['subscription__tenant__name', 'razorpay_payment_id']
    readonly_fields = ['refund_flagged_at', 'refund_resolved_at', 'raw_payload']

    def save_model(self, request, obj, form, change):
        if change and 'refund_status' in form.changed_data:
            before = SubscriptionPayment.objects.values_list('refund_status', flat=True).get(pk=obj.pk)
            now = timezone.now()
            if obj.refund_status == SubscriptionPayment.RefundStatus.NONE:
                obj.refund_flagged_at = obj.refund_resolved_at = None
            elif obj.refund_status == SubscriptionPayment.RefundStatus.PENDING:
                obj.refund_flagged_at = obj.refund_flagged_at or now
                obj.refund_resolved_at = None
            else:
                obj.refund_flagged_at = obj.refund_flagged_at or now
                obj.refund_resolved_at = now
            super().save_model(request, obj, form, change)
            # Platform-level audit, ids and codes only (the tenant's own audit rows may be gone).
            audit_log.record(
                action='subscription.refund_resolved' if obj.refund_resolved_at else 'subscription.refund_status_changed',
                actor=request.user, tenant_id=None, obj=obj,
                before={'refund_status': before},
                after={'refund_status': obj.refund_status, 'refund_resolution': obj.refund_resolution,
                       'razorpay_payment_id': obj.razorpay_payment_id},
                request=request,
            )
            return
        super().save_model(request, obj, form, change)


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
