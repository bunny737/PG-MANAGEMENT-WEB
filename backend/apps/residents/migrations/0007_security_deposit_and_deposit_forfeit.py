from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    """Security deposit becomes its own Admission field. The refundable /
    forfeitable amount that vacate and absconded used to read from
    `advance_amount` moves to it; `advance_amount` is now rent paid upfront
    for the first period. AbscondedRecord's advance_* fields are renamed to
    deposit_* to match."""

    dependencies = [
        ('residents', '0006_alter_admission_contracted_sharing_type_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='admission',
            name='security_deposit_amount',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12),
        ),
        migrations.AddField(
            model_name='admission',
            name='security_deposit_collected_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='admission',
            name='security_deposit_mode',
            field=models.CharField(
                blank=True, max_length=15,
                choices=[('upi', 'UPI'), ('cash', 'Cash'), ('bank_transfer', 'Bank Transfer')],
            ),
        ),
        # Existing rows: their advance_amount was the deposit under the old rule.
        migrations.RunSQL(
            sql="""
                UPDATE admissions SET
                    security_deposit_amount = advance_amount,
                    security_deposit_collected_date = advance_collected_date,
                    security_deposit_mode = advance_mode,
                    advance_amount = 0, advance_collected_date = NULL, advance_mode = '';
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RenameField('abscondedrecord', 'advance_forfeited', 'deposit_forfeited'),
        migrations.RenameField('abscondedrecord', 'advance_applied_to_dues', 'deposit_applied_to_dues'),
    ]
