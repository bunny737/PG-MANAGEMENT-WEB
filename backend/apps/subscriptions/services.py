"""Plan-limit enforcement, plan selection, and Razorpay webhook handling
(PRD §4 'Subscription & Pricing Model', Module 20 'Subscription Management').
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.accounts.models import Tenant
from apps.audit import log as audit_log
from apps.core.models import PlatformConfig
from apps.core.tenancy import tenant_context
from apps.properties.models import Property
from apps.residents.models import Resident

from . import razorpay_client
from .models import Subscription, SubscriptionPayment


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
    anytime'). Creates the Razorpay plan (first time only) and a fresh
    Razorpay subscription. Selecting a plan does NOT itself flip the tenant
    to Active — that happens when a webhook confirms the first charge (see
    the Module 13 spec's Decisions)."""
    before_plan = subscription.plan.name if subscription.plan else None

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
    webhook handling for payment success/failure'). Looks the Subscription
    up by its stored `razorpay_subscription_id` since the webhook carries no
    concept of our tenant id."""
    event = payload.get('event', '')
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
    plan_amount = subscription.plan.price_per_month if subscription.plan else 0

    # No authenticated request set the Postgres tenant context (the webhook
    # is deliberately unauthenticated — see RazorpayWebhookView), so this
    # must set it manually before writing the RLS-scoped SubscriptionPayment.
    with tenant_context(tenant.id):
        if event in ('subscription.activated', 'subscription.charged'):
            tenant.status = Tenant.Status.ACTIVE
            subscription.payment_failed_at = None
            today = timezone.now().date()
            subscription.current_period_start = today
            subscription.current_period_end = today + timedelta(days=30)
            SubscriptionPayment.objects.create(
                tenant_id=tenant.id, subscription=subscription,
                razorpay_payment_id=payment_entity.get('id', ''), amount=plan_amount,
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
                razorpay_payment_id=payment_entity.get('id', ''), amount=plan_amount,
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
