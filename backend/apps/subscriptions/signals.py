"""Feeds `BedLedgerEntry` from `Bed` writes (PER_BED_MONTHLY billing
prerequisite — see `BedLedgerEntry`'s docstring for why a ledger is needed
instead of counting the live `beds` table). Lives in `subscriptions`, not
`apps.properties`, so Module 02 stays untouched; wired up in
`SubscriptionsConfig.ready()`.
"""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from apps.properties.models import Bed

from .models import BedLedgerEntry


@receiver(post_save, sender=Bed)
def record_bed_added(sender, instance, created, **kwargs):
    if not created:
        return
    BedLedgerEntry.objects.create(
        tenant_id=instance.tenant_id, bed_id=instance.id,
        event=BedLedgerEntry.Event.ADDED, occurred_at=timezone.now(),
    )


@receiver(post_delete, sender=Bed)
def record_bed_removed(sender, instance, **kwargs):
    BedLedgerEntry.objects.create(
        tenant_id=instance.tenant_id, bed_id=instance.id,
        event=BedLedgerEntry.Event.REMOVED, occurred_at=timezone.now(),
    )
