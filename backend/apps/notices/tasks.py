"""Scheduled by the django-celery-beat PeriodicTask seeded in migration 0002."""
from celery import shared_task

from .sweep import allocate_food_holiday_credits


@shared_task
def allocate_food_holiday_credits_task():
    return allocate_food_holiday_credits()
