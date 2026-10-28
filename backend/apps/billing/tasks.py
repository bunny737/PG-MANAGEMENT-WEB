"""Scheduled by the django-celery-beat PeriodicTask seeded in migration 0008."""
from celery import shared_task

from .autobilling import run_auto_billing


@shared_task
def run_auto_billing_task():
    return run_auto_billing()
