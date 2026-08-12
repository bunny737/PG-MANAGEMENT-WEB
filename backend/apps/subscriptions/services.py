"""Plan-limit enforcement, plan selection, and Razorpay webhook handling
(PRD §4 'Subscription & Pricing Model', Module 20 'Subscription Management').
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from decimal import Decimal

from apps.accounts.models import Tenant
from apps.audit import log as audit_log
from apps.core.models import PlatformConfig
from apps.core.tenancy import tenant_context
from apps.properties.models import Bed, Property
from apps.residents.models import Resident

from . import pricing, razorpay_client
from .models import Plan, Subscription, SubscriptionInvoice, SubscriptionInvoiceLine, SubscriptionPayment


def get_or_create_subscription(tenant):
    """Every tenant gets a blank Subscription at signup; lazily create one
    for any that don't (older fixtures, data-fix scenarios) rather than
    500ing — mirrors Module 02's PropertySettings lazy-creation."""
    subscription, _created = Subscription.objects.get_or_create(tenant=tenant)
    return subscription


def check_property_limit(tenant_id):
    """Hard block (PRD: 'Hard block when either limit is reached'). A
    tenant with no Subscription row, no plan, or an unlimited plan has
    nothing to enforce — intentionally fail-open, so limits only bite once
    a Super Admin has actually configured a plan."""
    subscription = Subscription.objects.filter(tenant_id=tenant_id).select_related('plan', 'tenant').first()
    if subscription is None:
        return
    max_properties = subscription.effective_max_properties()
    if max_properties is None:
        return
    current = Property.objects.filter(tenant_id=tenant_id).count()
    if current >= max_properties:
        raise ValidationError(
            {'detail': _('Your plan allows a maximum of %(max)s properties. Upgrade to add more.')
             % {'max': max_properties}},
            code='property_limit_reached',
        )


def get_total_beds(tenant_id):
    """Billable bed count for PER_BED_MONTHLY plans — every `Bed` row under
    the tenant (provisioned capacity, not occupancy; PRD/owner decision:
    matches Google Workspace's per-seat-provisioned basis, and excluding
    e.g. `maintenance` beds would be an easy way to game the bill)."""
    return Bed.objects.filter(tenant_id=tenant_id).count()


def estimate_current_cycle(subscription):
    """Live PER_BED_MONTHLY preview at today's bed count — shared by the
    Subscription serializer (`current_cycle_estimate`) and the
    `price-preview` API action so the two never diverge. This is an
    estimate, not the eventual invoice: the real invoice prices the whole
    cycle's bed-day history via `pricing.prorated_charge`
    (`generate_invoice_for_subscription`), not just today's snapshot."""
    plan = subscription.effective_plan()
    if plan is None or plan.pricing_type != Plan.PricingType.PER_BED_MONTHLY:
        return None
    breakdown = pricing.monthly_charge(plan, get_total_beds(subscription.tenant_id))
    return {
        'bed_count': breakdown.bed_count,
        'total': str(breakdown.total),
        'tier_lines': [
            {
                'up_to_beds': line.up_to_beds, 'rate_per_bed': str(line.rate_per_bed),
                'beds_in_tier': line.beds_in_tier, 'subtotal': str(line.subtotal),
            }
            for line in breakdown.tier_lines
        ],
    }


def check_resident_limit(property):
    """Same hard block, per-property (PRD: 'Resident count is checked per
    property, not across all properties combined')."""
    subscription = (
        Subscription.objects.filter(tenant_id=property.tenant_id).select_related('plan', 'tenant').first()
    )
    if subscription is None:
        return
    max_residents = subscription.effective_max_residents_per_property()
    if max_residents is None:
        return
    current = Resident.objects.filter(
        property=property, status__in=Resident.COUNTS_TOWARD_PLAN_LIMIT
    ).count()
    if current >= max_residents:
        raise ValidationError(
            {'detail': _(
                'Your plan allows a maximum of %(max)s active residents per property. Upgrade to add more.'
            ) % {'max': max_residents}},
            code='resident_limit_reached',
        )


