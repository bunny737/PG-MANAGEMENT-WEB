import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.rls import enable_rls
from apps.core.tenancy import tenant_context


def create_default_buildings(apps, schema_editor):
    """Every existing Property gets a "Main Building" (order 0), and every
    existing Floor is re-parented onto it — Building always exists between
    Property and Floor going forward (see docs/modules/02-property-hierarchy.md
    Decisions, 2026-07-05)."""
    Property = apps.get_model('properties', 'Property')
    Building = apps.get_model('properties', 'Building')
    Floor = apps.get_model('properties', 'Floor')

    # RLS is FORCE-enabled on these tables (invariant 1) and this migration
    # runs outside any request, so there's no app.tenant_id GUC set — without
    # is_super_admin every query here would silently see zero rows.
    with tenant_context(is_super_admin=True):
        for prop in Property.objects.all():
            building = Building.objects.create(
                id=uuid.uuid4(), tenant_id=prop.tenant_id, property=prop,
                name='Main Building', order=0,
            )
            Floor.objects.filter(property_id=prop.id).update(building=building)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0003_propertyimage'),
    ]

    operations = [
        migrations.CreateModel(
            name='Building',
            fields=[
                ('tenant_id', models.UUIDField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=100)),
                ('order', models.PositiveSmallIntegerField()),
                ('property', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='buildings', to='properties.property')),
            ],
            options={
                'db_table': 'buildings',
                'ordering': ['order'],
            },
        ),
        migrations.AddConstraint(
            model_name='building',
            constraint=models.UniqueConstraint(fields=('property', 'order'), name='unique_building_order_per_property'),
        ),
        enable_rls('buildings'),

        migrations.AddField(
            model_name='floor',
            name='building',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='floors', to='properties.building'),
        ),
        migrations.RunPython(create_default_buildings, noop_reverse),

        migrations.RemoveConstraint(model_name='floor', name='unique_floor_order_per_property'),
        migrations.RemoveField(model_name='floor', name='property'),
        migrations.AlterField(
            model_name='floor',
            name='building',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='floors', to='properties.building'),
        ),
        migrations.AddConstraint(
            model_name='floor',
            constraint=models.UniqueConstraint(fields=('building', 'order'), name='unique_floor_order_per_building'),
        ),
    ]
