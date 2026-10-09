# Seeds the daily retention purge as an ordinary django-celery-beat
# PeriodicTask, so a Super Admin can retime or disable it from Django admin.
from django.db import migrations

TASK_NAME = 'devices.purge_stale_app_data'


def seed(apps, schema_editor):
    CrontabSchedule = apps.get_model('django_celery_beat', 'CrontabSchedule')
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

    daily_3_30am, _ = CrontabSchedule.objects.get_or_create(
        minute='30', hour='3', day_of_month='*', month_of_year='*', day_of_week='*',
        defaults={'timezone': 'Asia/Kolkata'},
    )
    PeriodicTask.objects.get_or_create(
        name=TASK_NAME,
        defaults={
            'task': 'apps.devices.tasks.purge_stale_app_data',
            'crontab': daily_3_30am,
            'enabled': True,
            'description': 'Deletes app installs unseen for APP_INSTALLATION_RETENTION_DAYS and old install history.',
        },
    )


def unseed(apps, schema_editor):
    apps.get_model('django_celery_beat', 'PeriodicTask').objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0001_initial'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
