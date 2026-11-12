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

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError

from apps.audit import log as audit_log
from apps.audit.models import AuditLog
from apps.core.idempotency import key_reused
from apps.properties.models import Bed, PropertySettings

from .access import record_exit
from .models import (
    AbscondedRecord,
    Admission,
    Allocation,
    BlacklistEntry,
    DepositPayment,
    Resident,
    Transfer,
    Vacate,
)


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
    previous_rent = allocation.contracted_rent

    # Lock both beds before touching them. The serializer checked
    # `new_bed.status == AVAILABLE`, but without a lock two concurrent transfers
    # (or a transfer racing a check-in) could both take the same bed. Lock in a
    # deterministic order (by id) to avoid deadlocks, then re-check.
    bed_ids = {allocation.allocated_bed_id, new_bed.id}
    locked_beds = {
        bed.id: bed
        for bed in Bed.objects.select_for_update(of=('self',))
        .filter(pk__in=bed_ids).order_by('id')
    }
    previous_bed = locked_beds[allocation.allocated_bed_id]
    new_bed = locked_beds[new_bed.id]
    if new_bed.status != Bed.Status.AVAILABLE:
        raise ValidationError(
            {'new_bed': _('This bed is not available.')}, code='bed_not_available'
        )

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


def create_initial_deposit_payment(admission, *, actor):
    """The deposit collected at check-in becomes the first ledger row. Called inside the
    admission-create transaction, after the admission row exists."""
    if admission.security_deposit_amount <= 0:
        return None
    return DepositPayment.objects.create(
        tenant_id=admission.tenant_id, admission=admission, amount=admission.security_deposit_amount,
        payment_date=admission.security_deposit_collected_date, payment_mode=admission.security_deposit_mode,
        recorded_by=actor,
    )


def deposit_payment_matches(existing, *, admission_id, amount, payment_date, payment_mode, reference):
    """True when a request carries exactly the inputs `existing` persisted."""
    return (
        str(existing.admission_id) == str(admission_id)
        and existing.amount == amount
        and existing.payment_date == payment_date
        and existing.payment_mode == payment_mode
        and existing.reference == reference
    )


def find_replayed_deposit_payment(*, tenant_id, idempotency_key, **inputs):
    """The payment an earlier request with this key created, or None. A key reused with any
    different persisted input is a client bug: 409."""
    existing = DepositPayment.objects.filter(tenant_id=tenant_id, idempotency_key=idempotency_key).first()
    if existing is None:
        return None
    if not deposit_payment_matches(existing, **inputs):
        raise key_reused()
    return existing


