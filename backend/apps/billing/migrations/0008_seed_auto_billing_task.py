# Seeds the daily automatic-billing sweep (Module 08) as an ordinary
# django-celery-beat PeriodicTask, so a Super Admin can retime or disable it
# from Django admin. 06:00 IST: issues the drafts due today, then drafts the
# cycles starting tomorrow.
from django.db import migrations

TASK_NAME = 'billing.auto_billing'


def seed(apps, schema_editor):
    CrontabSchedule = apps.get_model('django_celery_beat', 'CrontabSchedule')
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

    daily_6am, _ = CrontabSchedule.objects.get_or_create(
        minute='0', hour='6', day_of_month='*', month_of_year='*', day_of_week='*',
        defaults={'timezone': 'Asia/Kolkata'},
    )
    PeriodicTask.objects.get_or_create(
        name=TASK_NAME,
        defaults={
            'task': 'apps.billing.tasks.run_auto_billing_task',
            'crontab': daily_6am,
            'enabled': True,
            'description': 'Issues auto-drafted resident invoices due today and drafts the cycles starting tomorrow.',
        },
    )


def unseed(apps, schema_editor):
    apps.get_model('django_celery_beat', 'PeriodicTask').objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0007_auto_billing'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
