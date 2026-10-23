# Seeds the beat schedules the Module 14 V2 scheduling design depends on:
# a daily crontab sweep for trial-expiry reminders (replaces the original
# MVP's "run this via external cron" instruction — see
# send_trial_expiry_reminders management command, kept as a manual/ops
# fallback), and a 1-minute interval poll for one-off ScheduledNotification
# rows. Both are ordinary PeriodicTask rows a Super Admin can retime via
# Django admin afterwards — this migration only seeds sane defaults.
from django.db import migrations


def seed_periodic_tasks(apps, schema_editor):
    CrontabSchedule = apps.get_model('django_celery_beat', 'CrontabSchedule')
    IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

    daily_9am, _ = CrontabSchedule.objects.get_or_create(
        minute='0', hour='9', day_of_month='*', month_of_year='*', day_of_week='*',
        defaults={'timezone': 'Asia/Kolkata'},
    )
    PeriodicTask.objects.get_or_create(
        name='notifications.trial_expiry_reminders_sweep',
        defaults={
            'task': 'apps.notifications.tasks.run_due_sweep',
            'crontab': daily_9am,
            'kwargs': '{"sweep_key": "trial_expiry_reminders"}',
            'enabled': True,
            'description': 'Daily scan for tenants due a trial-expiry reminder email (PRD Module 18).',
        },
    )

    every_minute, _ = IntervalSchedule.objects.get_or_create(every=1, period='minutes')
    PeriodicTask.objects.get_or_create(
        name='notifications.dispatch_scheduled_notifications',
        defaults={
            'task': 'apps.notifications.tasks.dispatch_scheduled_notifications',
            'interval': every_minute,
            'enabled': True,
            'description': 'Sends any due one-off ScheduledNotification rows.',
        },
    )


def remove_periodic_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
    PeriodicTask.objects.filter(
        name__in=[
            'notifications.trial_expiry_reminders_sweep',
            'notifications.dispatch_scheduled_notifications',
        ],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0003_seed_notification_templates'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(seed_periodic_tasks, remove_periodic_tasks),
    ]
