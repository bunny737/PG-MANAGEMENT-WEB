from django.db import IntegrityError, migrations, models, transaction

from apps.properties.join_codes import generate_join_code


def backfill_join_codes(apps, schema_editor):
    """Give every existing property a join code. `properties` has FORCE ROW LEVEL SECURITY and the
    migration role is not a superuser, so without the super-admin GUC the UPDATEs would match
    nothing and silently "succeed". set_config(..., true) lasts for this transaction only.

    The historical model has no save() override, so the draw-again-on-collision loop is here;
    the partial unique index is the authority (RLS hides other tenants' rows from a pre-check)."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.is_super_admin', 'true', true)")
    Property = apps.get_model('properties', 'Property')
    for prop in Property.objects.filter(join_code__isnull=True).iterator():
        for _attempt in range(5):
            code = generate_join_code()
            try:
                with transaction.atomic():
                    Property.objects.filter(pk=prop.pk).update(join_code=code)
                break
            except IntegrityError:
                continue
        else:
            raise RuntimeError('Could not allocate a unique join code for an existing property.')


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0011_propertysettings_food_charge_per_day'),
    ]

    operations = [
        migrations.AddField(
            model_name='property',
            name='join_code',
            field=models.CharField(blank=True, editable=False, max_length=8, null=True),
        ),
        migrations.AddField(
            model_name='property',
            name='join_code_rotated_at',
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddConstraint(
            model_name='property',
            constraint=models.UniqueConstraint(condition=models.Q(('join_code__isnull', False)), fields=('join_code',), name='property_join_code_unique'),
        ),
        migrations.RunPython(backfill_join_codes, migrations.RunPython.noop),
    ]