@transaction.atomic
def select_plan(*, subscription, plan, actor, request=None):
    """Owner selects/changes a plan (PRD: 'Plan upgrade/downgrade available
    anytime'). Branches on `plan.pricing_type`:

    FLAT_MONTHLY — unchanged from the original flow. Creates the Razorpay
    plan (first time only) and a fresh Razorpay subscription. Selecting a
    plan does NOT itself flip the tenant to Active — that happens when a
    webhook confirms the first charge.

    PER_BED_MONTHLY — there is no advance charge to confirm (billing is in
    arrears, at cycle close — see `generate_invoice_for_subscription`), so
    plan selection activates the tenant immediately once the Razorpay
    customer exists. See the Module 13 spec's Decisions for why the two
    pricing types differ on activation timing."""
    before_plan = subscription.plan.name if subscription.plan else None
    tenant = subscription.tenant

    if plan.pricing_type == Plan.PricingType.PER_BED_MONTHLY:
        subscription.plan = plan
        if not subscription.razorpay_customer_id:
            subscription.razorpay_customer_id = razorpay_client.create_razorpay_customer(tenant)
        subscription.razorpay_subscription_id = ''
        today = timezone.now().date()
        subscription.current_period_start = today
        subscription.current_period_end = pricing.next_cycle_end(today)
        subscription.save(update_fields=[
            'plan', 'razorpay_customer_id', 'razorpay_subscription_id',
            'current_period_start', 'current_period_end', 'updated_at',
        ])
        if tenant.status == Tenant.Status.TRIAL:
            before_status = tenant.status
            tenant.status = Tenant.Status.ACTIVE
            tenant.save(update_fields=['status', 'updated_at'])
            audit_log.record(
                action='tenant.status_changed', actor=actor, tenant_id=tenant.id, obj=tenant,
                before={'status': before_status}, after={'status': tenant.status}, request=request,
            )
    else:
        if not plan.razorpay_plan_id:
            plan.razorpay_plan_id = razorpay_client.create_razorpay_plan(plan)
            plan.save(update_fields=['razorpay_plan_id', 'updated_at'])

        subscription.plan = plan
        subscription.razorpay_subscription_id = razorpay_client.create_razorpay_subscription(plan)
        subscription.save(update_fields=['plan', 'razorpay_subscription_id', 'updated_at'])

    audit_log.record(
        action='subscription.plan_selected', actor=actor, tenant_id=subscription.tenant_id,
        obj=subscription, before={'plan': before_plan}, after={'plan': plan.name},
        request=request,
    )
    return subscription


@transaction.atomic
def handle_webhook_event(payload):
    """Processes a Razorpay webhook payload (PRD Module 20: 'Razorpay
    webhook handling for payment success/failure'). Two independent event
    families, because FLAT_MONTHLY and PER_BED_MONTHLY use different
    Razorpay primitives (Phase 0 spike: Add-ons are deprecated, so arrears
    amounts are billed via Invoices, not Subscriptions):

    - `subscription.*` — advance billing, keyed by `razorpay_subscription_id`.
    - `invoice.*` — arrears billing, keyed by `razorpay_invoice_id` on
      `SubscriptionInvoice` (see `generate_invoice_for_subscription`)."""
    event = payload.get('event', '')
    if event.startswith('invoice.'):
        _handle_invoice_webhook(event, payload)
    else:
        _handle_subscription_webhook(event, payload)


