# Seeds the launch plan lineup (owner decision 2026-10-18) and the 45-day
# trial. Values are data, editable afterwards by Super Admin (invariant 10).
#
# No tenant_context() wrapper: plans and platform_config are global, no RLS.
import uuid
from decimal import Decimal

from django.db import migrations

BASIC_ID = uuid.UUID('78244c23-81a9-4bd9-bb8a-1abbc352f4c3')
UNLIMITED_ID = uuid.UUID('63d0b22d-d0d7-4b30-84be-1063104fd276')

PLANS = [
    {'id': BASIC_ID, 'name': 'Basic', 'price_per_month': Decimal('149.00'), 'max_beds': 500},
    {'id': UNLIMITED_ID, 'name': 'Unlimited', 'price_per_month': Decimal('249.00'), 'max_beds': None},
]
TRIAL_DAYS = 45


def seed(apps, schema_editor):
    Plan = apps.get_model('subscriptions', 'Plan')
    PlatformConfig = apps.get_model('core', 'PlatformConfig')

    # Validate everything before writing, and never overwrite or merge into a
    # plan this migration didn't create.
    for spec in PLANS:
        existing = Plan.objects.filter(pk=spec['id']).first()
        if existing is not None:
            actual = (existing.name, existing.pricing_type, existing.price_per_month, existing.max_beds)
            expected = (spec['name'], 'flat_monthly', spec['price_per_month'], spec['max_beds'])
            if actual != expected:
                raise RuntimeError(
                    f'Plan {spec["id"]} already exists with unexpected values {actual}; '
                    f'expected {expected}. Resolve it in Django admin, then re-run migrate.'
                )
        elif Plan.objects.filter(name=spec['name']).exists():
            raise RuntimeError(
                f'A plan named "{spec["name"]}" already exists. Rename it in Django admin, '
                f'then re-run migrate.'
            )

    # Historical models don't run Plan.save(), so move the trial flag here.
    Plan.objects.filter(is_trial_plan=True).exclude(pk=BASIC_ID).update(is_trial_plan=False)
    for spec in PLANS:
        Plan.objects.get_or_create(
            pk=spec['id'],
            defaults={
                'name': spec['name'],
                'pricing_type': 'flat_monthly',
                'price_per_month': spec['price_per_month'],
                'max_beds': spec['max_beds'],
                'max_properties': None,
                'max_residents_per_property': None,
                'is_active': True,
            },
        )
    Plan.objects.filter(pk=BASIC_ID).update(is_trial_plan=True, is_active=True)

    config, _ = PlatformConfig.objects.get_or_create(pk=1)
    config.trial_days = TRIAL_DAYS
    config.save(update_fields=['trial_days', 'updated_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_alter_platformconfig_trial_days'),
        ('subscriptions', '0005_plan_max_beds_subscription_max_beds_override'),
    ]

    operations = [
        # Reversing is a deliberate no-op: deleting the plans would fail (PROTECT)
        # once a tenant subscribes, and restoring trial_days would clobber any
        # later Super Admin edit. Reversing 0005 drops the new columns anyway.
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