@transaction.atomic
def record_deposit_payment(*, admission, amount, payment_date, payment_mode, reference='',
                           actor, request=None, idempotency_key=None):
    """Record a later collection of the security deposit (Module 10, 2026-11-01).

    Lock order is Resident -> Admission (the resident first, like every workflow that touches
    the resident; see `lock_resident`). The serializer pre-checks the same rules for a friendly
    error, but only the checks made under these locks are authoritative: two concurrent
    payments each within the pending amount could otherwise overpay.

    With an `idempotency_key`, a retry of a request that already succeeded returns the original
    payment (`replayed = True`) instead of failing the pending check or recording it twice."""
    resident = lock_resident(admission.resident)
    admission = Admission.objects.select_for_update(of=('self',)).get(pk=admission.pk)
    inputs = dict(
        admission_id=admission.pk, amount=amount, payment_date=payment_date,
        payment_mode=payment_mode, reference=reference,
    )

    if idempotency_key:
        existing = find_replayed_deposit_payment(
            tenant_id=admission.tenant_id, idempotency_key=idempotency_key, **inputs,
        )
        if existing is not None:
            existing.replayed = True
            return existing

    if resident.status not in (Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD):
        raise ValidationError(
            {'resident': _('A deposit can only be collected from a resident who is Active or on Notice Period.')},
            code='resident_not_current',
        )
    pending = admission.security_deposit_pending
    if amount > pending:
        raise ValidationError(
            {'amount': _('This exceeds the pending security deposit of %(pending)s.') % {'pending': pending}},
            code='deposit_overpaid',
        )

    try:
        with transaction.atomic():
            payment = DepositPayment.objects.create(
                tenant_id=admission.tenant_id, admission=admission, amount=amount,
                payment_date=payment_date, payment_mode=payment_mode, reference=reference,
                recorded_by=actor, idempotency_key=idempotency_key,
            )
    except IntegrityError:
        # unique_deposit_payment_idempotency_key: lost a race to a request with the same key.
        if not idempotency_key:
            raise
        existing = find_replayed_deposit_payment(
            tenant_id=admission.tenant_id, idempotency_key=idempotency_key, **inputs,
        )
        if existing is None:
            raise
        existing.replayed = True
        return existing
    payment.replayed = False

    before = admission.security_deposit_amount
    admission.security_deposit_amount = before + amount
    admission.save(update_fields=['security_deposit_amount', 'updated_at'])
    audit_log.record(
        action='deposit.payment_recorded', actor=actor, tenant_id=admission.tenant_id, obj=payment,
        before={'security_deposit_collected': str(before)},
        after={'resident': str(resident.id), 'amount': str(amount), 'mode': payment_mode,
               'security_deposit_collected': str(admission.security_deposit_amount),
               'security_deposit_pending': str(admission.security_deposit_pending)},
        request=request,
    )
    return payment


def lock_resident(resident):
    """Re-read a resident under a row lock, for the exit/status workflows.

    Lock order for every workflow that writes `Resident.status` is
    **Resident -> Vacate -> Bed -> Subscription**: take this first, validate the
    re-read `status` inside the lock, then touch the vacate, then the bed, and
    let check_resident_limit take the Subscription last. Everything that mutates
    `Resident.status` uses it, so two of them can't interleave on the same
    resident (e.g. cancel-notice racing finalize, or mark-absconded landing on
    a resident someone else just reactivated).

    `of=('self',)`: lock only the residents row. The callers' querysets
    select_related nullable admission/allocation joins, and PostgreSQL refuses
    FOR UPDATE on the nullable side of an outer join — the same reason
    subscriptions.services._subscription_for_limit_check locks a join-free row.

    Used by the services in this module, ResidentViewSet.change_status and
    AdmissionViewSet.perform_create. Admission once locked Bed -> Subscription
    and only touched the resident at the end, which deadlocked against
    change_status (Resident -> Subscription); see test_lock_ordering.py and the
    Module 10 spec. Any new code that writes Resident.status must start here.
    """
    return (
        Resident.objects.select_for_update(of=('self',)).get(pk=resident.pk)
    )


