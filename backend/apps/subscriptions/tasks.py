"""Scheduled by a django-celery-beat PeriodicTask seeded in migration 0010."""
from celery import shared_task

from .services import process_razorpay_cancellations


@shared_task
def retry_razorpay_cancellations():
    return process_razorpay_cancellations()
