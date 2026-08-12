from django.db import migrations

from apps.core.tenancy import tenant_context


def backfill_bed_ledger(apps, schema_editor):
    """Seeds one 'added' BedLedgerEntry per existing Bed at `bed.created_at`
    (see `BedLedgerEntry`'s docstring — `Bed.delete()` is a hard delete, so
    this backfill can only recover beds that still exist; proration is exact
    only from here forward)."""
    Bed = apps.get_model('properties', 'Bed')
    BedLedgerEntry = apps.get_model('subscriptions', 'BedLedgerEntry')

    # RLS is FORCE-enabled on bed_ledger_entries (invariant 1) and this
    # migration runs outside any request, so there's no app.tenant_id GUC
    # set — without is_super_admin the insert would be rejected.
    with tenant_context(is_super_admin=True):
        entries = [
            BedLedgerEntry(
                tenant_id=bed.tenant_id, bed_id=bed.id,
                event='added', occurred_at=bed.created_at,
            )
            for bed in Bed.objects.all().iterator()
        ]
        BedLedgerEntry.objects.bulk_create(entries, batch_size=500)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0002_alter_plan_options_plan_pricing_type_and_more'),
        ('properties', '0005_alter_room_sharing_type'),
    ]

    operations = [
        migrations.RunPython(backfill_bed_ledger, noop_reverse),
    ]
