# Seeds the cancellation retry sweep as an ordinary django-celery-beat PeriodicTask, so a
# Super Admin can retime or disable it from Django admin. It re-attempts every Razorpay
# subscription we have replaced or abandoned until Razorpay confirms it is cancelled.
from django.db import migrations

TASK_NAME = 'subscriptions.retry_razorpay_cancellations'


def seed(apps, schema_editor):
    IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

    every_10_minutes, _ = IntervalSchedule.objects.get_or_create(every=10, period='minutes')
    PeriodicTask.objects.get_or_create(
        name=TASK_NAME,
        defaults={
            'task': 'apps.subscriptions.tasks.retry_razorpay_cancellations',
            'interval': every_10_minutes,
            'enabled': True,
            'description': 'Retries cancelling replaced/abandoned Razorpay subscriptions so a tenant is never left double-billed.',
        },
    )


def unseed(apps, schema_editor):
    apps.get_model('django_celery_beat', 'PeriodicTask').objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0009_razorpay_subscription_ledger'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
