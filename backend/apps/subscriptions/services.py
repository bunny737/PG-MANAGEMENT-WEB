"""Plan-limit enforcement, plan selection, and Razorpay webhook handling
(PRD §4 'Subscription & Pricing Model', Module 20 'Subscription Management').
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import logging

from django.db import connection, transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from decimal import Decimal, ROUND_HALF_UP

from apps.accounts.models import Tenant
from apps.audit import log as audit_log
from apps.core.models import PlatformConfig
from apps.core.tenancy import tenant_context
from apps.properties.models import Bed, Property
from apps.residents.models import Resident

from . import pricing, razorpay_client
from .models import (
    Plan,
    RazorpaySubscription,
    Subscription,
    SubscriptionInvoice,
    SubscriptionInvoiceLine,
    SubscriptionPayment,
)


logger = logging.getLogger(__name__)


def get_or_create_subscription(tenant):
    """Every tenant gets a blank Subscription at signup; lazily create one
    for any that don't (older fixtures, data-fix scenarios) rather than
    500ing — mirrors Module 02's PropertySettings lazy-creation."""
    subscription, _created = Subscription.objects.get_or_create(tenant=tenant)
    return subscription


def _subscription_for_limit_check(tenant_id):
    """The tenant's Subscription, row-locked when the caller is inside a
    transaction so concurrent creates serialize on it (the count-then-create
    check below is otherwise a race — the PRD's 'hard block' could be sailed
    past by parallel requests). Outside a transaction (direct calls, tests)
    it degrades to an unlocked read."""
    qs = Subscription.objects.filter(tenant_id=tenant_id)
    if connection.in_atomic_block:
        # Lock the bare row; plan/tenant load lazily once the lock is held. A
        # joined read would be evaluated against pre-commit plan rows when the
        # lock waits on a concurrent plan change, so its limits could be stale.
        return qs.select_for_update().first()
    return qs.select_related('plan', 'tenant').first()


def check_property_limit(tenant_id):
    """Hard block (PRD: 'Hard block when either limit is reached'). A
    tenant with no Subscription row, no plan, or an unlimited plan has
    nothing to enforce — intentionally fail-open, so limits only bite once
    a Super Admin has actually configured a plan."""
    subscription = _subscription_for_limit_check(tenant_id)
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


def check_bed_limit(tenant_id, adding=1):
    """Hard block on total provisioned beds across the tenant (same basis as
    `get_total_beds`). Fail-open like the other limits."""
    subscription = _subscription_for_limit_check(tenant_id)
    if subscription is None:
        return
    max_beds = subscription.effective_max_beds()
    if max_beds is None:
        return
    if get_total_beds(tenant_id) + adding > max_beds:
        raise ValidationError(
            {'detail': _('Your plan allows a maximum of %(max)s beds. Upgrade to add more.')
             % {'max': max_beds}},
            code='bed_limit_reached',
        )


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
    bed_count = (
        subscription.annotated_bed_count
        if hasattr(subscription, 'annotated_bed_count')
        else get_total_beds(subscription.tenant_id)
    )
    breakdown = pricing.monthly_charge(plan, bed_count)
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
    subscription = _subscription_for_limit_check(property.tenant_id)
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


# Razorpay subscription statuses that mean "will never charge again".
RAZORPAY_FINISHED_STATUSES = ('cancelled', 'completed', 'expired')
# A failing cancellation is audited on these attempts only, so a long outage doesn't flood the log.
CANCEL_AUDIT_ATTEMPTS = (1, 10, 50)
# How long a CANCELLING claim is respected before another sweep assumes its worker died.
CANCEL_CLAIM_TIMEOUT = timedelta(minutes=15)


def _retire_current_subscription(subscription):
    """The tenant's live Razorpay subscription is being replaced: mark its ledger row
    REPLACED so it keeps being cancelled until Razorpay confirms. A subscription that
    predates the ledger gets a row here."""
    current_id = subscription.razorpay_subscription_id
    if not current_id:
        return
    row = RazorpaySubscription.objects.filter(razorpay_subscription_id=current_id).first()
    if row is None:
        if subscription.plan_id:
            RazorpaySubscription.objects.create(
                subscription=subscription, plan_id=subscription.plan_id,
                razorpay_subscription_id=current_id, state=RazorpaySubscription.State.REPLACED,
            )
    elif row.state != RazorpaySubscription.State.CANCELLED:
        row.state = RazorpaySubscription.State.REPLACED
        row.save(update_fields=['state', 'updated_at'])


