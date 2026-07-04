"""Bed-transfer orchestration (PRD Module 7 Transfer Management), plus the
vacating/absconded/blacklist workflows (PRD Module 11).

Kept out of the serializer/view because these actions have several coupled
side effects: freeing/occupying beds (which cascade to room-status sync in
Module 02), mutating the resident's Allocation or status, and freezing a
history row — all of which must succeed or fail together.
"""
import calendar
from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.audit import log as audit_log
from apps.properties.models import Bed, PropertySettings

from .models import AbscondedRecord, Admission, Allocation, BlacklistEntry, Resident, Transfer, Vacate


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


def add_one_month(d):
    """Same-day-next-month date arithmetic (PRD 'Notice Date + 1 month'),
    clamped to the last valid day when the target month is shorter
    (e.g. 31 Jan -> 28/29 Feb)."""
    month = d.month + 1
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


@transaction.atomic
def give_notice(*, resident, notice_given_date, actor, request=None):
    """Step 1 of the vacating workflow (PRD Module 11): Active -> Notice
    Period, expected_vacate_date auto-calculated as notice + 1 month."""
    before_status = resident.status
    vacate = Vacate.objects.create(
        tenant_id=resident.tenant_id, resident=resident,
        notice_given_date=notice_given_date,
        expected_vacate_date=add_one_month(notice_given_date),
    )
    resident.status = Resident.Status.NOTICE_PERIOD
    resident.save(update_fields=['status', 'updated_at'])

    audit_log.record(
        action='resident.notice_given', actor=actor, obj=vacate,
        after={'notice_given_date': notice_given_date.isoformat(),
               'expected_vacate_date': vacate.expected_vacate_date.isoformat()},
        request=request,
    )
    audit_log.record(
        action='resident.status_changed', actor=actor, obj=resident,
        before={'status': before_status}, after={'status': resident.status},
        request=request,
    )
    return vacate


@transaction.atomic
def finalize_vacate(*, vacate, actual_vacate_date, maintenance_deduction, maintenance_deduction_note,
                    refund_date, refund_mode, refund_note, actor, request=None):
    """Step 2 of the vacating workflow (PRD Module 11): move-out settlement —
    Notice Period -> Vacated, bed freed immediately, refund computed from the
    admission's advance minus the maintenance deduction."""
    resident = vacate.resident
    before_status = resident.status

    vacate.actual_vacate_date = actual_vacate_date
    vacate.maintenance_deduction = maintenance_deduction
    vacate.maintenance_deduction_note = maintenance_deduction_note
    vacate.refund_date = refund_date
    vacate.refund_mode = refund_mode
    vacate.refund_note = refund_note
    vacate.settled_by = actor
    vacate.save()

    bed = resident.allocation.allocated_bed
    bed.status = Bed.Status.AVAILABLE
    bed.save()  # also syncs the room's status (Module 02)

    resident.status = Resident.Status.VACATED
    resident.save(update_fields=['status', 'updated_at'])

    audit_log.record(
        action='resident.vacated', actor=actor, obj=vacate,
        after={'actual_vacate_date': actual_vacate_date.isoformat(),
               'maintenance_deduction': str(maintenance_deduction),
               'refund_amount': str(vacate.refund_amount)},
        request=request,
    )
    audit_log.record(
        action='resident.status_changed', actor=actor, obj=resident,
        before={'status': before_status}, after={'status': resident.status},
        request=request,
    )
    return vacate


def outstanding_dues_for(resident):
    """Sum of balance_due across the resident's issued/partially_paid invoices
    (Module 08/09). Deferred import: apps.billing imports apps.residents at
    module level, so importing it back at this module's top would be circular."""
    from apps.billing.models import Invoice

    invoices = Invoice.objects.filter(
        resident=resident, status__in=(Invoice.Status.ISSUED, Invoice.Status.PARTIALLY_PAID),
    )
    return sum((invoice.balance_due for invoice in invoices), Decimal('0.00'))


@transaction.atomic
def mark_absconded(*, resident, absconded_date, last_seen_date, absconded_note, actor, request=None):
    """PRD Module 11 'Absconded Resident Workflow': bed freed immediately (no
    notice period), advance forfeited and applied against outstanding dues,
    any remainder recorded as outstanding (owner can write it off later)."""
    before_status = resident.status
    advance = resident.admission.advance_amount
    outstanding = outstanding_dues_for(resident)
    applied = min(advance, outstanding)
    remaining = outstanding - applied

    record = AbscondedRecord.objects.create(
        tenant_id=resident.tenant_id, resident=resident,
        absconded_date=absconded_date, last_seen_date=last_seen_date, absconded_note=absconded_note,
        advance_applied_to_dues=applied, remaining_dues=remaining, marked_by=actor,
    )

    bed = resident.allocation.allocated_bed
    bed.status = Bed.Status.AVAILABLE
    bed.save()  # also syncs the room's status (Module 02)

    resident.status = Resident.Status.ABSCONDED
    resident.save(update_fields=['status', 'updated_at'])

    audit_log.record(
        action='resident.absconded', actor=actor, obj=record,
        after={'absconded_date': absconded_date.isoformat(), 'advance_applied_to_dues': str(applied),
               'remaining_dues': str(remaining)},
        request=request,
    )
    audit_log.record(
        action='resident.status_changed', actor=actor, obj=resident,
        before={'status': before_status}, after={'status': resident.status},
        request=request,
    )
    return record


def write_off_dues(*, absconded_record, note, actor, request=None):
    """Management decision to record remaining absconded dues as irrecoverable
    (PRD: 'owner can write off with mandatory note')."""
    before = {'dues_recovery_status': absconded_record.dues_recovery_status}
    absconded_record.dues_recovery_status = AbscondedRecord.DuesRecoveryStatus.WRITTEN_OFF
    absconded_record.dues_written_off_by = actor
    absconded_record.dues_written_off_note = note
    absconded_record.save(update_fields=[
        'dues_recovery_status', 'dues_written_off_by', 'dues_written_off_note', 'updated_at',
    ])
    audit_log.record(
        action='absconded.dues_written_off', actor=actor, obj=absconded_record,
        before=before, after={'dues_recovery_status': absconded_record.dues_recovery_status, 'note': note},
        request=request,
    )
    return absconded_record


@transaction.atomic
def confirm_blacklist(*, resident, reason, actor, request=None):
    """PRD Module 11 'Blacklisting': never automatic — Owner/Manager
    explicitly confirms. Phone/Aadhaar are snapshotted into a tenant-wide
    BlacklistEntry so a future registration anywhere in the tenant can warn,
    even from a property the confirming actor isn't otherwise scoped to."""
    before_status = resident.status
    entry = BlacklistEntry.objects.create(
        tenant_id=resident.tenant_id, resident=resident, phone=resident.phone,
        aadhaar_number=resident.aadhaar_number, reason=reason, confirmed_by=actor,
    )
    resident.status = Resident.Status.BLACKLISTED
    resident.save(update_fields=['status', 'updated_at'])

    audit_log.record(
        action='resident.blacklisted', actor=actor, obj=entry,
        after={'phone': entry.phone, 'reason': reason}, request=request,
    )
    audit_log.record(
        action='resident.status_changed', actor=actor, obj=resident,
        before={'status': before_status}, after={'status': resident.status},
        request=request,
    )
    return entry