@transaction.atomic
def give_notice(*, resident, notice_given_date, actor, request=None):
    """Step 1 of the vacating workflow (PRD Module 11): Active -> Notice
    Period, expected_vacate_date auto-calculated as notice + 1 month."""
    # Re-check under the lock: the serializer's checks ran unlocked, so two
    # concurrent give-notice calls could both pass them and race the
    # `unique_open_vacate_per_resident` constraint into an IntegrityError (a
    # 500) instead of a clean validation error.
    resident = lock_resident(resident)
    if not resident.can_transition_to(Resident.Status.NOTICE_PERIOD):
        raise ValidationError(
            {'resident': _('Only an active resident can give notice to vacate.')},
            code='resident_not_active',
        )
    if resident.open_vacate is not None:
        raise ValidationError(
            {'resident': _('This resident already has a vacate record.')},
            code='vacate_already_exists',
        )

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
    admission's security deposit minus the maintenance deduction."""
    # Settings -> Resident -> Vacate lock order (see lock_resident; Settings
    # first serializes the food-holiday credits settled here with every other
    # credit change in the property — Module 24). Re-check everything inside
    # the locks: the view's guards run unlocked, so two concurrent finalize
    # calls could both pass them and double-run the settlement (double refund
    # audit, double bed-free), and a finalize racing a cancel-notice could
    # settle a notice that was just withdrawn.
    from apps.billing.services import lock_property_settings
    from apps.notices import credits as food_credits

    lock_property_settings(vacate.resident.property_id, vacate.tenant_id)
    resident = lock_resident(vacate.resident)
    vacate = Vacate.objects.select_for_update().get(pk=vacate.pk)
    # Lock Admission right after Vacate (Settings -> Resident -> Vacate ->
    # Admission) so finalize_vacate cannot race adjust_from_advance or
    # delete_payment on an advance adjustment.
    Admission.objects.select_for_update(of=('self',)).get(resident=resident)
    if vacate.is_settled:
        raise ValidationError(
            {'detail': _('This vacate has already been settled.')}, code='already_settled'
        )
    if vacate.is_cancelled:
        raise ValidationError(
            {'detail': _('This notice was cancelled and cannot be settled.')},
            code='already_cancelled',
        )
    # Without this the resident's status is set to Vacated unconditionally,
    # which would drive an out-of-graph transition (e.g. Active -> Vacated) for
    # any resident who is no longer in their notice period.
    if not resident.can_transition_to(Resident.Status.VACATED):
        raise ValidationError(
            {'detail': _('Only a resident in their notice period can be settled.')},
            code='resident_not_in_notice_period',
        )

    before_status = resident.status

    # Food-holiday credits (Module 24): owed days are paid with the refund;
    # days already credited on an issued invoice after the move-out are clawed
    # back, as far as the refund can absorb.
    plan = food_credits.plan_exit(resident, through=actual_vacate_date)
    credit, clawback, recovered, unrecovered = food_credits.vacate_amounts(
        vacate, maintenance_deduction=maintenance_deduction, plan=plan,
    )

    vacate.actual_vacate_date = actual_vacate_date
    vacate.maintenance_deduction = maintenance_deduction
    vacate.maintenance_deduction_note = maintenance_deduction_note
    vacate.refund_date = refund_date
    vacate.refund_mode = refund_mode
    vacate.refund_note = refund_note
    vacate.settled_by = actor
    vacate.food_holiday_credit = credit
    vacate.food_holiday_clawback_calculated = clawback
    vacate.food_holiday_clawback_recovered = recovered
    vacate.food_holiday_clawback_unrecovered = unrecovered
    vacate.save()
    food_credits.apply_exit(plan, resident, vacate=vacate, actor=actor, request=request)

    bed = resident.allocation.allocated_bed
    bed.status = Bed.Status.AVAILABLE
    bed.save()  # also syncs the room's status (Module 02)

    resident.status = Resident.Status.VACATED
    resident.save(update_fields=['status', 'updated_at'])
    record_exit(resident)  # starts the app-access window (Module 26)

    audit_log.record(
        action='resident.vacated', actor=actor, obj=vacate,
        after={'actual_vacate_date': actual_vacate_date.isoformat(),
               'maintenance_deduction': str(maintenance_deduction),
               'food_holiday_credit': str(credit),
               'food_holiday_clawback_calculated': str(clawback),
               'food_holiday_clawback_recovered': str(recovered),
               'food_holiday_clawback_unrecovered': str(unrecovered),
               'refund_amount': str(vacate.refund_amount)},
        request=request,
    )
    audit_log.record(
        action='resident.status_changed', actor=actor, obj=resident,
        before={'status': before_status}, after={'status': resident.status},
        request=request,
    )
    return vacate