def _abandon_pending_subscriptions(subscription):
    """A newer plan choice supersedes any unpaid ones. They stay in the ledger: they
    are cancelled, but a payment that still lands on one is honoured (rule 26)."""
    RazorpaySubscription.objects.filter(
        subscription=subscription, state=RazorpaySubscription.State.PENDING,
    ).update(state=RazorpaySubscription.State.ABANDONED, updated_at=timezone.now())


def _claim_for_cancel(row):
    """Atomically move a REPLACED/ABANDONED row to CANCELLING before touching Razorpay,
    and return the state it came from (None if someone else got there first).

    This is the guard against cancelling a subscription a webhook is promoting. A
    cancelled Razorpay subscription can never restart, so once we may have cancelled
    it, no webhook may promote it to the tenant's live subscription; webhooks only
    promote PENDING/ABANDONED rows, so claiming (a single conditional UPDATE, atomic
    against the webhook's row lock) decides the race one way or the other. A claim
    left by a worker that died is taken over after CANCEL_CLAIM_TIMEOUT."""
    State = RazorpaySubscription.State
    now = timezone.now()
    if RazorpaySubscription.objects.filter(pk=row.pk, state__in=(State.REPLACED, State.ABANDONED)).update(
        state=State.CANCELLING, cancel_from=F('state'), updated_at=now,
    ):
        return RazorpaySubscription.objects.values_list('cancel_from', flat=True).get(pk=row.pk)
    if RazorpaySubscription.objects.filter(
        pk=row.pk, state=State.CANCELLING, updated_at__lt=now - CANCEL_CLAIM_TIMEOUT,
    ).update(updated_at=now):
        return RazorpaySubscription.objects.values_list('cancel_from', flat=True).get(pk=row.pk) or State.ABANDONED
    return None


def _cancel_ledger_row(row):
    """One cancellation attempt; returns True (cancelled), False (failed, will retry) or
    None (not ours to cancel: a webhook or another worker got the row first).

    Success — or Razorpay reporting the subscription already finished — closes the row;
    any other failure puts it back for the next sweep. Network calls are made with no
    database lock held, which is safe only because the row is CANCELLING meanwhile."""
    State = RazorpaySubscription.State
    came_from = _claim_for_cancel(row)
    if came_from is None:
        return None
    now = timezone.now()
    try:
        razorpay_client.cancel_razorpay_subscription(row.razorpay_subscription_id)
        finished = True
    except Exception as exc:  # noqa: BLE001 - any SDK/network failure is a retry, not a crash
        finished = False
        try:
            finished = razorpay_client.fetch_razorpay_subscription_status(
                row.razorpay_subscription_id,
            ) in RAZORPAY_FINISHED_STATUSES
        except Exception:  # noqa: BLE001 - status unknown: treat the cancel as failed
            pass
        if not finished:
            logger.warning(
                'Could not cancel Razorpay subscription %s; will retry', row.razorpay_subscription_id, exc_info=True,
            )
            RazorpaySubscription.objects.filter(pk=row.pk, state=State.CANCELLING).update(
                state=came_from, cancel_attempts=F('cancel_attempts') + 1, last_cancel_error=str(exc)[:1000],
                last_cancel_attempt_at=now, updated_at=now,
            )
            attempts = RazorpaySubscription.objects.values_list('cancel_attempts', flat=True).get(pk=row.pk)
            if attempts in CANCEL_AUDIT_ATTEMPTS:
                audit_log.record(
                    action='subscription.razorpay_cancel_failed', tenant_id=row.subscription.tenant_id,
                    after={'razorpay_subscription_id': row.razorpay_subscription_id, 'attempts': attempts},
                )
            return False
    if RazorpaySubscription.objects.filter(pk=row.pk, state=State.CANCELLING).update(
        state=State.CANCELLED, cancelled_at=now, updated_at=now,
    ):
        return True
    # Nothing was CANCELLING any more. Only Razorpay's own "cancelled" webhook may have
    # closed it first; anything else means the ledger no longer matches Razorpay (the
    # subscription is cancelled there), so say so rather than reporting success.
    state = RazorpaySubscription.objects.values_list('state', flat=True).get(pk=row.pk)
    if state == State.CANCELLED:
        return True
    logger.error('Ledger conflict: %s cancelled at Razorpay but is %s here', row.razorpay_subscription_id, state)
    audit_log.record(
        action='subscription.cancel_conflict', tenant_id=row.subscription.tenant_id,
        after={'razorpay_subscription_id': row.razorpay_subscription_id, 'ledger_state': state},
    )
    return False


