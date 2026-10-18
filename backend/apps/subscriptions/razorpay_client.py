"""Thin Razorpay SDK wrapper (PRD §4/§12: Razorpay handles platform
subscription billing ONLY — resident rent is never collected through it,
see Module 09/10).

Falls back to a local stub when `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET`
aren't configured, so dev/test can exercise the full select-plan/webhook
flow without real credentials — same conditional-activation pattern as
Module 04's S3/local document storage.
"""
import uuid
from typing import NamedTuple

import razorpay
from django.conf import settings


def is_configured():
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def get_client():
    if not is_configured():
        return None
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def create_razorpay_plan(plan):
    """Returns a Razorpay plan id for `plan`. Stubbed locally when
    unconfigured — the stub id is enough to drive the rest of the flow
    (it's just stored on `Plan.razorpay_plan_id`, never parsed)."""
    client = get_client()
    if client is None:
        return f'test_plan_{uuid.uuid4().hex[:14]}'
    response = client.plan.create({
        'period': 'monthly',
        'interval': 1,
        'item': {
            'name': plan.name,
            'amount': int(plan.price_per_month * 100),  # paise
            'currency': 'INR',
        },
    })
    return response['id']


def create_razorpay_subscription(plan, *, total_count=12):
    """Returns a Razorpay subscription id for a tenant selecting `plan`.
    Stubbed locally when unconfigured."""
    client = get_client()
    if client is None:
        return f'test_sub_{uuid.uuid4().hex[:14]}'
    response = client.subscription.create({
        'plan_id': plan.razorpay_plan_id,
        'total_count': total_count,
        'customer_notify': 1,
    })
    return response['id']


def cancel_razorpay_subscription(subscription_id):
    """Cancels a Razorpay subscription immediately, so it can't charge again.
    Used when a tenant moves to another plan; stubbed locally when unconfigured.
    Raises on failure: callers decide whether that blocks the plan change."""
    client = get_client()
    if client is None or not subscription_id:
        return
    client.subscription.cancel(subscription_id, {'cancel_at_cycle_end': 0})


def fetch_razorpay_subscription_status(subscription_id):
    """Razorpay's own status for a subscription ('active', 'cancelled', 'completed'...),
    or None when Razorpay isn't configured. Used to tell "cancel failed because it is
    already cancelled" apart from a genuine failure."""
    client = get_client()
    if client is None:
        return None
    return client.subscription.fetch(subscription_id).get('status')


def create_razorpay_customer(tenant):
    """Returns a Razorpay customer id for `tenant`, used to issue arrears
    invoices for PER_BED_MONTHLY plans (see Phase 0 spike: Razorpay Add-ons
    are deprecated, so arrears amounts are billed via Invoices, not
    Subscriptions — there is no shared per-tier Razorpay Plan to attach to).
    Stubbed locally when unconfigured."""
    from apps.accounts.models import User
    from apps.core.roles import Role

    client = get_client()
    if client is None:
        return f'test_cust_{uuid.uuid4().hex[:14]}'
    owner = User.objects.filter(tenant=tenant, role=Role.OWNER).order_by('created_at').first()
    response = client.customer.create({
        'name': tenant.name,
        'email': owner.email if owner else '',
        'fail_existing': 0,
    })
    return response['id']


class RazorpayInvoice(NamedTuple):
    """What Razorpay reports for one of our invoices. `status` is Razorpay's own
    (`issued`, `paid`, `expired`, ...); `payment_id` is set once it is paid."""
    id: str
    short_url: str
    status: str
    payment_id: str = ''


def _as_razorpay_invoice(entity):
    return RazorpayInvoice(
        id=entity['id'], short_url=entity.get('short_url', ''),
        status=entity.get('status', 'issued'), payment_id=entity.get('payment_id') or '',
    )


def create_razorpay_invoice(customer_id, subscription_invoice):
    """Creates and issues a Razorpay Invoice for one PER_BED_MONTHLY billing
    cycle, returning its `RazorpayInvoice`. One Razorpay line item per
    `SubscriptionInvoiceLine`, using the line's own already-rounded `amount` (not
    unit_rate × quantity) so the line items always sum to exactly `total_amount`
    (invariant 5/6).

    Safe to call again for the same `SubscriptionInvoice`: its id is sent as the
    Razorpay `receipt`, and an invoice already carrying that receipt is reused
    (and issued, if a crash left it a draft) instead of creating a second one.
    That makes a retry after a lost response or a failed local save harmless.
    The reused invoice's real status comes back, so the caller can see that it was
    already paid or has expired rather than assume it is merely issued.

    Stubbed locally when unconfigured, and then always `issued`."""
    receipt = str(subscription_invoice.id)
    client = get_client()
    if client is None:
        stub_id = f'test_inv_{subscription_invoice.id.hex[:14]}'
        return RazorpayInvoice(stub_id, f'https://rzp.io/i/{stub_id}', 'issued')

    existing = client.invoice.all({'receipt': receipt}).get('items', [])
    if existing:
        found = existing[0]
        if found.get('status') == 'draft':
            found = client.invoice.issue(found['id'])
        return _as_razorpay_invoice(found)

    response = client.invoice.create({
        'type': 'invoice',
        'customer_id': customer_id,
        'currency': 'INR',
        'receipt': receipt,
        'line_items': [
            {
                'name': line.description[:255],
                'amount': int(line.amount * 100),  # paise
                'currency': 'INR',
                'quantity': 1,
            }
            for line in subscription_invoice.lines.all()
        ],
    })
    issued = client.invoice.issue(response['id'])
    return _as_razorpay_invoice({'id': response['id'], 'status': 'issued', **issued})


def verify_webhook_signature(payload_body, signature):
    """True if the webhook signature is valid.

    When no webhook secret is configured, verification is skipped (always True)
    ONLY if settings.RAZORPAY_ALLOW_UNSIGNED_WEBHOOKS is on (dev/test). In
    production that flag defaults to False, so a missing secret fails closed —
    the webhook endpoint is public and unauthenticated (see RazorpayWebhookView),
    so an unverified payload could otherwise let anyone drive tenant status
    changes and platform payment records."""
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return bool(settings.RAZORPAY_ALLOW_UNSIGNED_WEBHOOKS)
    try:
        razorpay.Utility().verify_webhook_signature(
            payload_body, signature, settings.RAZORPAY_WEBHOOK_SECRET
        )
        return True
    except razorpay.errors.SignatureVerificationError:
        return False
