# Seeds the nightly account-deletion purge as an ordinary django-celery-beat PeriodicTask, so
# a Super Admin can retime or disable it from Django admin. 00:00 IST: scheduled_for is
# rounded up to a midnight, so a request is purged by exactly that night's run.
from django.db import migrations

TASK_NAME = 'accounts.purge_due_account_deletions'


def seed(apps, schema_editor):
    CrontabSchedule = apps.get_model('django_celery_beat', 'CrontabSchedule')
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

    midnight, _ = CrontabSchedule.objects.get_or_create(
        minute='0', hour='0', day_of_month='*', month_of_year='*', day_of_week='*',
        defaults={'timezone': 'Asia/Kolkata'},
    )
    PeriodicTask.objects.get_or_create(
        name=TASK_NAME,
        defaults={
            'task': 'apps.accounts.tasks.purge_due_account_deletions',
            'crontab': midnight,
            'enabled': True,
            'description': 'Permanently deletes accounts whose deletion request has passed its grace period.',
        },
    )


def unseed(apps, schema_editor):
    apps.get_model('django_celery_beat', 'PeriodicTask').objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_account_deletion'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