def _handle_subscription_webhook(event, payload):
    """FLAT_MONTHLY: looks the Subscription up by its stored
    `razorpay_subscription_id` since the webhook carries no concept of our
    tenant id."""
    entity = payload.get('payload', {}).get('subscription', {}).get('entity', {})
    razorpay_subscription_id = entity.get('id', '')

    subscription = (
        Subscription.objects.filter(razorpay_subscription_id=razorpay_subscription_id)
        .select_related('tenant', 'plan').first()
    )
    if subscription is None:
        return  # unknown subscription — nothing to reconcile

    tenant = subscription.tenant
    before_status = tenant.status
    payment_entity = payload.get('payload', {}).get('payment', {}).get('entity', {})
    razorpay_payment_id = payment_entity.get('id', '')
    # The amount Razorpay actually charged (paise), not the plan's list price —
    # the two used to silently diverge whenever a payment carried an adjusted amount.
    raw_amount = payment_entity.get('amount')
    charged_amount = (
        Decimal(raw_amount) / 100 if raw_amount is not None
        else (subscription.plan.price_per_month if subscription.plan else Decimal('0'))
    )

    # No authenticated request set the Postgres tenant context (the webhook
    # is deliberately unauthenticated — see RazorpayWebhookView), so this
    # must set it manually before writing the RLS-scoped SubscriptionPayment.
    with tenant_context(tenant.id):
        if event in ('subscription.activated', 'subscription.charged'):
            # Idempotency: a replayed webhook must not double-record the same charge.
            if razorpay_payment_id and SubscriptionPayment.objects.filter(
                razorpay_payment_id=razorpay_payment_id
            ).exists():
                return
            tenant.status = Tenant.Status.ACTIVE
            subscription.payment_failed_at = None
            current_start = entity.get('current_start')
            current_end = entity.get('current_end')
            today = timezone.now().date()
            subscription.current_period_start = (
                datetime_from_epoch(current_start) if current_start else today
            )
            subscription.current_period_end = (
                datetime_from_epoch(current_end) if current_end else pricing.next_cycle_end(today)
            )
            SubscriptionPayment.objects.create(
                tenant_id=tenant.id, subscription=subscription,
                razorpay_payment_id=razorpay_payment_id, amount=charged_amount,
                status=SubscriptionPayment.Status.SUCCESS, paid_at=timezone.now(), raw_payload=payload,
            )
        elif event == 'subscription.halted':
            tenant.status = Tenant.Status.SUSPENDED
        elif event == 'subscription.cancelled':
            tenant.status = Tenant.Status.CANCELLED
        elif event == 'payment.failed':
            tenant.status = Tenant.Status.PAYMENT_FAILED
            subscription.payment_failed_at = timezone.now()
            SubscriptionPayment.objects.create(
                tenant_id=tenant.id, subscription=subscription,
                razorpay_payment_id=razorpay_payment_id, amount=charged_amount,
                status=SubscriptionPayment.Status.FAILED, raw_payload=payload,
            )
        else:
            return  # unhandled event type — ignore

        subscription.save()
        tenant.save(update_fields=['status', 'updated_at'])

        if tenant.status != before_status:
            audit_log.record(
                action='tenant.status_changed', tenant_id=tenant.id, obj=tenant,
                before={'status': before_status}, after={'status': tenant.status},
            )


def _handle_invoice_webhook(event, payload):
    """PER_BED_MONTHLY: looks the SubscriptionInvoice up by its stored
    `razorpay_invoice_id` (set when `generate_invoice_for_subscription`
    issues the cycle's invoice)."""
    entity = payload.get('payload', {}).get('invoice', {}).get('entity', {})
    razorpay_invoice_id = entity.get('id', '')

    invoice = (
        SubscriptionInvoice.objects.filter(razorpay_invoice_id=razorpay_invoice_id)
        .select_related('subscription__tenant').first()
    )
    if invoice is None:
        return  # unknown invoice — nothing to reconcile

    subscription = invoice.subscription
    tenant = subscription.tenant
    before_status = tenant.status
    payment_entity = payload.get('payload', {}).get('payment', {}).get('entity', {})
    razorpay_payment_id = payment_entity.get('id', '')

    with tenant_context(tenant.id):
        if event == 'invoice.paid':
            if razorpay_payment_id and SubscriptionPayment.objects.filter(
                razorpay_payment_id=razorpay_payment_id
            ).exists():
                return
            invoice.status = SubscriptionInvoice.Status.PAID
            invoice.paid_at = timezone.now()
            invoice.save(update_fields=['status', 'paid_at'])
            subscription.payment_failed_at = None
            subscription.save(update_fields=['payment_failed_at', 'updated_at'])
            if tenant.status == Tenant.Status.PAYMENT_FAILED:
                tenant.status = Tenant.Status.ACTIVE
            SubscriptionPayment.objects.create(
                tenant_id=tenant.id, subscription=subscription,
                razorpay_payment_id=razorpay_payment_id, amount=invoice.total_amount,
                status=SubscriptionPayment.Status.SUCCESS, paid_at=timezone.now(), raw_payload=payload,
            )
        elif event in ('invoice.expired', 'invoice.partially_paid'):
            invoice.status = SubscriptionInvoice.Status.FAILED
            invoice.save(update_fields=['status'])
            tenant.status = Tenant.Status.PAYMENT_FAILED
            subscription.payment_failed_at = timezone.now()
            subscription.save(update_fields=['payment_failed_at', 'updated_at'])
            SubscriptionPayment.objects.create(
                tenant_id=tenant.id, subscription=subscription,
                razorpay_payment_id=razorpay_payment_id, amount=invoice.total_amount,
                status=SubscriptionPayment.Status.FAILED, raw_payload=payload,
            )
        else:
            return  # unhandled event type — ignore

        if tenant.status != before_status:
            tenant.save(update_fields=['status', 'updated_at'])
            audit_log.record(
                action='tenant.status_changed', tenant_id=tenant.id, obj=tenant,
                before={'status': before_status}, after={'status': tenant.status},
            )


