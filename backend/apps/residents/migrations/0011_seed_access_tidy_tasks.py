# Seeds the two nightly resident-access housekeeping jobs (Module 26) as ordinary django-celery-beat
# PeriodicTasks, so a Super Admin can retime or disable them from Django admin. Same pattern as
# accounts.0010. Neither job decides who has access (that is checked on every request).
from django.db import migrations

TASKS = [
    ('residents.tidy_resident_access', 1, 'apps.residents.tasks.tidy_resident_access',
     'Marks resident app links and invites past their expiry as expired.'),
    ('accounts.purge_unverified_resident_accounts', 2, 'apps.accounts.tasks.purge_unverified_resident_accounts',
     'Removes resident app accounts that never verified their email.'),
]


def seed(apps, schema_editor):
    CrontabSchedule = apps.get_model('django_celery_beat', 'CrontabSchedule')
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
    for name, hour, task, description in TASKS:
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour=str(hour), day_of_month='*', month_of_year='*', day_of_week='*',
            timezone='Asia/Kolkata',
        )
        PeriodicTask.objects.get_or_create(
            name=name,
            defaults={'task': task, 'crontab': schedule, 'enabled': True, 'description': description},
        )


def unseed(apps, schema_editor):
    names = [name for name, *_ in TASKS]
    apps.get_model('django_celery_beat', 'PeriodicTask').objects.filter(name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('residents', '0010_resident_app_access'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
