# Module 10 (2026-11-01): the security deposit can be collected in parts. `agreed` is the full
# amount owed, `security_deposit_amount` stays the amount collected, and `deposit_payments` is the
# ledger behind it. Existing admissions are backfilled so agreed == collected and each has one row.

import django.db.models.deletion
import uuid
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models

from apps.core.rls import enable_rls

# The collected amount so far becomes the agreed amount, and each admission that collected anything
# gets one ledger row (date and mode from its own fields; a legacy row with no mode is cash).
BACKFILL_SQL = """
    SELECT set_config('app.is_super_admin', 'true', true);
    UPDATE admissions SET security_deposit_agreed = security_deposit_amount;
    INSERT INTO deposit_payments
        (id, tenant_id, created_at, updated_at, admission_id, amount, payment_date, payment_mode,
         reference, recorded_by_id)
    SELECT gen_random_uuid(), tenant_id, now(), now(), id, security_deposit_amount,
           COALESCE(security_deposit_collected_date, joining_date),
           COALESCE(NULLIF(security_deposit_mode, ''), 'cash'), '', recorded_by_id
    FROM admissions WHERE security_deposit_amount > 0;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('residents', '0009_food_holiday_settlement'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='admission',
            name='security_deposit_agreed',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12),
        ),
        migrations.CreateModel(
            name='DepositPayment',
            fields=[
                ('tenant_id', models.UUIDField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('payment_date', models.DateField()),
                ('payment_mode', models.CharField(choices=[('upi', 'UPI'), ('cash', 'Cash'), ('bank_transfer', 'Bank Transfer')], max_length=15)),
                ('reference', models.CharField(blank=True, max_length=100)),
                ('idempotency_key', models.CharField(blank=True, max_length=100, null=True)),
                ('admission', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='deposit_payments', to='residents.admission')),
                ('recorded_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='deposit_payments_recorded', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'deposit_payments',
                'ordering': ['-payment_date', '-created_at'],
                'constraints': [models.UniqueConstraint(condition=models.Q(('idempotency_key__isnull', False)), fields=('tenant_id', 'idempotency_key'), name='unique_deposit_payment_idempotency_key')],
            },
        ),
        enable_rls('deposit_payments'),
        # `admissions` and `deposit_payments` are FORCE-RLS and the app role is not a superuser, so
        # without the super-admin GUC these statements would match/insert nothing and "succeed"
        # (the lesson of 0007). set_config(..., true) is scoped to this migration's transaction.
        migrations.RunSQL(BACKFILL_SQL, migrations.RunSQL.noop),
    ]
