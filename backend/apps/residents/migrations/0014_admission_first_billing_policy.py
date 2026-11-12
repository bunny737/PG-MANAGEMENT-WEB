from django.db import migrations, models

import apps.core.periods


class Migration(migrations.Migration):

    dependencies = [
        ('residents', '0013_admission_advance_guards'),
    ]

    operations = [
        migrations.AddField(
            model_name='admission',
            name='first_billing_policy',
            field=models.CharField(
                choices=[
                    ('from_joining_date', 'From joining date'),
                    ('next_billing_cycle', 'Next billing cycle'),
                ],
                default='from_joining_date',
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name='admission',
            name='billing_enrolled_on',
            field=models.DateField(default=apps.core.periods.local_today),
        ),
        migrations.AddField(
            model_name='admission',
            name='auto_apply_advance_to_first_invoice',
            field=models.BooleanField(default=True),
        ),
    ]
