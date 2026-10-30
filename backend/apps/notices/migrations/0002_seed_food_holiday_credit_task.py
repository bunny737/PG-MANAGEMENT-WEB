# Seeds the daily food-holiday credit allocation (Module 24) as an ordinary
# django-celery-beat PeriodicTask, so a Super Admin can retime or disable it
# from Django admin. 05:30 IST — before the 06:00 automatic-billing sweep — it
# creates the credits of holidays that ended and puts pending ones on drafts.
from django.db import migrations

TASK_NAME = 'notices.allocate_food_holiday_credits'


def seed(apps, schema_editor):
    CrontabSchedule = apps.get_model('django_celery_beat', 'CrontabSchedule')
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

    # The timezone is part of the lookup (see billing 0008).
    daily_0530, _ = CrontabSchedule.objects.get_or_create(
        minute='30', hour='5', day_of_month='*', month_of_year='*', day_of_week='*',
        timezone='Asia/Kolkata',
    )
    PeriodicTask.objects.get_or_create(
        name=TASK_NAME,
        defaults={
            'task': 'apps.notices.tasks.allocate_food_holiday_credits_task',
            'crontab': daily_0530,
            'enabled': True,
            'description': 'Creates food-holiday credits for holidays that ended and puts pending credits on draft invoices.',
        },
    )


def unseed(apps, schema_editor):
    apps.get_model('django_celery_beat', 'PeriodicTask').objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('notices', '0001_initial'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
