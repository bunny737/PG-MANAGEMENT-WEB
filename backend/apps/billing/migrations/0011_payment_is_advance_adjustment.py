"""Fail-loud backfill of Payment.is_advance_adjustment and blank payment_mode support."""
from decimal import Decimal

from django.db import migrations, models
from django.db.models import Sum
from django.db.models.functions import Coalesce

from apps.billing.historical_audit import ZERO, classify_historical_advance_payments
from apps.core.tenancy import tenant_context


def backfill_advance_adjustments(apps, schema_editor):
    Admission = apps.get_model('residents', 'Admission')
    Payment = apps.get_model('billing', 'Payment')

    report = classify_historical_advance_payments(apps)
    if report['gate_failures']:
        details = '; '.join(
            f"admission={g['admission_id']} ({g['reason']})" for g in report['gate_failures']
        )
        raise RuntimeError(
            f"Aborting billing.0011: unresolved historical advance gate failures: {details}"
        )

    with tenant_context(is_super_admin=True):
        if report['to_mark_ids']:
            Payment.objects.filter(pk__in=report['to_mark_ids']).update(is_advance_adjustment=True)

        # Global reconciliation invariant: every Admission with advance_applied_amount > 0
        # must have 100% of its applied advance backed by is_advance_adjustment=True rows.
        money_field = models.DecimalField(max_digits=12, decimal_places=2)
        unreconciled = []
        for admission in Admission.objects.filter(advance_applied_amount__gt=ZERO):
            flagged_sum = (
                Payment.objects.filter(
                    invoice__resident_id=admission.resident_id,
                    is_advance_adjustment=True,
                ).aggregate(total=Coalesce(Sum('amount'), ZERO, output_field=money_field))['total']
            )
            if flagged_sum != admission.advance_applied_amount:
                unreconciled.append(
                    f"admission={admission.id} applied={admission.advance_applied_amount} flagged={flagged_sum}"
                )
        if unreconciled:
            raise RuntimeError(
                'Aborting billing.0011: global advance reconciliation mismatch: ' + '; '.join(unreconciled)
            )


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0010_line_type_food_holiday'),
        ('residents', '0012_merge_deposit_payments_and_resident_access'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='is_advance_adjustment',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AlterField(
            model_name='payment',
            name='payment_mode',
            field=models.CharField(
                blank=True,
                choices=[
                    ('upi', 'UPI'),
                    ('cash', 'Cash'),
                    ('bank_transfer', 'Bank Transfer'),
                    ('card', 'Card'),
                    ('cheque', 'Cheque'),
                ],
                max_length=15,
            ),
        ),
        migrations.RunPython(backfill_advance_adjustments, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='payment',
            constraint=models.CheckConstraint(
                condition=models.Q(('is_advance_adjustment', True)) | models.Q(('payment_mode', ''), _negated=True),
                name='payment_mode_required_for_direct',
            ),
        ),
    ]