def process_razorpay_cancellations(subscription_id=None):
    """Cancels every replaced/abandoned Razorpay subscription (optionally only one
    tenant's) that Razorpay hasn't yet confirmed finished, and takes over claims whose
    worker died. Run right after a plan change commits, and every few minutes by a
    periodic task, so a Razorpay outage delays the cancellation but can never lose it."""
    State = RazorpaySubscription.State
    rows = RazorpaySubscription.objects.filter(
        Q(state__in=(State.REPLACED, State.ABANDONED))
        | Q(state=State.CANCELLING, updated_at__lt=timezone.now() - CANCEL_CLAIM_TIMEOUT),
    ).select_related('subscription')
    if subscription_id is not None:
        rows = rows.filter(subscription_id=subscription_id)
    outcome = {'cancelled': 0, 'failed': 0}
    for row in rows.order_by('created_at'):
        result = _cancel_ledger_row(row)
        if result is not None:
            outcome['cancelled' if result else 'failed'] += 1
    return outcome


@transaction.atomic
def select_plan(*, subscription, plan, actor, request=None):
    """Owner selects/changes a plan (PRD: 'Plan upgrade/downgrade available
    anytime'). Branches on `plan.pricing_type`:

    FLAT_MONTHLY — nothing about the tenant's entitlements changes yet. Creates the
    Razorpay plan (first time only) and a fresh Razorpay subscription, and records
    them as `pending_plan` / `pending_razorpay_subscription_id`. The tenant keeps its
    current plan and limits until Razorpay's webhook confirms the first charge, which
    promotes the pending plan and cancels the old Razorpay subscription
    (`_promote_ledger_row`). So a plan can't be had without paying, and a paying
    tenant is never billed twice.

    PER_BED_MONTHLY — there is no advance charge to confirm (billing is in
    arrears, at cycle close — see `generate_invoice_for_subscription`), so
    plan selection activates the tenant immediately once the Razorpay
    customer exists. The flat Razorpay subscription it replaces is queued for
    cancellation (see `process_razorpay_cancellations`), otherwise it would keep
    charging for a plan they no longer have."""
    # Same lock as the limit checks, so a bed create can't interleave with the
    # bed check below; it runs before any Razorpay side effect.
    subscription = Subscription.objects.select_for_update().get(pk=subscription.pk)
    # Then the target plan, re-read under its own lock (order: Subscription ->
    # Plan, as in PlanViewSet): the caller's instance is stale if an admin has
    # since repriced, capped or retired it, and the lock stops them doing so
    # between the Razorpay call below and our commit.
    plan = Plan.objects.select_for_update().get(pk=plan.pk)
    if not plan.is_active:
        raise ValidationError(
            {'plan': [_('This plan is no longer available.')]}, code='plan_inactive',
        )
    tenant = subscription.tenant
    if tenant.status == Tenant.Status.ACTIVE and subscription.plan_id == plan.pk:
        raise ValidationError({'detail': _('You are already on this plan.')}, code='plan_unchanged')
    max_beds = subscription.max_beds_on(plan)
    if max_beds is not None:
        bed_count = get_total_beds(subscription.tenant_id)
        if bed_count > max_beds:
            raise ValidationError(
                {'detail': _(
                    'You have %(count)s beds, but this plan allows %(max)s. '
                    'Remove beds or choose a larger plan.'
                ) % {'count': bed_count, 'max': max_beds}},
                code='plan_bed_limit_exceeded',
            )
    before_plan = subscription.plan.name if subscription.plan else None

    if plan.pricing_type == Plan.PricingType.PER_BED_MONTHLY:
        # Written locally first, in this transaction; the Razorpay cancellations follow
        # after commit and are retried until confirmed (never done before the writes: a
        # remote cancel can't be rolled back if a later local write then fails).
        _retire_current_subscription(subscription)
        _abandon_pending_subscriptions(subscription)
        subscription.plan = plan
        subscription.pending_plan = None
        subscription.pending_razorpay_subscription_id = ''
        if not subscription.razorpay_customer_id:
            subscription.razorpay_customer_id = razorpay_client.create_razorpay_customer(tenant)
        subscription.razorpay_subscription_id = ''
        today = timezone.now().date()
        subscription.current_period_start = today
        subscription.current_period_end = pricing.next_cycle_end(today)
        subscription.payment_failed_at = None
        subscription.save(update_fields=[
            'plan', 'pending_plan', 'pending_razorpay_subscription_id', 'razorpay_customer_id',
            'razorpay_subscription_id', 'current_period_start', 'current_period_end',
            'payment_failed_at', 'updated_at',
        ])
        if tenant.status != Tenant.Status.ACTIVE:
            before_status = tenant.status
            tenant.status = Tenant.Status.ACTIVE
            tenant.save(update_fields=['status', 'updated_at'])
            audit_log.record(
                action='tenant.status_changed', actor=actor, tenant_id=tenant.id, obj=tenant,
                before={'status': before_status}, after={'status': tenant.status}, request=request,
            )
        after = {'plan': plan.name}
    else:
        if not plan.razorpay_plan_id:
            plan.razorpay_plan_id = razorpay_client.create_razorpay_plan(plan)
            plan.save(update_fields=['razorpay_plan_id', 'updated_at'])

        new_id = razorpay_client.create_razorpay_subscription(plan)
        # An earlier unpaid choice is cancelled but kept: if its payment lands anyway,
        # the webhook recognises it and honours it.
        _abandon_pending_subscriptions(subscription)
        RazorpaySubscription.objects.create(
            subscription=subscription, plan=plan, razorpay_subscription_id=new_id,
            state=RazorpaySubscription.State.PENDING,
        )
        subscription.pending_plan = plan
        subscription.pending_razorpay_subscription_id = new_id
        subscription.save(update_fields=['pending_plan', 'pending_razorpay_subscription_id', 'updated_at'])
        after = {'plan': before_plan, 'pending_plan': plan.name}

    transaction.on_commit(lambda: process_razorpay_cancellations(subscription_id=subscription.pk))
    audit_log.record(
        action='subscription.plan_selected', actor=actor, tenant_id=subscription.tenant_id,
        obj=subscription, before={'plan': before_plan}, after=after, request=request,
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


def _promote_ledger_row(subscription, row):
    """Razorpay confirmed a first charge on `row` (a PENDING, or an ABANDONED one that was
    paid anyway): it becomes the tenant's plan and live subscription, and the one it
    replaces is queued for cancellation (after commit). Caller holds the subscription
    row lock.

    The tenant may have grown past the new plan's bed cap while payment was pending.
    They paid for this plan, so it is applied anyway: existing beds are never removed,
    and further adds are simply blocked until they fit (audited)."""
    new_plan = row.plan
    previous_plan = subscription.plan
    _retire_current_subscription(subscription)
    subscription.plan = new_plan
    subscription.razorpay_subscription_id = row.razorpay_subscription_id
    update_fields = ['plan', 'razorpay_subscription_id', 'updated_at']
    if subscription.pending_razorpay_subscription_id == row.razorpay_subscription_id:
        subscription.pending_plan = None
        subscription.pending_razorpay_subscription_id = ''
        update_fields += ['pending_plan', 'pending_razorpay_subscription_id']
    subscription.save(update_fields=update_fields)
    row.state = RazorpaySubscription.State.CURRENT
    row.save(update_fields=['state', 'updated_at'])
    audit_log.record(
        action='subscription.plan_changed', tenant_id=subscription.tenant_id, obj=subscription,
        before={'plan': previous_plan.name if previous_plan else None}, after={'plan': new_plan.name},
    )
    max_beds = subscription.max_beds_on(new_plan)
    if max_beds is not None and get_total_beds(subscription.tenant_id) > max_beds:
        audit_log.record(
            action='subscription.promoted_over_bed_limit', tenant_id=subscription.tenant_id,
            obj=subscription, after={'plan': new_plan.name, 'max_beds': max_beds},
        )
    transaction.on_commit(lambda: process_razorpay_cancellations(subscription_id=subscription.pk))


def _reconcile_non_current_event(event, subscription, row, *, razorpay_payment_id, charged_amount, payload):
    """An event for a Razorpay subscription that is not the tenant's live one. Returns
    True if the event was fully handled here, False if `row` was just promoted and the
    caller should now treat it as the live subscription's first charge.

    Nothing here ever changes the tenant's status for a subscription it has moved on
    from; what it must never do is let a successful payment vanish."""
    State = RazorpaySubscription.State
    charge = event in ('subscription.activated', 'subscription.charged')
    if row is None or row.subscription_id != subscription.pk:
        return True  # not one of ours
    already_recorded = bool(razorpay_payment_id) and SubscriptionPayment.objects.filter(
        razorpay_payment_id=razorpay_payment_id,
    ).exists()
    if charge and already_recorded:
        # A replay of a charge we already decided on. That decision stands: a payment
        # flagged for refund while the row was CANCELLING must not promote it just
        # because a failed cancel has since returned the row to ABANDONED.
        return True
    if charge and row.state in (State.PENDING, State.ABANDONED):
        _promote_ledger_row(subscription, row)
        return False
    if charge:
        # A charge on a subscription we replaced (a renewal that raced the cancel) or
        # already cancelled: no plan to honour. Keep the money visible and flag it.
        if not already_recorded:
            SubscriptionPayment.objects.create(
                tenant_id=subscription.tenant_id, subscription=subscription,
                razorpay_payment_id=razorpay_payment_id, amount=charged_amount,
                status=SubscriptionPayment.Status.SUCCESS, paid_at=timezone.now(), raw_payload=payload,
            )
            audit_log.record(
                action='subscription.payment_needs_refund', tenant_id=subscription.tenant_id, obj=subscription,
                after={
                    'razorpay_subscription_id': row.razorpay_subscription_id,
                    'razorpay_payment_id': razorpay_payment_id, 'amount': str(charged_amount),
                    'subscription_state': row.state,
                },
            )
        return True
    if event in ('subscription.cancelled', 'subscription.halted') and row.state != State.CANCELLED:
        # Razorpay confirms it is finished: the retry loop's job is done.
        row.state = State.CANCELLED
        row.cancelled_at = timezone.now()
        row.save(update_fields=['state', 'cancelled_at', 'updated_at'])
        if subscription.pending_razorpay_subscription_id == row.razorpay_subscription_id:
            subscription.pending_plan = None
            subscription.pending_razorpay_subscription_id = ''
            subscription.save(update_fields=['pending_plan', 'pending_razorpay_subscription_id', 'updated_at'])
    return True  # e.g. payment.failed on an unpaid or superseded subscription: nothing to do


def _handle_subscription_webhook(event, payload):
    """FLAT_MONTHLY: looks the Subscription up by its stored
    `razorpay_subscription_id` since the webhook carries no concept of our
    tenant id."""
    entity = payload.get('payload', {}).get('subscription', {}).get('entity', {})
    razorpay_subscription_id = entity.get('id', '')

    if not razorpay_subscription_id:
        return
    # Any Razorpay subscription we ever created for a tenant is in the ledger, in
    # whatever state it has reached, so an event for one we have since moved on from
    # (an abandoned plan choice, a replaced subscription) is still recognised. The
    # Subscription fallback covers rows that predate it.
    ledger_row = (
        RazorpaySubscription.objects.filter(razorpay_subscription_id=razorpay_subscription_id)
        .select_related('plan').first()
    )
    subscription = (
        Subscription.objects.filter(pk=ledger_row.subscription_id).select_related('tenant', 'plan').first()
        if ledger_row else
        Subscription.objects.filter(
            Q(razorpay_subscription_id=razorpay_subscription_id)
            | Q(pending_razorpay_subscription_id=razorpay_subscription_id)
        ).select_related('tenant', 'plan').first()
    )
    if subscription is None:
        return  # unknown subscription — nothing to reconcile

    payment_entity = payload.get('payload', {}).get('payment', {}).get('entity', {})
    razorpay_payment_id = payment_entity.get('id', '')
    # The amount Razorpay actually charged (paise), not the plan's list price —
    # the two used to silently diverge whenever a payment carried an adjusted amount.
    raw_amount = payment_entity.get('amount')
    priced_plan = ledger_row.plan if ledger_row else subscription.plan
    charged_amount = (
        Decimal(raw_amount) / 100 if raw_amount is not None
        else (priced_plan.price_per_month if priced_plan and priced_plan.price_per_month else Decimal('0'))
    )

    # No authenticated request set the Postgres tenant context (the webhook
    # is deliberately unauthenticated — see RazorpayWebhookView), so this
    # must set it manually before writing the RLS-scoped SubscriptionPayment.
    with tenant_context(subscription.tenant_id), transaction.atomic():
        # Lock the subscription for the rest of the handler so a replayed or
        # concurrently-delivered webhook for the same subscription serializes
        # behind this one — the idempotency checks below then can't race.
        subscription = (
            Subscription.objects.select_for_update(of=('self',))
            .select_related('tenant', 'plan')
            .get(pk=subscription.pk)
        )
        tenant = subscription.tenant
        before_status = tenant.status  # read under the lock (was a stale pre-lock read)

        # Re-read under the lock: a plan change may have moved the live id since the
        # unlocked lookup above. Only the live subscription drives the tenant's status;
        # an event for any other one is reconciled against the ledger instead.
        ledger_row = (
            RazorpaySubscription.objects.select_for_update()
            .filter(razorpay_subscription_id=razorpay_subscription_id).first()
        )
        if subscription.razorpay_subscription_id != razorpay_subscription_id:
            if _reconcile_non_current_event(
                event, subscription, ledger_row, razorpay_payment_id=razorpay_payment_id,
                charged_amount=charged_amount, payload=payload,
            ):
                return
            # Promoted: it is now the live subscription, and this is its first charge.

        if event in ('subscription.activated', 'subscription.charged'):
            # Idempotency: a replayed webhook must not double-record the same charge.
            if razorpay_payment_id:
                if SubscriptionPayment.objects.filter(
                    razorpay_payment_id=razorpay_payment_id
                ).exists():
                    return
            else:
                today = timezone.now().date()
                if SubscriptionPayment.objects.filter(
                    subscription=subscription, status=SubscriptionPayment.Status.SUCCESS, created_at__date=today
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
            if ledger_row is not None:
                ledger_row.state = RazorpaySubscription.State.CANCELLED
                ledger_row.cancelled_at = timezone.now()
                ledger_row.save(update_fields=['state', 'cancelled_at', 'updated_at'])
        elif event == 'payment.failed':
            # Idempotency: a replayed failure webhook must not double-record it
            # (also avoids tripping the unique_razorpay_payment_id constraint).
            if razorpay_payment_id and SubscriptionPayment.objects.filter(
                razorpay_payment_id=razorpay_payment_id
            ).exists():
                return
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

    payment_entity = payload.get('payload', {}).get('payment', {}).get('entity', {})
    razorpay_payment_id = payment_entity.get('id', '')

    with tenant_context(invoice.subscription.tenant_id), transaction.atomic():
        # Lock the invoice for the rest of the handler so a replayed or
        # concurrently-delivered webhook for the same invoice serializes behind
        # this one — the status-based idempotency checks below can't race.
        invoice = (
            SubscriptionInvoice.objects.select_for_update(of=('self',))
            .select_related('subscription__tenant')
            .get(pk=invoice.pk)
        )
        subscription = invoice.subscription
        tenant = subscription.tenant
        before_status = tenant.status
        if event == 'invoice.paid':
            if invoice.status == SubscriptionInvoice.Status.PAID:
                return  # already processed payment for this invoice
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
            if invoice.status == SubscriptionInvoice.Status.FAILED:
                return  # already processed this failure
            if razorpay_payment_id and SubscriptionPayment.objects.filter(
                razorpay_payment_id=razorpay_payment_id
            ).exists():
                return
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


def override_limits(*, subscription, max_properties_override, max_residents_override,
                    max_beds_override, actor, request=None):
    """Super Admin manual override 'for a specific tenant if needed (e.g.
    grace period, enterprise negotiation)' (PRD §4)."""
    before = {
        'max_properties_override': subscription.max_properties_override,
        'max_residents_override': subscription.max_residents_override,
        'max_beds_override': subscription.max_beds_override,
    }
    subscription.max_properties_override = max_properties_override
    subscription.max_residents_override = max_residents_override
    subscription.max_beds_override = max_beds_override
    subscription.save(update_fields=[
        'max_properties_override', 'max_residents_override', 'max_beds_override', 'updated_at',
    ])
    audit_log.record(
        action='subscription.limits_overridden', actor=actor, tenant_id=subscription.tenant_id,
        obj=subscription, before=before,
        after={
            'max_properties_override': max_properties_override,
            'max_residents_override': max_residents_override,
            'max_beds_override': max_beds_override,
        },
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

    if not subscription.razorpay_customer_id:
        subscription.razorpay_customer_id = razorpay_client.create_razorpay_customer(subscription.tenant)
        subscription.save(update_fields=['razorpay_customer_id', 'updated_at'])

    with tenant_context(subscription.tenant_id):
        if SubscriptionInvoice.objects.filter(subscription=subscription, period_start=period_start).exists():
            return None  # already generated for this cycle — safe to re-run

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
                    (Decimal(segment.amount) * tier_line.subtotal / segment.unprorated_total).quantize(
                        Decimal('0.01'), rounding=ROUND_HALF_UP
                    )
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