def datetime_from_epoch(seconds):
    """Razorpay entity timestamps are UTC epoch seconds — convert
    explicitly rather than via the naive, local-timezone `date.fromtimestamp`."""
    return datetime.fromtimestamp(seconds, tz=dt_timezone.utc).date()


def override_limits(*, subscription, max_properties_override, max_residents_override, actor, request=None):
    """Super Admin manual override 'for a specific tenant if needed (e.g.
    grace period, enterprise negotiation)' (PRD §4)."""
    before = {
        'max_properties_override': subscription.max_properties_override,
        'max_residents_override': subscription.max_residents_override,
    }
    subscription.max_properties_override = max_properties_override
    subscription.max_residents_override = max_residents_override
    subscription.save(update_fields=['max_properties_override', 'max_residents_override', 'updated_at'])
    audit_log.record(
        action='subscription.limits_overridden', actor=actor, tenant_id=subscription.tenant_id,
        obj=subscription, before=before,
        after={'max_properties_override': max_properties_override, 'max_residents_override': max_residents_override},
        request=request,
    )
    return subscription


def suspend_tenant(*, tenant, actor, request=None):
    before_status = tenant.status
    tenant.status = Tenant.Status.SUSPENDED
    tenant.save(update_fields=['status', 'updated_at'])
    audit_log.record(
        action='tenant.status_changed', actor=actor, tenant_id=tenant.id, obj=tenant,
        before={'status': before_status}, after={'status': tenant.status}, request=request,
    )
    return tenant


def reactivate_tenant(*, tenant, actor, request=None):
    before_status = tenant.status
    tenant.status = Tenant.Status.ACTIVE
    tenant.save(update_fields=['status', 'updated_at'])
    audit_log.record(
        action='tenant.status_changed', actor=actor, tenant_id=tenant.id, obj=tenant,
        before={'status': before_status}, after={'status': tenant.status}, request=request,
    )
    return tenant


