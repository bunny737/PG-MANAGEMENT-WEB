"""Ordering and recovery rules for Razorpay subscription webhooks (owner decision 2026-10-20).

Razorpay delivers webhooks at least once, asynchronously and not necessarily in order, so a payload is
a snapshot of something that already happened. The rule:

    Terminal and manual states win first; otherwise the newest event by OCCURRENCE time wins — not
    the last webhook delivered.

Pure functions only (no database, no Razorpay): `decide()` maps one event plus the facts we hold to a
`Decision`, and `services._handle_subscription_webhook` carries it out and writes the audit trail.

Precedence at equal timestamps (higher wins):  cancelled > halted > charged / resumed > activated > payment.failed
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from apps.accounts.models import Tenant

Status = Tenant.Status

# Razorpay event name -> kind. Anything else (paused, pending, ...) is not ours to act on.
KIND_BY_EVENT = {
    'subscription.activated': 'activated',
    'subscription.charged': 'charged',
    'subscription.resumed': 'resumed',
    'subscription.halted': 'halted',
    'subscription.cancelled': 'cancelled',
    'payment.failed': 'payment_failed',
}
PRECEDENCE = {'cancelled': 5, 'halted': 4, 'charged': 3, 'resumed': 3, 'activated': 2, 'payment_failed': 1}
CHARGE_KINDS = ('activated', 'charged')   # carry a captured payment

# Razorpay's own subscription status -> the tenant status it implies (None: no opinion).
TENANT_STATUS_BY_REMOTE = {
    'active': Status.ACTIVE,
    'pending': Status.PAYMENT_FAILED,     # a charge failed and Razorpay is retrying
    'halted': Status.SUSPENDED,
    'cancelled': Status.CANCELLED,
    'completed': Status.CANCELLED,
    'expired': Status.CANCELLED,
}


class Action:
    APPLY = 'apply'                        # change the tenant to `target`
    NO_CHANGE = 'no_change'                # valid and current, nothing to change (e.g. already in that state)
    STALE = 'stale'
    TERMINAL = 'terminal'                  # subscription finished / tenant cancelled
    MANUAL_HOLD = 'manual_hold'
    NOT_RECOVERY = 'not_recovery'          # e.g. `activated` after the initial activation
    VERIFY = 'verify'                      # ask Razorpay before changing access
    DECLINED = 'declined'                  # asked Razorpay; it did not confirm the change


@dataclass(frozen=True)
class LastEvent:
    at: Optional[datetime] = None
    event_type: str = ''                   # the Razorpay event name, e.g. 'subscription.halted'
    event_id: str = ''

    @property
    def kind(self):
        return KIND_BY_EVENT.get(self.event_type, '')


@dataclass(frozen=True)
class Facts:
    tenant_status: str
    row_cancelled: bool                    # the ledger row reached CANCELLED
    manual_hold: bool
    activated_before: bool
    last: LastEvent = LastEvent()


@dataclass(frozen=True)
class Decision:
    action: str
    target: Optional[str] = None           # tenant status to apply
    reason: str = ''
    flag_payment: bool = False             # a captured payment arrived that access must not honour


def decide(kind, occurred_at, facts):
    """`kind` is a value of KIND_BY_EVENT; `occurred_at` the event's own timestamp or None."""

    # 1. Manual states win first: no webhook may undo a Super Admin's suspension or cancellation.
    if facts.manual_hold:
        return Decision(Action.MANUAL_HOLD, reason='tenant status was set manually', flag_payment=kind in CHARGE_KINDS)

    # 2. Terminal states next. A cancelled subscription never restarts, so nothing later can reactivate it.
    if kind == 'cancelled':
        if facts.row_cancelled or facts.tenant_status == Status.CANCELLED:
            return Decision(Action.NO_CHANGE, reason='already cancelled')
        return Decision(Action.APPLY, Status.CANCELLED, 'subscription cancelled')  # applies whatever its age
    if facts.row_cancelled or facts.tenant_status == Status.CANCELLED:
        return Decision(Action.TERMINAL, reason='subscription is cancelled', flag_payment=kind in CHARGE_KINDS)

    # 3. No timestamp, no ordering: ask Razorpay for the authoritative state instead of guessing.
    if occurred_at is None:
        return Decision(Action.VERIFY, reason='missing_timestamp')

    # 4. Newest by occurrence time wins; equal timestamps fall back to the fixed precedence.
    last = facts.last
    if last.at is not None:
        if occurred_at < last.at:
            return Decision(Action.STALE, reason='older than the last applied event')
        if occurred_at == last.at and PRECEDENCE[kind] <= PRECEDENCE.get(last.kind, 0):
            return Decision(Action.STALE, reason='same time as, and not above, the last applied event')

    suspended_by_razorpay = facts.tenant_status == Status.SUSPENDED and last.kind == 'halted'

    if kind == 'halted':
        return Decision(Action.APPLY, Status.SUSPENDED, 'subscription halted')
    if kind == 'payment_failed':
        if facts.tenant_status == Status.SUSPENDED:
            return Decision(Action.NO_CHANGE, reason='already suspended')
        return Decision(Action.APPLY, Status.PAYMENT_FAILED, 'payment failed')
    if kind == 'activated':
        if facts.activated_before:
            return Decision(Action.NOT_RECOVERY, reason='activation is for the first charge only')
        return Decision(Action.APPLY, Status.ACTIVE, 'initial activation')
    if kind == 'charged':
        if suspended_by_razorpay:
            # Contradicts "halted stays suspended until an explicit, newer resume": let Razorpay decide.
            return Decision(Action.VERIFY, reason='charged_after_halt', flag_payment=True)
        return Decision(Action.APPLY, Status.ACTIVE, 'charge succeeded')
    if kind == 'resumed':
        if suspended_by_razorpay:
            return Decision(Action.APPLY, Status.ACTIVE, 'subscription resumed')
        return Decision(Action.NO_CHANGE, reason='nothing to resume')
    raise ValueError(f'unknown webhook kind {kind!r}')


def tenant_status_for_remote(remote_status):
    return TENANT_STATUS_BY_REMOTE.get((remote_status or '').lower())
