"""Give every existing payment a receipt number (D4), per tenant in the order
the payments were recorded, and leave each tenant's counter at its last one
so new payments continue the sequence."""
from collections import defaultdict

from django.db import migrations


def backfill(apps, schema_editor):
    from apps.core.tenancy import tenant_context

    Payment = apps.get_model('billing', 'Payment')
    ReceiptCounter = apps.get_model('billing', 'ReceiptCounter')
    # payments / receipt_counters are under FORCE RLS: without a context the
    # migration would see no rows at all.
    with tenant_context(is_super_admin=True):
        last = defaultdict(int)
        for payment in Payment.objects.filter(receipt_number__isnull=True).order_by('tenant_id', 'created_at', 'id'):
            last[payment.tenant_id] += 1
            payment.receipt_number = f'RCT-{last[payment.tenant_id]:06d}'
            payment.save(update_fields=['receipt_number'])
        for tenant_id, number in last.items():
            ReceiptCounter.objects.update_or_create(tenant_id=tenant_id, defaults={'last_number': number})


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0005_receiptcounter_payment_idempotency_key_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
