# Owner decision 2026-10-31: reprice the launch plans seeded by 0006
# (Basic 149 -> 199, Unlimited 249 -> 299). Prices are data (invariant 10); bed caps are untouched.
#
# A historical-model update bypasses Plan.validate_protected_changes(), the lock that stops a
# live plan being repriced, so this migration enforces its own guard: a plan still at its old
# price is only repriced when nothing bills against it. Rows that are missing, already at the new
# price, or hand-edited by Super Admin are left alone.
#
# No tenant_context() wrapper: plans are global, no RLS.
import uuid
from decimal import Decimal

from django.db import migrations
from django.utils import timezone

BASIC_ID = uuid.UUID('78244c23-81a9-4bd9-bb8a-1abbc352f4c3')
UNLIMITED_ID = uuid.UUID('63d0b22d-d0d7-4b30-84be-1063104fd276')

REPRICES = [
    {'id': BASIC_ID, 'name': 'Basic', 'old': Decimal('149.00'), 'new': Decimal('199.00')},
    {'id': UNLIMITED_ID, 'name': 'Unlimited', 'old': Decimal('249.00'), 'new': Decimal('299.00')},
]


def _billing_references(plan):
    refs = []
    if plan.razorpay_plan_id:
        refs.append('a Razorpay plan ID')
    if plan.subscriptions.exists():
        refs.append('subscriptions')
    if plan.pending_subscriptions.exists():
        refs.append('pending plan changes')
    if plan.razorpay_subscriptions.exists():
        refs.append('Razorpay subscriptions')
    return refs


def reprice(apps, schema_editor):
    Plan = apps.get_model('subscriptions', 'Plan')

    # Validate both plans before writing either, so a live Unlimited never leaves Basic repriced.
    to_update = []
    for spec in REPRICES:
        plan = Plan.objects.filter(pk=spec['id']).first()
        if plan is None or plan.price_per_month != spec['old']:
            continue
        refs = _billing_references(plan)
        if refs:
            raise RuntimeError(
                f'Plan "{spec["name"]}" is still at {spec["old"]} but is already in use '
                f'({", ".join(refs)}), so it cannot be repriced in place. Create a new plan at '
                f'{spec["new"]} and retire this one in Django admin, then re-run migrate.'
            )
        to_update.append(spec)

    now = timezone.now()
    for spec in to_update:
        # queryset update() doesn't advance auto_now; the public catalogue's updated_at reads it.
        Plan.objects.filter(pk=spec['id']).update(price_per_month=spec['new'], updated_at=now)


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0015_payment_refund_obligation'),
    ]

    operations = [
        # Reversing is a deliberate no-op: restoring the old prices could undo a later
        # Super Admin or owner decision.
        migrations.RunPython(reprice, migrations.RunPython.noop),
    ]
