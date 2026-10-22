# Free trial goes from 45 to 30 days (owner decision 2026-10-22). New databases get
# 30 from the field default; the existing platform_config row is moved too, but only
# if it still holds the old 45, so a value a Super Admin chose is never overwritten
# (invariant 10). Runs after the subscriptions seed (0006), which writes 45.
from django.db import migrations, models

OLD_TRIAL_DAYS = 45
NEW_TRIAL_DAYS = 30


def shorten_trial(apps, schema_editor):
    PlatformConfig = apps.get_model('core', 'PlatformConfig')
    PlatformConfig.objects.filter(trial_days=OLD_TRIAL_DAYS).update(trial_days=NEW_TRIAL_DAYS)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_contactmessage'),
        ('subscriptions', '0006_seed_basic_unlimited_plans'),
    ]

    operations = [
        migrations.AlterField(
            model_name='platformconfig',
            name='trial_days',
            field=models.PositiveIntegerField(default=NEW_TRIAL_DAYS),
        ),
        # Reverse is a no-op: restoring 45 would clobber later Super Admin edits.
        migrations.RunPython(shorten_trial, migrations.RunPython.noop),
    ]
