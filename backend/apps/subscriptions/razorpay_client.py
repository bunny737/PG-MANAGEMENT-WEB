"""Thin Razorpay SDK wrapper (PRD §4/§12: Razorpay handles platform
subscription billing ONLY — resident rent is never collected through it,
see Module 09/10).

Falls back to a local stub when `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET`
aren't configured, so dev/test can exercise the full select-plan/webhook
flow without real credentials — same conditional-activation pattern as
Module 04's S3/local document storage.
"""
import uuid

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


def verify_webhook_signature(payload_body, signature):
    """True if the webhook signature is valid. Verification is skipped
    (always True) when no webhook secret is configured, so dev/test can post
    a fake webhook body without a real Razorpay signature."""
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return True
    try:
        razorpay.Utility().verify_webhook_signature(
            payload_body, signature, settings.RAZORPAY_WEBHOOK_SECRET
        )
        return True
    except razorpay.errors.SignatureVerificationError:
        return False
