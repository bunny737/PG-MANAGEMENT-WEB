"""Scheduled by django-celery-beat PeriodicTasks seeded in migrations 0010 and 0013."""
from celery import shared_task

from .services import process_invoice_issuing, process_razorpay_cancellations


@shared_task
def retry_razorpay_cancellations():
    return process_razorpay_cancellations()


@shared_task
def retry_invoice_issuing():
    return process_invoice_issuing()
