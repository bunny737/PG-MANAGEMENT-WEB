"""Plan-limit enforcement, plan selection, and Razorpay webhook handling
(PRD §4 'Subscription & Pricing Model', Module 20 'Subscription Management').
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import hashlib
import json
import logging
import uuid

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

from . import pricing, razorpay_client, webhook_policy
from .models import (
    Plan,
    RazorpaySubscription,
    RazorpayWebhookEvent,
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
        if not subscription.razorpay_customer_id:
            subscription.razorpay_customer_id = razorpay_client.create_razorpay_customer(tenant)
        # Leaving another per-bed plan: its arrears are invoiced on that plan
        # before the plan and period below overwrite what prices them.
        close_per_bed_period(subscription)
        subscription.plan = plan
        subscription.pending_plan = None
        subscription.pending_razorpay_subscription_id = ''
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


def _fallback_event_id(payload):
    """Razorpay sends a unique `X-Razorpay-Event-Id` (the same on every retry). Without it, the body itself
    identifies a redelivery."""
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
    return 'body:' + hashlib.sha256(canonical.encode()).hexdigest()


def _event_time(payload):
    """The event's own occurrence time (the payload's top-level `created_at`), or None."""
    raw = payload.get('created_at')
    if isinstance(raw, bool) or raw in (None, ''):
        return None
    try:
        seconds = int(raw)
        return datetime.fromtimestamp(seconds, tz=dt_timezone.utc) if seconds > 0 else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def handle_webhook_event(payload, event_id=None):
    """Processes a Razorpay webhook payload (PRD Module 20: 'Razorpay
    webhook handling for payment success/failure'). Two independent event
    families, because FLAT_MONTHLY and PER_BED_MONTHLY use different
    Razorpay primitives (Phase 0 spike: Add-ons are deprecated, so arrears
    amounts are billed via Invoices, not Subscriptions):

    - `subscription.*` / `payment.failed` — advance billing, keyed by `razorpay_subscription_id`.
      Applied by `webhook_policy`: terminal and manual states first, then the newest event by
      occurrence time, not delivery order.
    - `invoice.*` — arrears billing, keyed by `razorpay_invoice_id` on
      `SubscriptionInvoice` (see `generate_invoice_for_subscription`).

    Every valid event is stored (`RazorpayWebhookEvent`) whatever its outcome, and a redelivery of the
    same `event_id` does nothing."""
    event = payload.get('event', '')
    entities = payload.get('payload', {})
    subscription_entity = entities.get('subscription', {}).get('entity', {})
    with transaction.atomic():
        record, created = RazorpayWebhookEvent.objects.get_or_create(
            event_id=event_id or _fallback_event_id(payload),
            defaults={
                'event_type': event[:60], 'payload': payload, 'occurred_at': _event_time(payload),
                'razorpay_subscription_id': subscription_entity.get('id', '')[:100],
            },
        )
        if not created:
            return  # a redelivery of an event we already processed
        if event.startswith('invoice.'):
            _handle_invoice_webhook(event, payload)
            outcome, detail, tenant_id = RazorpayWebhookEvent.Outcome.APPLIED, 'invoice event', None
        else:
            outcome, detail, tenant_id = _handle_subscription_webhook(event, payload, record.event_id)
        record.outcome, record.detail, record.tenant_id = outcome, detail[:500], tenant_id
        record.save(update_fields=['outcome', 'detail', 'tenant_id'])


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
    # A per-bed plan bills in arrears: invoice what it accrued before the flat
    # plan replaces it, while the old plan and period can still price it.
    close_per_bed_period(subscription)
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


def _live_ledger_row(subscription, razorpay_subscription_id):
    """The ledger row of the tenant's live Razorpay subscription, created if an older row predates the
    ledger (it carries the ordering state, so it must exist). Caller holds the subscription lock."""
    row = (
        RazorpaySubscription.objects.select_for_update()
        .filter(razorpay_subscription_id=razorpay_subscription_id).first()
    )
    if row is None and subscription.plan_id:
        row = RazorpaySubscription.objects.create(
            subscription=subscription, plan=subscription.plan,
            razorpay_subscription_id=razorpay_subscription_id, state=RazorpaySubscription.State.CURRENT,
        )
    return row


def _verify_with_razorpay(decision, razorpay_subscription_id, facts):
    """Settles a Decision.VERIFY by asking Razorpay for the subscription's real status. Returns
    (decision, remote_status). It never grants access it cannot confirm: an unreachable or unconfigured
    Razorpay leaves the decision unresolved (VERIFY) and access unchanged."""
    try:
        remote = razorpay_client.fetch_razorpay_subscription_status(razorpay_subscription_id)
    except Exception:
        logger.exception('Could not verify subscription %s with Razorpay', razorpay_subscription_id)
        return decision, None
    if remote is None:
        return decision, None
    target = webhook_policy.tenant_status_for_remote(remote)
    Action = webhook_policy.Action
    if decision.reason == 'charged_after_halt':
        if target == Tenant.Status.ACTIVE:
            return webhook_policy.Decision(Action.APPLY, Tenant.Status.ACTIVE, f'razorpay confirms {remote}'), remote
        return webhook_policy.Decision(
            Action.DECLINED, reason=f'razorpay reports {remote}; stays suspended', flag_payment=True), remote
    # missing_timestamp: believe Razorpay's current state rather than the undated snapshot.
    if target is None or target == facts.tenant_status:
        return webhook_policy.Decision(Action.NO_CHANGE, reason=f'razorpay reports {remote}'), remote
    return webhook_policy.Decision(Action.APPLY, target, f'razorpay reports {remote}'), remote


def _record_event_payment(kind, subscription, razorpay_payment_id, amount, payload):
    """Keeps the money visible whatever the event's ordering outcome. Returns True if a new row was written.
    Only charge and payment-failure events describe a payment attempt; a halted/cancelled/resumed payload may
    still carry a payment entity, which is not a new payment."""
    if kind not in (*webhook_policy.CHARGE_KINDS, 'payment_failed'):
        return False
    if razorpay_payment_id:
        if SubscriptionPayment.objects.filter(razorpay_payment_id=razorpay_payment_id).exists():
            return False
    elif kind in webhook_policy.CHARGE_KINDS:
        if SubscriptionPayment.objects.filter(
            subscription=subscription, status=SubscriptionPayment.Status.SUCCESS,
            created_at__date=timezone.now().date(),
        ).exists():
            return False
    succeeded = kind in webhook_policy.CHARGE_KINDS
    SubscriptionPayment.objects.create(
        tenant_id=subscription.tenant_id, subscription=subscription,
        razorpay_payment_id=razorpay_payment_id, amount=amount,
        status=SubscriptionPayment.Status.SUCCESS if succeeded else SubscriptionPayment.Status.FAILED,
        paid_at=timezone.now() if succeeded else None, raw_payload=payload,
    )
    return True


_OUTCOME_BY_ACTION = {
    webhook_policy.Action.APPLY: RazorpayWebhookEvent.Outcome.APPLIED,
    webhook_policy.Action.NO_CHANGE: RazorpayWebhookEvent.Outcome.APPLIED,
    webhook_policy.Action.STALE: RazorpayWebhookEvent.Outcome.STALE_IGNORED,
    webhook_policy.Action.TERMINAL: RazorpayWebhookEvent.Outcome.TERMINAL_IGNORED,
    webhook_policy.Action.MANUAL_HOLD: RazorpayWebhookEvent.Outcome.MANUAL_HOLD_IGNORED,
    webhook_policy.Action.NOT_RECOVERY: RazorpayWebhookEvent.Outcome.NOT_RECOVERY_IGNORED,
    webhook_policy.Action.VERIFY: RazorpayWebhookEvent.Outcome.NEEDS_VERIFICATION,
    webhook_policy.Action.DECLINED: RazorpayWebhookEvent.Outcome.VERIFICATION_DECLINED,
}


def _handle_subscription_webhook(event, payload, event_id):
    """FLAT_MONTHLY: looks the Subscription up by its stored `razorpay_subscription_id` since the
    webhook carries no concept of our tenant id. Returns (outcome, detail, tenant_id) for the stored
    `RazorpayWebhookEvent`.

    Which events may change the tenant, and in what order, is `webhook_policy`'s decision; this carries
    it out, keeps every captured payment on record, flags payments access must not honour, and audits
    what it ignored."""
    Outcome = RazorpayWebhookEvent.Outcome
    entity = payload.get('payload', {}).get('subscription', {}).get('entity', {})
    razorpay_subscription_id = entity.get('id', '')

    if not razorpay_subscription_id:
        return Outcome.UNKNOWN_SUBSCRIPTION, 'no subscription id in the payload', None
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
        return Outcome.UNKNOWN_SUBSCRIPTION, 'unknown subscription — nothing to reconcile', None

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
    kind = webhook_policy.KIND_BY_EVENT.get(event)
    occurred_at = _event_time(payload)
    if occurred_at is None and not razorpay_client.is_configured():
        # Local stub (dev/test) has no Razorpay to ask: fall back to arrival order. Production is always configured.
        occurred_at = timezone.now()

    # No authenticated request set the Postgres tenant context (the webhook
    # is deliberately unauthenticated — see RazorpayWebhookView), so this
    # must set it manually before writing the RLS-scoped SubscriptionPayment.
    with tenant_context(subscription.tenant_id), transaction.atomic():
        # Lock the subscription for the rest of the handler so a replayed or
        # concurrently-delivered webhook for the same subscription serializes
        # behind this one — the ordering checks below then can't race.
        subscription = (
            Subscription.objects.select_for_update(of=('self',))
            .select_related('tenant', 'plan')
            .get(pk=subscription.pk)
        )
        tenant = subscription.tenant
        before_status = tenant.status  # read under the lock (was a stale pre-lock read)
        tenant_id = tenant.id

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
                return Outcome.NON_CURRENT, 'not the tenant\'s live subscription', tenant_id
            # Promoted: it is now the live subscription, and this is its first charge.
        else:
            ledger_row = _live_ledger_row(subscription, razorpay_subscription_id) or ledger_row

        if kind is None:
            return Outcome.UNHANDLED, f'{event} is not acted on', tenant_id

        Action = webhook_policy.Action
        facts = webhook_policy.Facts(
            tenant_status=tenant.status,
            row_cancelled=bool(ledger_row and ledger_row.state == RazorpaySubscription.State.CANCELLED),
            manual_hold=subscription.status_hold == Subscription.STATUS_HOLD_MANUAL,
            activated_before=bool(ledger_row and ledger_row.activated_at),
            last=webhook_policy.LastEvent(
                ledger_row.last_status_event_at, ledger_row.last_status_event_type, ledger_row.last_status_event_id,
            ) if ledger_row else webhook_policy.LastEvent(),
        )
        decision = webhook_policy.decide(kind, occurred_at, facts)
        remote_status = None
        if decision.action == Action.VERIFY:
            decision, remote_status = _verify_with_razorpay(decision, razorpay_subscription_id, facts)
            if decision.action == Action.APPLY and occurred_at is None:
                occurred_at = timezone.now()   # authoritative as of now

        # The money is always recorded, however the event's ordering turned out.
        new_payment = _record_event_payment(kind, subscription, razorpay_payment_id, charged_amount, payload)

        if kind == 'cancelled' and ledger_row and ledger_row.state != RazorpaySubscription.State.CANCELLED:
            # Terminal at Razorpay whatever the tenant's status: the ledger must say so.
            ledger_row.state = RazorpaySubscription.State.CANCELLED
            ledger_row.cancelled_at = timezone.now()
            ledger_row.save(update_fields=['state', 'cancelled_at', 'updated_at'])

        if decision.action == Action.APPLY:
            _apply_status_event(
                decision, kind, event, event_id, occurred_at, subscription, tenant, ledger_row, entity)
            if tenant.status != before_status:
                audit_log.record(
                    action='tenant.status_changed', tenant_id=tenant.id, obj=tenant,
                    before={'status': before_status}, after={'status': tenant.status},
                )
        elif decision.action != Action.NO_CHANGE:
            audit_log.record(
                action=('subscription.stale_event_ignored' if decision.action == Action.STALE
                        else 'subscription.event_needs_verification' if decision.action == Action.VERIFY
                        else 'subscription.event_ignored'),
                tenant_id=tenant.id, obj=subscription,
                after={
                    'event': event, 'event_id': event_id, 'outcome': decision.action, 'reason': decision.reason,
                    'occurred_at': occurred_at.isoformat() if occurred_at else None,
                    'last_applied_at': facts.last.at.isoformat() if facts.last.at else None,
                    'last_applied_event': facts.last.event_type, 'tenant_status': tenant.status,
                    'razorpay_status': remote_status,
                },
            )
        if decision.flag_payment and new_payment and kind in webhook_policy.CHARGE_KINDS:
            # A captured payment that access will not honour: keep it, and put it in front of ops.
            audit_log.record(
                action='subscription.payment_needs_refund', tenant_id=tenant.id, obj=subscription,
                after={
                    'razorpay_subscription_id': razorpay_subscription_id,
                    'razorpay_payment_id': razorpay_payment_id, 'amount': str(charged_amount),
                    'reason': decision.reason, 'event': event, 'event_id': event_id,
                    'razorpay_status': remote_status,
                },
            )
        return _OUTCOME_BY_ACTION[decision.action], decision.reason, tenant_id


def _apply_status_event(decision, kind, event, event_id, occurred_at, subscription, tenant, ledger_row, entity):
    """Carries out an APPLY decision: tenant status, billing period and grace clock, and the ledger's
    last-applied-event marker. Caller holds the subscription lock and the audit/payment bookkeeping."""
    tenant.status = decision.target
    if decision.target == Tenant.Status.ACTIVE:
        subscription.payment_failed_at = None
    elif decision.target == Tenant.Status.PAYMENT_FAILED:
        subscription.payment_failed_at = timezone.now()
    if kind in webhook_policy.CHARGE_KINDS:
        today = timezone.now().date()
        current_start = entity.get('current_start')
        current_end = entity.get('current_end')
        subscription.current_period_start = datetime_from_epoch(current_start) if current_start else today
        subscription.current_period_end = (
            datetime_from_epoch(current_end) if current_end else pricing.next_cycle_end(today)
        )
    subscription.save()
    tenant.save(update_fields=['status', 'updated_at'])
    if ledger_row is not None:
        ledger_row.last_status_event_at = occurred_at
        ledger_row.last_status_event_type = event
        ledger_row.last_status_event_id = event_id
        fields = ['last_status_event_at', 'last_status_event_type', 'last_status_event_id', 'updated_at']
        if kind in webhook_policy.CHARGE_KINDS and ledger_row.activated_at is None:
            ledger_row.activated_at = timezone.now()
            fields.append('activated_at')
        ledger_row.save(update_fields=fields)


def _invoice_for_webhook(entity):
    """The SubscriptionInvoice a Razorpay invoice entity belongs to, or None.

    Matched by the stored `razorpay_invoice_id`, falling back to the entity's
    `receipt`, which is our invoice's id: if the response to our create call was
    lost we hold no Razorpay id yet, but every event Razorpay sends carries the
    receipt. A receipt match is refused when the invoice already holds a
    different Razorpay id.

    Runs as super admin: a webhook has no tenant, and under RLS every invoice is
    invisible without one."""
    razorpay_invoice_id = entity.get('id', '')
    with tenant_context(is_super_admin=True):
        invoice = None
        if razorpay_invoice_id:
            invoice = SubscriptionInvoice.objects.filter(razorpay_invoice_id=razorpay_invoice_id).first()
        if invoice is None:
            try:
                receipt = uuid.UUID(str(entity.get('receipt') or ''))
            except ValueError:
                return None
            invoice = SubscriptionInvoice.objects.filter(pk=receipt).first()
            if invoice is not None and invoice.razorpay_invoice_id not in ('', razorpay_invoice_id):
                return None
        return invoice


def _bind_razorpay_invoice(invoice, razorpay_invoice_id):
    """Records the Razorpay id on an invoice whose create response we never saw (it
    was lost, or a webhook beat our own save), and releases any issue claim. A DRAFT
    is thereby ISSUED, so the retry sweep leaves it alone. Caller holds the invoice
    row lock."""
    invoice.issue_claimed_at = None
    fields = ['issue_claimed_at']
    if razorpay_invoice_id and not invoice.razorpay_invoice_id:
        invoice.razorpay_invoice_id = razorpay_invoice_id
        fields.append('razorpay_invoice_id')
        if invoice.status == SubscriptionInvoice.Status.DRAFT:
            invoice.status = SubscriptionInvoice.Status.ISSUED
            invoice.issued_at = timezone.now()
            fields += ['status', 'issued_at']
    invoice.save(update_fields=fields)


def _apply_invoice_event(event, invoice, razorpay_payment_id, payload):
    """Settles `invoice` for an `invoice.*` event: paid, or expired / partially paid
    (a failure). Idempotent — a replay, or the same fact arriving by both webhook and
    issue-time reconciliation, changes nothing. Caller holds the invoice row lock and
    a tenant context."""
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
        if (tenant.status == Tenant.Status.PAYMENT_FAILED
                and subscription.status_hold != Subscription.STATUS_HOLD_MANUAL):
            tenant.status = Tenant.Status.ACTIVE
        SubscriptionPayment.objects.create(
            tenant_id=tenant.id, subscription=subscription,
            razorpay_payment_id=razorpay_payment_id, amount=invoice.total_amount,
            status=SubscriptionPayment.Status.SUCCESS, paid_at=timezone.now(), raw_payload=payload,
        )
    elif event in ('invoice.expired', 'invoice.partially_paid'):
        if invoice.status in (SubscriptionInvoice.Status.FAILED, SubscriptionInvoice.Status.PAID):
            return  # already processed this failure — or a late failure for an invoice that has since been paid
        if razorpay_payment_id and SubscriptionPayment.objects.filter(
            razorpay_payment_id=razorpay_payment_id
        ).exists():
            return
        invoice.status = SubscriptionInvoice.Status.FAILED
        invoice.save(update_fields=['status'])
        # A failed invoice is still recorded, but it only starts the grace clock for a tenant in good
        # standing: it never reaches a suspended or cancelled one, nor one a Super Admin holds.
        if (tenant.status in (Tenant.Status.TRIAL, Tenant.Status.ACTIVE, Tenant.Status.PAYMENT_FAILED)
                and subscription.status_hold != Subscription.STATUS_HOLD_MANUAL):
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


def _handle_invoice_webhook(event, payload):
    """PER_BED_MONTHLY: finds the SubscriptionInvoice for a Razorpay invoice event
    (`_invoice_for_webhook`) and settles it (`_apply_invoice_event`)."""
    entity = payload.get('payload', {}).get('invoice', {}).get('entity', {})
    found = _invoice_for_webhook(entity)
    if found is None:
        return  # unknown invoice — nothing to reconcile

    payment_entity = payload.get('payload', {}).get('payment', {}).get('entity', {})
    razorpay_payment_id = payment_entity.get('id', '')

    with tenant_context(found.tenant_id), transaction.atomic():
        # Lock the invoice for the rest of the handler so a replayed or
        # concurrently-delivered webhook for the same invoice serializes behind
        # this one — the status-based idempotency checks can't race.
        invoice = (
            SubscriptionInvoice.objects.select_for_update(of=('self',))
            .select_related('subscription__tenant')
            .get(pk=found.pk)
        )
        # The match in `_invoice_for_webhook` was made before this lock; another
        # process may have bound a different Razorpay id since. Check again.
        if invoice.razorpay_invoice_id not in ('', entity.get('id', '')):
            logger.warning(
                'Ignoring %s for Razorpay invoice %s: invoice %s is bound to %s',
                event, entity.get('id', ''), invoice.pk, invoice.razorpay_invoice_id,
            )
            return
        _bind_razorpay_invoice(invoice, entity.get('id', ''))
        _apply_invoice_event(event, invoice, razorpay_payment_id, payload)


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


def set_manual_status_hold(tenant, held):
    """A Super Admin's own suspension or cancellation sticks: while the hold is on, no webhook may change
    the tenant's status (webhook_policy). Only an explicit reactivation clears it."""
    Subscription.objects.filter(tenant=tenant).update(
        status_hold=Subscription.STATUS_HOLD_MANUAL if held else '', updated_at=timezone.now())


def suspend_tenant(*, tenant, actor, request=None):
    before_status = tenant.status
    tenant.status = Tenant.Status.SUSPENDED
    tenant.save(update_fields=['status', 'updated_at'])
    set_manual_status_hold(tenant, True)
    audit_log.record(
        action='tenant.status_changed', actor=actor, tenant_id=tenant.id, obj=tenant,
        before={'status': before_status}, after={'status': tenant.status, 'status_hold': 'manual'}, request=request,
    )
    return tenant


def reactivate_tenant(*, tenant, actor, request=None):
    before_status = tenant.status
    tenant.status = Tenant.Status.ACTIVE
    tenant.save(update_fields=['status', 'updated_at'])
    set_manual_status_hold(tenant, False)
    audit_log.record(
        action='tenant.status_changed', actor=actor, tenant_id=tenant.id, obj=tenant,
        before={'status': before_status}, after={'status': tenant.status}, request=request,
    )
    return tenant


def _ensure_razorpay_customer(subscription):
    if not subscription.razorpay_customer_id:
        subscription.razorpay_customer_id = razorpay_client.create_razorpay_customer(subscription.tenant)
        subscription.save(update_fields=['razorpay_customer_id', 'updated_at'])


def _invoice_period(subscription, plan, *, period_start, billed_end, cycle_end):
    """Prices the bed-day history in `[period_start, billed_end)` against `plan`,
    writes the invoice + line items (invariant 6 — a list, never fixed fields)
    and either leaves it DRAFT for `issue_invoice` to send through Razorpay
    Invoices after commit or — below `PlatformConfig.min_billable_amount`
    (invariant 10) — marks it paid with no Razorpay call. `cycle_end` is the nominal end of the cycle the period
    belongs to: it sets the proration denominator, so a period closed early is
    charged for the days it ran, not for a whole month.

    Returns None, writing nothing, when the period already has an invoice
    (the model's `unique_invoice_per_cycle`), so a re-run never double-bills.
    Does not move the subscription's period; the caller decides what's next."""
    with tenant_context(subscription.tenant_id):
        if SubscriptionInvoice.objects.filter(subscription=subscription, period_start=period_start).exists():
            return None

        segments = pricing.bed_segments(subscription.tenant_id, period_start, billed_end)
        breakdown = pricing.prorated_charge(plan, segments, period_start, cycle_end)
        bed_count_start = segments[0][2] if segments else 0
        bed_count_end = segments[-1][2] if segments else 0

        invoice = SubscriptionInvoice.objects.create(
            tenant_id=subscription.tenant_id, subscription=subscription,
            period_start=period_start, period_end=billed_end,
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
            # Stays DRAFT: nothing remote happens inside this transaction, which may
            # still roll back (a Razorpay invoice can't be). It is issued once the
            # transaction commits, and by the periodic sweep if that attempt fails.
            invoice_id, tenant_id = invoice.pk, invoice.tenant_id
            transaction.on_commit(lambda: issue_invoice(invoice_id, tenant_id))
    return invoice


# How long an issue claim is respected before the sweep assumes its worker died.
INVOICE_ISSUE_CLAIM_TIMEOUT = timedelta(minutes=15)
INVOICE_ISSUE_AUDIT_ATTEMPTS = (1, 10, 50)


def _unissued_invoices(now):
    """DRAFT invoices nobody is currently issuing (never claimed, or the claim went stale)."""
    return SubscriptionInvoice.objects.filter(
        Q(issue_claimed_at__isnull=True) | Q(issue_claimed_at__lt=now - INVOICE_ISSUE_CLAIM_TIMEOUT),
        status=SubscriptionInvoice.Status.DRAFT, razorpay_invoice_id='',
    )


def _settle_issued_invoice(invoice_id, remote):
    """Records what Razorpay says about an invoice we just sent (or found by receipt).

    The invoice is re-read under its row lock because a webhook may have got there
    first — it can bind the Razorpay id by receipt and even mark the invoice paid
    while our create call was still in flight — and a later `issued` must never undo
    that. When `remote` was found already paid or expired (the lost-response retry),
    the payment is applied here, since its webhook may have been dropped before the
    id was known; `_apply_invoice_event` ignores facts already recorded."""
    with transaction.atomic():
        invoice = (
            SubscriptionInvoice.objects.select_for_update(of=('self',))
            .select_related('subscription__tenant')
            .get(pk=invoice_id)
        )
        if invoice.razorpay_invoice_id not in ('', remote.id):
            # Already bound to a different Razorpay invoice (by a webhook, since we
            # started): don't attach this one's status to it.
            logger.error(
                'Invoice %s is bound to %s but Razorpay returned %s for its receipt',
                invoice.pk, invoice.razorpay_invoice_id, remote.id,
            )
            invoice.issue_claimed_at = None
            invoice.save(update_fields=['issue_claimed_at'])
            return
        _bind_razorpay_invoice(invoice, remote.id)
        # The same statuses, mapped to the same events, as the webhooks treat them.
        event = {
            'paid': 'invoice.paid', 'expired': 'invoice.expired', 'partially_paid': 'invoice.partially_paid',
        }.get(remote.status)
        if event:
            _apply_invoice_event(event, invoice, remote.payment_id, {
                'source': 'issue_reconciliation', 'razorpay_invoice_id': remote.id,
                'razorpay_status': remote.status, 'razorpay_payment_id': remote.payment_id,
            })


def issue_invoice(invoice_id, tenant_id):
    """Sends one priced DRAFT invoice to Razorpay; returns True (issued), False
    (failed, the sweep retries) or None (not ours: already issued, or another worker
    holds it).

    Runs after the transaction that priced the invoice has committed, so a rollback
    can never leave a Razorpay invoice behind. The invoice is claimed first (a
    conditional UPDATE, atomic across workers), and no database lock is held during
    the network call. The invoice's own id is the Razorpay `receipt`, so if Razorpay
    created it but we lost the response or failed to save, the retry finds and reuses
    it rather than billing twice (`razorpay_client.create_razorpay_invoice`)."""
    now = timezone.now()
    with tenant_context(tenant_id):
        if not _unissued_invoices(now).filter(pk=invoice_id).update(issue_claimed_at=now):
            return None
        invoice = SubscriptionInvoice.objects.select_related('subscription').get(pk=invoice_id)
        try:
            remote = razorpay_client.create_razorpay_invoice(
                invoice.subscription.razorpay_customer_id, invoice,
            )
        except Exception as exc:  # noqa: BLE001 - any SDK/network failure is a retry, not a crash
            logger.warning('Could not issue subscription invoice %s; will retry', invoice_id, exc_info=True)
            SubscriptionInvoice.objects.filter(pk=invoice_id).update(
                issue_claimed_at=None, issue_attempts=F('issue_attempts') + 1, last_issue_error=str(exc)[:1000],
            )
            attempts = SubscriptionInvoice.objects.values_list('issue_attempts', flat=True).get(pk=invoice_id)
            if attempts in INVOICE_ISSUE_AUDIT_ATTEMPTS:
                audit_log.record(
                    action='subscription.invoice_issue_failed', tenant_id=tenant_id, obj=invoice,
                    after={'attempts': attempts, 'period_start': invoice.period_start.isoformat()},
                )
            return False
        _settle_issued_invoice(invoice_id, remote)
        return True


def process_invoice_issuing():
    """Issues every DRAFT invoice that isn't claimed (including claims whose worker
    died). Run by a periodic task, so a Razorpay outage delays an invoice but can't
    lose it."""
    with tenant_context(is_super_admin=True):
        due = list(_unissued_invoices(timezone.now()).order_by('created_at').values_list('pk', 'tenant_id'))
    outcome = {'issued': 0, 'failed': 0}
    for invoice_id, tenant_id in due:
        result = issue_invoice(invoice_id, tenant_id)
        if result is not None:
            outcome['issued' if result else 'failed'] += 1
    return outcome


@transaction.atomic
def generate_invoice_for_subscription(subscription, *, today=None):
    """Closes out one PER_BED_MONTHLY billing cycle: prices the cycle from
    the bed ledger (`pricing.bed_segments` + `pricing.prorated_charge`) and
    invoices it (`_invoice_period`).

    Idempotent: re-running for a cycle that already has an invoice is a no-op,
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

    _ensure_razorpay_customer(subscription)
    invoice = _invoice_period(
        subscription, plan, period_start=period_start, billed_end=period_end, cycle_end=period_end,
    )
    if invoice is None:
        return None  # already generated for this cycle — safe to re-run

    # Advance to the next cycle regardless of payment outcome — a
    # failed/expired invoice is reconciled by the webhook + the existing
    # grace-period sweep (`process_payment_grace_periods`), not by
    # holding this cycle open.
    with tenant_context(subscription.tenant_id):
        subscription.current_period_start = period_end
        subscription.current_period_end = pricing.next_cycle_end(period_end)
        subscription.save(update_fields=['current_period_start', 'current_period_end', 'updated_at'])
    return invoice


@transaction.atomic
def close_per_bed_period(subscription, *, today=None):
    """The tenant is leaving its PER_BED_MONTHLY plan: invoice what has accrued
    under it, because arrears can't be priced once the plan is gone. Call it
    before `subscription.plan` or the period is overwritten, with the
    subscription row locked; the caller then sets the new plan and period.

    A cycle that already ended but wasn't invoiced yet is billed whole first
    (the normal path, via `generate_invoice_for_subscription`). The current
    cycle is then billed from its start up to `today`, on the old plan, against
    that cycle's full length. Nothing is written when no day has accrued (the
    plan was chosen today) or the period already has an invoice.

    Returns the invoices created, oldest first."""
    plan = subscription.plan
    if plan is None or plan.pricing_type != Plan.PricingType.PER_BED_MONTHLY:
        return []
    if subscription.current_period_start is None or subscription.current_period_end is None:
        return []
    today = today or timezone.now().date()

    invoices = []
    while subscription.current_period_end <= today:
        invoice = generate_invoice_for_subscription(subscription, today=today)
        if invoice is None:
            break
        invoices.append(invoice)

    period_start = subscription.current_period_start
    cycle_end = subscription.current_period_end
    billed_end = min(today, cycle_end)
    if billed_end > period_start:
        _ensure_razorpay_customer(subscription)
        invoice = _invoice_period(
            subscription, plan, period_start=period_start, billed_end=billed_end, cycle_end=cycle_end,
        )
        if invoice is not None:
            invoices.append(invoice)
    return invoices


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