def settlement_preview(*, vacate, maintenance_deduction, actual_vacate_date=None):
    """Move-out settlement breakdown for a not-yet-finalized vacate (owner
    request 2026-10-26: a checkout screen showing the refund before staff
    confirm it). A non-locking, point-in-time estimate — unlike
    `finalize_vacate` it takes no row lock, mutates nothing and writes no
    audit entry, so a concurrent finalize/cancel can make this figure stale
    between the preview and the real settlement. That's accepted: the real
    settlement (`finalize_vacate`) re-checks everything under its own locks
    (see lock_resident there), so a stale preview can never cause a wrong
    refund — it can only show a staff member a number that's a few seconds
    old, which they'd see anyway if they reloaded the screen.

    `outstanding_dues` is informational only (owner decision 2026-10-26) —
    unlike `mark_absconded`, a normal vacate never nets dues against the
    refund; the deposit/advance math is exactly `Vacate.refund_for`.

    Food-holiday figures (Module 24) come from the same read-only plan
    `finalize_vacate` applies, for `actual_vacate_date` (default: the expected
    vacate date), so the preview and the settlement can't disagree."""
    from apps.notices import credits as food_credits

    through = actual_vacate_date or vacate.expected_vacate_date
    plan = food_credits.plan_exit(vacate.resident, through=through)
    credit, clawback, recovered, unrecovered = food_credits.vacate_amounts(
        vacate, maintenance_deduction=maintenance_deduction, plan=plan,
    )
    return {
        'security_deposit_amount': vacate.resident.admission.security_deposit_amount,
        'advance_amount': vacate.resident.admission.advance_amount,
        'advance_applied_amount': vacate.resident.admission.advance_applied_amount,
        'advance_refundable': vacate.resident.admission.advance_refundable,
        'maintenance_deduction': maintenance_deduction,
        'actual_vacate_date': through,
        'food_holiday_credit': credit,
        'food_holiday_clawback_calculated': clawback,
        'food_holiday_clawback_recovered': recovered,
        'food_holiday_clawback_unrecovered': unrecovered,
        'refund_amount': vacate.refund_for(
            maintenance_deduction, food_holiday_credit=credit, clawback_recovered=recovered,
        ),
        'outstanding_dues': outstanding_dues_for(vacate.resident),
    }


