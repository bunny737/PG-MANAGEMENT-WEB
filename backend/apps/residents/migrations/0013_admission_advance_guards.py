"""Add Admission.first_invoice_advance_settled and advance balance check constraints."""
from decimal import Decimal

from django.db import migrations, models
from django.db.models import Q

from apps.core.tenancy import tenant_context


def backfill_first_invoice_settled(apps, schema_editor):
    Admission = apps.get_model('residents', 'Admission')
    Invoice = apps.get_model('billing', 'Invoice')

    with tenant_context(is_super_admin=True):
        issued_resident_ids = Invoice.objects.exclude(status='draft').values_list('resident_id', flat=True)
        Admission.objects.filter(
            Q(advance_applied_amount__gt=Decimal('0.00')) | Q(resident_id__in=issued_resident_ids)
        ).update(first_invoice_advance_settled=True)


class Migration(migrations.Migration):

    dependencies = [
        ('residents', '0012_merge_deposit_payments_and_resident_access'),
        ('billing', '0002_invoice_invoicelineitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='admission',
            name='first_invoice_advance_settled',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(backfill_first_invoice_settled, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='admission',
            constraint=models.CheckConstraint(
                condition=models.Q(('advance_applied_amount__gte', 0)),
                name='admission_advance_applied_non_negative',
            ),
        ),
        migrations.AddConstraint(
            model_name='admission',
            constraint=models.CheckConstraint(
                condition=models.Q(('advance_applied_amount__lte', models.F('advance_amount'))),
                name='admission_advance_applied_lte_advance',
            ),
        ),
    ]

