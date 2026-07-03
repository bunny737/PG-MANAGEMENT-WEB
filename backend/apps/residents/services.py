"""Bed-transfer orchestration (PRD Module 7 Transfer Management).

Kept out of the serializer/view because a transfer has several coupled
side effects: freeing/occupying beds (which cascade to room-status sync in
Module 02), mutating the resident's Allocation, and freezing a Transfer
history row — all of which must succeed or fail together.
"""
from datetime import date

from django.db import transaction

from apps.audit import log as audit_log
from apps.properties.models import Bed, PropertySettings

from .models import Admission, Allocation, Transfer


def _first_of_next_month(d):
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def rent_effective_date(property_settings, transfer_date):
    """PRD Module 2B 'Room Transfer Rent Timing': Immediately => the transfer
    date itself; Next Billing Cycle => the 1st of the following month."""
    if property_settings.room_transfer_rent_timing == PropertySettings.RentChangeTiming.IMMEDIATE:
        return transfer_date
    return _first_of_next_month(transfer_date)


def default_new_rent(new_bed, resident):
    """Rack rate of the destination bed for the resident's contracted food
    preference — the pre-fill for a permanent transfer's new contracted rent."""
    with_food = resident.admission.food_preference == Admission.FoodPreference.WITH_FOOD
    return new_bed.rack_rate(with_food=with_food)


@transaction.atomic
def perform_transfer(*, allocation, new_bed, transfer_date, is_temporary, reason,
                     new_rent, expected_move_date, temporary_note, actor, request=None):
    resident = allocation.resident
    previous_bed = allocation.allocated_bed
    previous_rent = allocation.contracted_rent

    # Free the vacated bed and occupy the new one; each save() cascades to the
    # room-status sync built in Module 02.
    previous_bed.status = Bed.Status.AVAILABLE
    previous_bed.save()
    new_bed.status = Bed.Status.OCCUPIED
    new_bed.save()

    allocation.allocated_bed = new_bed

    if is_temporary:
        # Invariant 3: contracted rent (and the whole contracted deal) is
        # untouched — the resident keeps paying their contracted rent.
        resolved_new_rent = previous_rent
        allocation.is_temporary = True
        allocation.temporary_since = transfer_date
        allocation.expected_move_date = expected_move_date
        allocation.temporary_note = temporary_note or ''
        effective_date = transfer_date  # no rent change to schedule
    else:
        resolved_new_rent = new_rent if new_rent is not None else default_new_rent(new_bed, resident)
        allocation.contracted_rent = resolved_new_rent
        allocation.contracted_sharing_type = new_bed.room.sharing_type
        allocation.contracted_room_category = new_bed.room.category
        # A permanent move to any room clears the temporary flag (this is also
        # how a temporarily-placed resident is moved back to their proper type).
        allocation.is_temporary = False
        allocation.temporary_since = None
        allocation.expected_move_date = None
        allocation.temporary_note = ''
        settings_obj, _ = PropertySettings.objects.get_or_create(
            property=resident.property, defaults={'tenant_id': resident.tenant_id}
        )
        effective_date = rent_effective_date(settings_obj, transfer_date)

    allocation.save()

    transfer = Transfer.objects.create(
        tenant_id=allocation.tenant_id,
        resident=resident,
        previous_bed=previous_bed,
        new_bed=new_bed,
        is_temporary=is_temporary,
        reason=reason or '',
        transfer_date=transfer_date,
        previous_rent=previous_rent,
        new_rent=resolved_new_rent,
        rent_effective_date=effective_date,
        recorded_by=actor,
    )

    audit_log.record(
        action='resident.transferred', actor=actor, obj=transfer,
        before={'bed': str(previous_bed.id), 'contracted_rent': str(previous_rent)},
        after={'bed': str(new_bed.id), 'contracted_rent': str(resolved_new_rent),
               'is_temporary': is_temporary, 'rent_effective_date': effective_date.isoformat()},
        request=request,
    )
    return transfer


def create_initial_allocation(admission):
    """Called from Module 05 check-in: a checked-in resident is, by
    definition, allocated to the bed they were admitted into."""
    return Allocation.objects.create(
        tenant_id=admission.tenant_id,
        resident=admission.resident,
        allocated_bed=admission.bed,
        contracted_sharing_type=admission.contracted_sharing_type,
        contracted_room_category=admission.contracted_room_category,
        contracted_rent=admission.contracted_rent,
    )
