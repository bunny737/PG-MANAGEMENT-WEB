# Seeds the invoice-issuing sweep as an ordinary django-celery-beat PeriodicTask, so a
# Super Admin can retime or disable it from Django admin. An invoice is priced and saved
# as a draft inside the plan-change / cycle-close transaction and sent to Razorpay after
# it commits; this sweep sends any whose first attempt failed or never ran.
from django.db import migrations

TASK_NAME = 'subscriptions.retry_invoice_issuing'


def seed(apps, schema_editor):
    IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

    every_10_minutes, _ = IntervalSchedule.objects.get_or_create(every=10, period='minutes')
    PeriodicTask.objects.get_or_create(
        name=TASK_NAME,
        defaults={
            'task': 'apps.subscriptions.tasks.retry_invoice_issuing',
            'interval': every_10_minutes,
            'enabled': True,
            'description': 'Issues draft subscription invoices to Razorpay that were not sent after commit.',
        },
    )


def unseed(apps, schema_editor):
    apps.get_model('django_celery_beat', 'PeriodicTask').objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0012_subscriptioninvoice_issue_attempts_and_more'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