@transaction.atomic
def cancel_notice(*, vacate, cancelled_date, cancellation_reason, actor, request=None):
    """Withdraw a notice to vacate: Notice Period -> Active (owner request
    2026-10-07). The resident changed their mind and stays on.

    Deliberately touches nothing but the vacate row and the resident's status:

    - The **bed** was never released (give_notice doesn't touch it; only
      finalize_vacate does), so there is nothing to re-occupy.
    - The **Allocation** — and with it `contracted_rent` — is untouched.
      Invariant 2: the contracted rent stays as snapshotted at admission and is
      never re-derived from the room's current rack rate.
    - **Billing** already treats Notice Period exactly like Active, so no
      invoice, proration or plan-limit work is needed either way.
    - The **deposit/advance** are only paid out at finalize, so nothing to
      reverse.

    The row is kept as history rather than deleted; a later notice creates a
    new Vacate (`unique_open_vacate_per_resident` allows it once this one is
    closed).
    """
    # Resident -> Vacate lock order (see lock_resident).
    resident = lock_resident(vacate.resident)
    vacate = Vacate.objects.select_for_update().get(pk=vacate.pk)
    if vacate.is_settled:
        raise ValidationError(
            {'detail': _('This vacate has already been settled.')}, code='already_settled'
        )
    if vacate.is_cancelled:
        raise ValidationError(
            {'detail': _('This notice has already been cancelled.')}, code='already_cancelled'
        )
    if resident.status != Resident.Status.NOTICE_PERIOD:
        raise ValidationError(
            {'detail': _('Only a resident in their notice period can cancel notice.')},
            code='resident_not_in_notice_period',
        )
    # Re-validated here, not just in the serializer, so a direct service call
    # (seed scripts, management commands) can't record an impossible date.
    if cancelled_date < vacate.notice_given_date:
        raise ValidationError(
            {'cancelled_date': _('Cancellation cannot predate the notice.')},
            code='cancelled_before_notice',
        )
    if cancelled_date > timezone.localdate():
        raise ValidationError(
            {'cancelled_date': _('Cancellation date cannot be in the future.')},
            code='cancelled_date_in_future',
        )
    if not (cancellation_reason or '').strip():
        raise ValidationError(
            {'cancellation_reason': _('A reason is required to cancel notice.')},
            code='reason_required',
        )

    before_status = resident.status

    vacate.cancelled_date = cancelled_date
    vacate.cancellation_reason = cancellation_reason
    vacate.cancelled_by = actor
    vacate.save(update_fields=[
        'cancelled_date', 'cancellation_reason', 'cancelled_by', 'updated_at',
    ])

    resident.status = Resident.Status.ACTIVE
    resident.save(update_fields=['status', 'updated_at'])

    audit_log.record(
        action='resident.notice_cancelled', actor=actor, obj=vacate,
        before={'notice_given_date': vacate.notice_given_date.isoformat(),
                'expected_vacate_date': vacate.expected_vacate_date.isoformat()},
        after={'cancelled_date': cancelled_date.isoformat(),
               'cancellation_reason': cancellation_reason},
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
    module level, so importing it back at this module's top would be circular.

    `balance_due` is `total - amount_paid`, each computed in Python from
    `line_items.all()`/`payments.all()` (billing/models.py) rather than
    stored — without prefetching, that's 1 query per invoice for each of the
    two, i.e. O(N) queries for N invoices. Originally only reached from
    `mark_absconded` (one-off, non-interactive), it's now also called from
    `settlement_preview` on every checkout-screen request, so the N+1 is
    worth avoiding here rather than in each caller."""
    from apps.billing.models import Invoice

    invoices = Invoice.objects.filter(
        resident=resident, status__in=(Invoice.Status.ISSUED, Invoice.Status.PARTIALLY_PAID),
    ).prefetch_related('line_items', 'payments')
    return sum((invoice.balance_due for invoice in invoices), Decimal('0.00'))


@transaction.atomic
def mark_absconded(*, resident, absconded_date, last_seen_date, absconded_note, actor, request=None):
    """PRD Module 11 'Absconded Resident Workflow': bed freed immediately (no
    notice period), security deposit forfeited and applied against outstanding dues,
    any remainder recorded as outstanding (owner can write it off later)."""
    # Settings -> Resident lock (see lock_resident; Settings first for the
    # food-holiday credits settled here — Module 24) + re-check: Active is now
    # reachable by cancelling a notice, so an unlocked read here could mark a
    # resident absconded off a status another request had just changed.
    from apps.billing.services import lock_property_settings
    from apps.notices import credits as food_credits

    lock_property_settings(resident.property_id, resident.tenant_id)
    resident = lock_resident(resident)
    if not resident.can_transition_to(Resident.Status.ABSCONDED):
        raise ValidationError(
            {'resident': _('Only an active resident can be marked absconded.')},
            code='resident_not_active',
        )

    before_status = resident.status
    # Settings -> Resident -> Admission (serialize against advance adjustments/reversals).
    admission = Admission.objects.select_for_update(of=('self',)).get(resident=resident)
    # Food-holiday credit still owed joins the forfeited pool; days already
    # credited on an issued invoice after the abscond date are added to the
    # dues (owner decisions 2026-10-30).
    plan = food_credits.plan_exit(resident, through=absconded_date)
    # An unapplied advance surplus is forfeited together with the deposit.
    deposit = food_credits.check_amount(
        admission.security_deposit_amount + admission.advance_refundable + plan.credit_total,
        'deposit_applied_to_dues',
    )
    outstanding = food_credits.check_amount(
        outstanding_dues_for(resident) + plan.clawback_total, 'remaining_dues',
    )
    applied = min(deposit, outstanding)
    remaining = outstanding - applied

    record = AbscondedRecord.objects.create(
        tenant_id=resident.tenant_id, resident=resident,
        absconded_date=absconded_date, last_seen_date=last_seen_date, absconded_note=absconded_note,
        deposit_applied_to_dues=applied, remaining_dues=remaining, marked_by=actor,
        food_holiday_credit=plan.credit_total, food_holiday_clawback=plan.clawback_total,
    )
    food_credits.apply_exit(plan, resident, absconded_record=record, actor=actor, request=request)

    bed = resident.allocation.allocated_bed
    bed.status = Bed.Status.AVAILABLE
    bed.save()  # also syncs the room's status (Module 02)

    resident.status = Resident.Status.ABSCONDED
    resident.save(update_fields=['status', 'updated_at'])
    record_exit(resident)  # starts the app-access window (Module 26)

    audit_log.record(
        action='resident.absconded', actor=actor, obj=record,
        after={'absconded_date': absconded_date.isoformat(), 'deposit_applied_to_dues': str(applied),
               'remaining_dues': str(remaining), 'food_holiday_credit': str(plan.credit_total),
               'food_holiday_clawback': str(plan.clawback_total)},
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
    # Resident lock (see lock_resident) + re-check, so a blacklist can't land on
    # a status another request changed under it (e.g. a notice just cancelled,
    # which takes the resident out of the Notice Period -> Blacklisted edge).
    resident = lock_resident(resident)
    if not resident.can_transition_to(Resident.Status.BLACKLISTED):
        raise ValidationError(
            {'resident': _('This resident cannot be blacklisted from their current status.')},
            code='invalid_status_transition',
        )

    before_status = resident.status
    entry = BlacklistEntry.objects.create(
        tenant_id=resident.tenant_id, resident=resident, phone=resident.phone,
        aadhaar_number=resident.aadhaar_number, reason=reason, confirmed_by=actor,
    )
    resident.status = Resident.Status.BLACKLISTED
    resident.save(update_fields=['status', 'updated_at'])
    record_exit(resident)  # a no-op for access already on the clock: Absconded -> Blacklisted never extends it

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


def build_activity_timeline(resident):
    """Aggregates a resident's lifecycle into one chronological feed (PRD
    Module 22). Computed entirely from records already built by Modules
    04-12 — no new table. Reverse relations (resident.invoices,
    resident.complaints, ...) are used instead of importing those apps'
    models directly, so this stays a leaf function with no risk of the
    circular-import issues other cross-app service functions in this file
    work around (e.g. outstanding_dues_for's deferred Invoice import).

    Same-day events are ordered by a fixed per-kind weight (the `add()` calls
    below, in narrative order), not insertion order, so a day with several
    events (e.g. Absconded + Advance Forfeited) always reads sensibly — note
    Notice Given/Cancelled can legitimately fall on the same day.

    The notice sequence can repeat: cancelling a notice returns the resident to
    Active, so a resident may have several Vacate rows and the feed shows each
    Notice Given (-> Notice Cancelled) pair before whichever notice finally
    settles."""
    events = []

    def add(event_date, weight, label, detail=''):
        if event_date is None:
            return
        events.append({'date': event_date, '_weight': weight, 'event': label, 'detail': detail})

    add(timezone.localtime(resident.created_at).date(), 0, _('Inquiry Received'))

    reserved_log = AuditLog.objects.filter(
        object_type='Resident', object_id=str(resident.id),
        action='resident.status_changed', after__status=Resident.Status.RESERVED,
    ).order_by('created_at').first()
    if reserved_log:
        add(timezone.localtime(reserved_log.created_at).date(), 1, _('Room Reserved'))

    admission = getattr(resident, 'admission', None)
    if admission is not None:
        # One atomic action in this system (Module 05: admission == check-in)
        # — represented as one entry, not the PRD example's two separate lines.
        add(
            admission.joining_date, 2, _('Admission Completed — Checked In'),
            _('Room %(room)s (%(bed)s)') % {
                'room': admission.bed.room.room_number, 'bed': admission.bed.bed_number,
            },
        )

    for invoice in resident.invoices.all().prefetch_related('payments'):
        if invoice.issue_date:
            add(invoice.issue_date, 3, _('Invoice Generated'), _('Total ₹%(total)s') % {'total': invoice.total})
        if invoice.status != invoice.Status.PAID and invoice.is_overdue(date.today()):
            add(
                invoice.due_date, 5, _('Invoice Overdue'),
                _('Balance due ₹%(balance)s') % {'balance': invoice.balance_due},
            )

        payments = sorted(invoice.payments.all(), key=lambda p: (p.payment_date, p.created_at))
        running_total = Decimal('0.00')
        for index, payment in enumerate(payments):
            running_total += payment.amount
            if payment.is_advance_adjustment:
                label = _('Advance Adjusted')
            elif running_total < invoice.total:
                label = _('Partial Payment')
            elif index == 0:
                label = _('Payment Received')
            else:
                label = _('Remaining Paid')
            add(
                payment.payment_date, 4, label,
                _('₹%(amount)s via %(mode)s')
                % {'amount': payment.amount, 'mode': payment.get_payment_source_display()},
            )

    for transfer in resident.transfers.select_related('new_bed__room'):
        add(
            transfer.transfer_date, 6, _('Transferred'),
            _('Room %(room)s (%(bed)s)')
            % {'room': transfer.new_bed.room.room_number, 'bed': transfer.new_bed.bed_number},
        )

    for complaint in resident.complaints.all():
        add(timezone.localtime(complaint.created_at).date(), 7, _('Complaint Raised'), complaint.get_category_display())

    # Every notice, oldest-first: a resident may have cancelled one notice and
    # given another later, so this is a list, not a single row.
    for vacate in resident.vacates.all():
        add(
            vacate.notice_given_date, 8, _('Notice Given'),
            _('Expected vacate %(date)s') % {'date': vacate.expected_vacate_date.isoformat()},
        )
        if vacate.is_cancelled:
            add(
                vacate.cancelled_date, 9, _('Notice Cancelled'),
                vacate.cancellation_reason,
            )
        if vacate.is_settled:
            detail = (
                _('Refund ₹%(amount)s') % {'amount': vacate.refund_amount}
                if vacate.refund_amount is not None else ''
            )
            add(vacate.actual_vacate_date, 10, _('Vacated'), detail)

    absconded = getattr(resident, 'absconded_record', None)
    if absconded is not None:
        note = absconded.absconded_note
        if absconded.last_seen_date:
            seen = _('Last seen %(date)s') % {'date': absconded.last_seen_date.isoformat()}
            note = f'{seen} — {note}' if note else seen
        add(absconded.absconded_date, 11, _('Marked Absconded'), note)
        if absconded.deposit_applied_to_dues > 0:
            add(
                absconded.absconded_date, 12, _('Security Deposit Forfeited'),
                _('₹%(amount)s applied against dues') % {'amount': absconded.deposit_applied_to_dues},
            )
        if absconded.dues_recovery_status == AbscondedRecord.DuesRecoveryStatus.WRITTEN_OFF:
            add(
                timezone.localtime(absconded.updated_at).date(), 13, _('Dues Written Off'),
                _('₹%(amount)s — %(note)s')
                % {'amount': absconded.remaining_dues, 'note': absconded.dues_written_off_note},
            )

    blacklist_entry = getattr(resident, 'blacklist_entry', None)
    if blacklist_entry is not None:
        add(timezone.localtime(blacklist_entry.created_at).date(), 14, _('Blacklisted'), blacklist_entry.reason)

    events.sort(key=lambda e: (e['date'], e['_weight']))
    for event in events:
        del event['_weight']
        event['date'] = event['date'].isoformat()
    return events