@transaction.atomic
def generate_invoice_for_subscription(subscription, *, today=None):
    """Closes out one PER_BED_MONTHLY billing cycle: prices the cycle from
    the bed ledger (`pricing.bed_segments` + `pricing.prorated_charge`),
    writes a `SubscriptionInvoice` + line items (invariant 6 — a list, never
    fixed fields), and either issues it via Razorpay Invoices or — for a
    cycle inside the free allowance — marks it paid immediately with no
    Razorpay call at all (invariant 10: the floor is `PlatformConfig.
    min_billable_amount`, not a literal here).

    Idempotent via the model's `unique_invoice_per_cycle` constraint check
    below: re-running for a cycle that already has an invoice is a no-op,
    not a duplicate charge — see `generate_subscription_invoices`."""
    plan = subscription.plan
    if plan is None or plan.pricing_type != Plan.PricingType.PER_BED_MONTHLY:
        return None
    period_start = subscription.current_period_start
    period_end = subscription.current_period_end
    if period_start is None or period_end is None:
        return None

    today = today or timezone.now().date()
    if today < period_end:
        return None  # cycle hasn't closed yet

    if SubscriptionInvoice.objects.filter(subscription=subscription, period_start=period_start).exists():
        return None  # already generated for this cycle — safe to re-run

    with tenant_context(subscription.tenant_id):
        segments = pricing.bed_segments(subscription.tenant_id, period_start, period_end)
        breakdown = pricing.prorated_charge(plan, segments, period_start, period_end)
        bed_count_start = segments[0][2] if segments else 0
        bed_count_end = segments[-1][2] if segments else 0

        invoice = SubscriptionInvoice.objects.create(
            tenant_id=subscription.tenant_id, subscription=subscription,
            period_start=period_start, period_end=period_end,
            status=SubscriptionInvoice.Status.DRAFT, total_amount=breakdown.total,
            billed_bed_count_start=bed_count_start, billed_bed_count_end=bed_count_end,
        )
        for segment in breakdown.segments:
            for tier_line in segment.tier_lines:
                # Split the segment's prorated amount across its tiers
                # proportionally to each tier's full-cycle share, so every
                # line is an exact, auditable slice and the lines still sum
                # to `total_amount`.
                tier_amount = (
                    (segment.amount * tier_line.subtotal / segment.unprorated_total).quantize(Decimal('0.01'))
                    if segment.unprorated_total else Decimal('0.00')
                )
                SubscriptionInvoiceLine.objects.create(
                    tenant_id=subscription.tenant_id, invoice=invoice,
                    description=_('%(beds)s beds @ ₹%(rate)s (%(from)s–%(to)s)') % {
                        'beds': tier_line.beds_in_tier, 'rate': tier_line.rate_per_bed,
                        'from': segment.start.isoformat(), 'to': segment.end.isoformat(),
                    },
                    quantity=Decimal(tier_line.beds_in_tier), unit_rate=tier_line.rate_per_bed,
                    amount=tier_amount,
                )

        min_billable = PlatformConfig.get().min_billable_amount
        if invoice.total_amount < min_billable:
            invoice.status = SubscriptionInvoice.Status.PAID
            invoice.paid_at = timezone.now()
            invoice.save(update_fields=['status', 'paid_at'])
        else:
            if not subscription.razorpay_customer_id:
                subscription.razorpay_customer_id = razorpay_client.create_razorpay_customer(subscription.tenant)
                subscription.save(update_fields=['razorpay_customer_id', 'updated_at'])
            razorpay_invoice_id, _short_url = razorpay_client.create_razorpay_invoice(
                subscription.razorpay_customer_id, invoice
            )
            invoice.razorpay_invoice_id = razorpay_invoice_id
            invoice.status = SubscriptionInvoice.Status.ISSUED
            invoice.issued_at = timezone.now()
            invoice.save(update_fields=['razorpay_invoice_id', 'status', 'issued_at'])

        # Advance to the next cycle regardless of payment outcome — a
        # failed/expired invoice is reconciled by the webhook + the existing
        # grace-period sweep (`process_payment_grace_periods`), not by
        # holding this cycle open.
        subscription.current_period_start = period_end
        subscription.current_period_end = pricing.next_cycle_end(period_end)
        subscription.save(update_fields=['current_period_start', 'current_period_end', 'updated_at'])

    return invoice


def process_payment_grace_periods():
    """Daily sweep (PRD: 'Payment failure grace period: 5 days before
    account suspension'). Invoked by the `check_subscription_grace_periods`
    management command — see the Module 13 spec's Decisions for why this
    isn't wired to a Celery beat schedule yet."""
    grace_days = PlatformConfig.get().payment_grace_days
    cutoff = timezone.now() - timedelta(days=grace_days)
    overdue = Subscription.objects.filter(
        tenant__status=Tenant.Status.PAYMENT_FAILED, payment_failed_at__lte=cutoff,
    ).select_related('tenant')

    suspended = []
    for subscription in overdue:
        tenant = subscription.tenant
        before_status = tenant.status
        tenant.status = Tenant.Status.SUSPENDED
        tenant.save(update_fields=['status', 'updated_at'])
        audit_log.record(
            action='tenant.status_changed', tenant_id=tenant.id, obj=tenant,
            before={'status': before_status}, after={'status': tenant.status},
        )
        suspended.append(tenant)
    return suspended
