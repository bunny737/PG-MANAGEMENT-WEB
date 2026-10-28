"""Scheduled by the django-celery-beat PeriodicTasks seeded in migrations 0008 and 0009."""
from celery import shared_task

from .autobilling import retry_pending_summaries, run_auto_billing


@shared_task
def run_auto_billing_task():
    return run_auto_billing()


@shared_task
def retry_auto_billing_summaries_task():
    return retry_pending_summaries()
