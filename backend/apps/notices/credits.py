"""Food-holiday credits (Module 24).

A food holiday with `adjust_in_bill` owes every with-food resident
`rate_per_day` for each holiday day they stayed. This module is the only code
that creates, attaches, detaches, settles or deletes a `FoodHolidayCredit`;
every change runs in the caller's transaction after the property's
`PropertySettings` row lock, which serializes all holiday/credit work per
property (lock order: Settings -> FoodHoliday -> Resident -> Vacate -> Invoice
-> FoodHolidayCredit -> Admission).

Timing: a credit is created and put on a bill only after its holiday has
ended (`end_date < on_date`). The one exception is a move-out or abscond,
which settles the days actually stayed, unfinished holiday included.

Allocation (`allocate_pending`): pending credits, oldest holiday first, each go
on the resident's earliest *draft* starting after the holiday ended, as long as
that draft's total stays above zero. A credit that fits nowhere stops the
queue (strict FIFO), and credits already on a draft are never moved.

The top of this module is pure date math, so the entitlement rules can be
unit-tested without a database.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Max
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError

from apps.audit import log as audit_log
from apps.core.periods import local_today

from .models import MAX_AMOUNT, FoodHoliday, FoodHolidayCredit

ZERO = Decimal('0.00')
# Food-holiday lines are added after the generated lines (accommodation 0,
# discount 1) and ad-hoc charges, so they read last on the invoice.
LINE_ORDER = 90


# --- Entitlement (pure) -------------------------------------------------------

def entitled_days(*, holiday, joining_date, with_food, through=None):
    """Holiday days a resident is owed for: [start, end] ∩ [joining_date,
    through]. `through` is a move-out / abscond date; None = still staying."""
    if not holiday.adjust_in_bill or not with_food or joining_date is None:
        return 0
    start = max(holiday.start_date, joining_date)
    end = holiday.end_date if through is None else min(holiday.end_date, through)
    return max(0, (end - start).days + 1)


def credit_amount(rate, days):
    return rate * days  # exact: decimal(12,2) × whole days needs no rounding


def check_amount(value, field_name):
    """Every persisted aggregate must fit decimal(12,2)."""
    if value > MAX_AMOUNT:
        raise ValidationError(
            {field_name: _('This amount is too large to record.')}, code='settlement_amount_too_large',
        )
    return value


# --- Helpers ------------------------------------------------------------------

def _terms(resident):
    """(joining_date, with_food) from the admission — the same food-preference
    source the accommodation label uses."""
    from apps.residents.models import Admission

    admission = getattr(resident, 'admission', None)
    if admission is None:
        return None, False
    return admission.joining_date, admission.food_preference == Admission.FoodPreference.WITH_FOOD


def _is_current(resident):
    from apps.residents.models import Resident

    return resident.status in (Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD)


def _line_label(credit):
    # Stored display text, built like the other generated labels
    # (billing.services._accommodation_label).
    days = credit.days
    unit = 'day' if days == 1 else 'days'
    return f'Food holiday — {credit.holiday.name} ({days} {unit} × ₹{credit.rate})'


def _invoice_total(invoice):
    from apps.billing.models import InvoiceLineItem

    return sum(
        InvoiceLineItem.objects.filter(invoice=invoice).values_list('amount', flat=True), ZERO,
    )


def _lock(credit):
    return FoodHolidayCredit.objects.select_for_update(of=('self',)).select_related('holiday').get(pk=credit.pk)


def _audit(action, credit, *, actor=None, before=None, after=None, request=None):
    audit_log.record(
        action=action, actor=actor, tenant_id=credit.tenant_id, obj=credit,
        before=before, after=after, request=request,
    )


def _state(credit):
    return {
        'holiday': str(credit.holiday_id), 'resident': str(credit.resident_id), 'status': credit.status,
        'days': credit.days, 'amount': str(credit.amount),
        'invoice': str(credit.line_item.invoice_id) if credit.line_item_id else None,
    }


# --- Transitions --------------------------------------------------------------

def detach(credit, *, to, actor=None, request=None):
    """Take an invoiced credit off its draft line, to `pending` or `waived`.
    The reference is cleared (and the status set) in one save before the line
    is deleted — the PROTECT foreign key requires that order."""
    if to not in (FoodHolidayCredit.Status.PENDING, FoodHolidayCredit.Status.WAIVED):
        raise ValueError(f'detach() only moves a credit to pending or waived, not {to!r}')
    credit = _lock(credit)
    before = _state(credit)
    line_id = credit.line_item_id
    credit.line_item = None
    credit.status = to
    credit.save(update_fields=['line_item', 'status', 'updated_at'])
    if line_id is not None:
        from apps.billing.models import InvoiceLineItem

        InvoiceLineItem.objects.filter(pk=line_id).delete()
    _audit(
        'food_holiday_credit.waived' if to == FoodHolidayCredit.Status.WAIVED else 'food_holiday_credit.detached',
        credit, actor=actor, before=before, after=_state(credit), request=request,
    )
    return credit


def _attach(credit, invoice):
    from apps.billing.models import InvoiceLineItem

    order = InvoiceLineItem.objects.filter(invoice=invoice).aggregate(top=Max('order'))['top']
    line = InvoiceLineItem.objects.create(
        tenant_id=credit.tenant_id, invoice=invoice, line_type=InvoiceLineItem.LineType.FOOD_HOLIDAY,
        label=_line_label(credit), amount=-credit.amount, order=max(LINE_ORDER, (order or 0) + 1),
    )
    credit.line_item = line
    credit.status = FoodHolidayCredit.Status.INVOICED
    credit.save(update_fields=['line_item', 'status', 'updated_at'])
    _audit('food_holiday_credit.invoiced', credit, after=_state(credit))


def settle(credit, *, days, vacate=None, absconded_record=None):
    """Pay a pending credit out through a move-out refund or abscond netting.
    Days, amount, status and the one settlement reference are written in a
    single save, so the status CHECK holds at every write."""
    credit = _lock(credit)
    if credit.status != FoodHolidayCredit.Status.PENDING:
        raise ValueError('Only a pending credit can be settled; detach it first.')
    if (vacate is None) == (absconded_record is None):
        raise ValueError('settle() needs exactly one of vacate / absconded_record')
    credit.rate = credit.holiday.rate_per_day
    credit.days = days
    credit.amount = credit_amount(credit.rate, days)
    credit.status = FoodHolidayCredit.Status.SETTLED
    credit.vacate = vacate
    credit.absconded_record = absconded_record
    credit.save(update_fields=['rate', 'days', 'amount', 'status', 'vacate', 'absconded_record', 'updated_at'])
    _audit('food_holiday_credit.settled', credit, after=_state(credit))
    return credit


def record_clawback(credit, *, clawback_days, vacate=None, absconded_record=None):
    """An issued credit covered days after the resident left: record what is
    clawed back, linked to the settlement that claws it."""
    credit = _lock(credit)
    if credit.status != FoodHolidayCredit.Status.INVOICED:
        raise ValueError('Only an invoiced credit can be clawed back.')
    if (vacate is None) == (absconded_record is None):
        raise ValueError('record_clawback() needs exactly one of vacate / absconded_record')
    credit.clawback_days = clawback_days
    credit.clawback_amount = credit_amount(credit.rate, clawback_days)
    credit.vacate = vacate
    credit.absconded_record = absconded_record
    credit.save(update_fields=['clawback_days', 'clawback_amount', 'vacate', 'absconded_record', 'updated_at'])
    _audit('food_holiday_credit.clawed_back', credit,
           after={**_state(credit), 'clawback_days': clawback_days, 'clawback_amount': str(credit.clawback_amount)})
    return credit


def delete_credit(credit, *, actor=None, request=None):
    """Remove a credit row (never a status). One on a draft is detached first;
    one on an issued invoice or already settled is a financial record."""
    credit = _lock(credit)
    if credit.status == FoodHolidayCredit.Status.SETTLED or credit.vacate_id or credit.absconded_record_id:
        raise ValueError('A settled credit cannot be deleted.')
    if credit.status == FoodHolidayCredit.Status.INVOICED:
        if credit.line_item.invoice.status != credit.line_item.invoice.Status.DRAFT:
            raise ValueError('A credit on an issued invoice cannot be deleted.')
        credit = detach(credit, to=FoodHolidayCredit.Status.PENDING, actor=actor, request=request)
    _audit('food_holiday_credit.deleted', credit, actor=actor, before=_state(credit), request=request)
    credit.delete()


# --- Creation and allocation --------------------------------------------------

def _set_amount(credit, *, days, rate):
    credit.days = days
    credit.rate = rate
    credit.amount = credit_amount(rate, days)


def ensure_credits(resident, *, on_date):
    """Create the missing pending credits of a current resident for every
    adjust-in-bill holiday of their property that ended before `on_date`."""
    if not _is_current(resident):
        return []
    joining_date, with_food = _terms(resident)
    if not with_food:
        return []
    have = set(FoodHolidayCredit.objects.filter(resident=resident).values_list('holiday_id', flat=True))
    created = []
    holidays = FoodHoliday.objects.filter(
        property_id=resident.property_id, adjust_in_bill=True, end_date__lt=on_date,
    ).exclude(pk__in=have).order_by('end_date', 'start_date', 'id')
    for holiday in holidays:
        days = entitled_days(holiday=holiday, joining_date=joining_date, with_food=with_food)
        if days <= 0:
            continue
        credit = FoodHolidayCredit(tenant_id=resident.tenant_id, holiday=holiday, resident=resident)
        _set_amount(credit, days=days, rate=holiday.rate_per_day)
        credit.save()
        _audit('food_holiday_credit.created', credit, after=_state(credit))
        created.append(credit)
    return created


def allocate_pending(resident, *, on_date=None):
    """Put the resident's pending credits on draft invoices (see the module
    docstring). Only ever touches drafts; returns how many were attached."""
    from apps.billing.models import Invoice

    on_date = on_date or local_today()
    pending = list(
        FoodHolidayCredit.objects.filter(
            resident=resident, status=FoodHolidayCredit.Status.PENDING, holiday__end_date__lt=on_date,
            holiday__adjust_in_bill=True,
        ).select_related('holiday').order_by('holiday__end_date', 'holiday__start_date', 'id')
    )
    if not pending:
        return 0
    drafts = list(
        Invoice.objects.select_for_update(of=('self',))
        .filter(resident=resident, status=Invoice.Status.DRAFT).order_by('period_start')
    )
    totals = {invoice.pk: _invoice_total(invoice) for invoice in drafts}
    attached = 0
    for credit in pending:
        target = next(
            (invoice for invoice in drafts
             if invoice.period_start > credit.holiday.end_date and totals[invoice.pk] - credit.amount > 0),
            None,
        )
        if target is None:
            break  # strict FIFO: a later credit never jumps ahead of this one
        _attach(credit, target)
        totals[target.pk] -= credit.amount
        attached += 1
    return attached


def estimate_holiday(holiday, *, exclude=()):
    """(resident, days) a holiday would credit each current with-food resident
    who has no credit row yet — before the holiday ends too. Read-only."""
    from apps.residents.models import Admission, Resident

    if not holiday.adjust_in_bill:
        return []
    residents = (
        Resident.objects.filter(
            property_id=holiday.property_id,
            status__in=(Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD),
            admission__food_preference=Admission.FoodPreference.WITH_FOOD,
        ).exclude(pk__in=exclude).select_related('admission').order_by('first_name', 'last_name')
    )
    rows = []
    for resident in residents:
        joining_date, with_food = _terms(resident)
        days = entitled_days(holiday=holiday, joining_date=joining_date, with_food=with_food)
        if days > 0:
            rows.append((resident, days))
    return rows


def credits_on(invoice):
    return FoodHolidayCredit.objects.filter(line_item__invoice=invoice)


def release_invoice(invoice, *, actor=None, request=None):
    """A draft is about to be deleted: its credits go back to pending."""
    for credit in credits_on(invoice):
        detach(credit, to=FoodHolidayCredit.Status.PENDING, actor=actor, request=request)


def rebalance(invoice, *, actor=None, request=None):
    """Another line change left the draft at or below zero: detach its credits,
    newest holiday first (the reverse of the allocation order), until the
    total is positive again. Owner lines alone at or below zero are left as
    the owner set them."""
    total = _invoice_total(invoice)
    if total > 0:
        return 0
    detached = 0
    on_invoice = credits_on(invoice).select_related('holiday').order_by(
        '-holiday__end_date', '-holiday__start_date', '-id',
    )
    for credit in on_invoice:
        if total > 0:
            break
        detach(credit, to=FoodHolidayCredit.Status.PENDING, actor=actor, request=request)
        total += credit.amount
        detached += 1
    return detached


def waive(credit, *, actor, request=None):
    return detach(credit, to=FoodHolidayCredit.Status.WAIVED, actor=actor, request=request)


def restore(credit, *, actor, request=None, on_date=None):
    """Owner undoes a waiver: back to pending, then offered to drafts again
    (only once the holiday has ended — allocate_pending enforces that)."""
    credit = _lock(credit)
    if credit.status != FoodHolidayCredit.Status.WAIVED:
        raise ValidationError({'detail': _('Only a waived credit can be restored.')}, code='not_waived')
    if not credit.holiday.adjust_in_bill:
        raise ValidationError(
            {'detail': _('Turn on the bill adjustment for this holiday first.')}, code='adjustment_off',
        )
    if not _is_current(credit.resident):
        raise ValidationError(
            {'detail': _("This resident's stay has ended, so the credit can't be restored.")},
            code='resident_not_current',
        )
    before = _state(credit)
    credit.status = FoodHolidayCredit.Status.PENDING
    credit.save(update_fields=['status', 'updated_at'])
    _audit('food_holiday_credit.restored', credit, actor=actor, before=before, after=_state(credit), request=request)
    allocate_pending(credit.resident, on_date=on_date)
    return credit


# --- Holiday lifecycle --------------------------------------------------------

def holiday_is_locked(holiday):
    """True once a credit is on an issued invoice or settled: the holiday's
    dates, rate and adjustment are then a financial record."""
    from apps.billing.models import Invoice

    return holiday.credits.exclude(
        status__in=(FoodHolidayCredit.Status.PENDING, FoodHolidayCredit.Status.WAIVED),
    ).exclude(
        status=FoodHolidayCredit.Status.INVOICED, line_item__invoice__status=Invoice.Status.DRAFT,
    ).exists()


def _affected_residents(holiday):
    from apps.residents.models import Admission, Resident

    current = Resident.objects.filter(
        property_id=holiday.property_id, status__in=(Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD),
        admission__food_preference=Admission.FoodPreference.WITH_FOOD,
    ).values_list('pk', flat=True)
    with_rows = holiday.credits.values_list('resident_id', flat=True)
    return sorted(set(current) | set(with_rows))


def recompute_holiday(holiday, *, actor=None, request=None, on_date=None):
    """Bring a holiday's credits in line with its current dates, rate and
    adjustment (after create or edit). Draft-attached credits come off their
    lines; pending ones are rebuilt; waived ones stay waived (tombstones)
    with their days recomputed. Residents are locked in id order."""
    from apps.residents.models import Resident
    from apps.residents.services import lock_resident

    on_date = on_date or local_today()
    ended = holiday.end_date < on_date
    for resident_id in _affected_residents(holiday):
        resident = lock_resident(Resident(pk=resident_id))
        credit = FoodHolidayCredit.objects.filter(holiday=holiday, resident=resident).first()
        if credit is not None and credit.status == FoodHolidayCredit.Status.INVOICED:
            credit = detach(credit, to=FoodHolidayCredit.Status.PENDING, actor=actor, request=request)
        joining_date, with_food = _terms(resident)
        days = entitled_days(holiday=holiday, joining_date=joining_date, with_food=with_food)
        if credit is not None and credit.status == FoodHolidayCredit.Status.WAIVED:
            if holiday.adjust_in_bill:
                _set_amount(credit, days=days, rate=holiday.rate_per_day)
                credit.save(update_fields=['days', 'rate', 'amount', 'updated_at'])
        elif credit is not None:  # pending
            if holiday.adjust_in_bill and ended and days > 0 and _is_current(resident):
                _set_amount(credit, days=days, rate=holiday.rate_per_day)
                credit.save(update_fields=['days', 'rate', 'amount', 'updated_at'])
            else:
                delete_credit(credit, actor=actor, request=request)
        elif holiday.adjust_in_bill and ended and days > 0 and _is_current(resident):
            credit = FoodHolidayCredit(tenant_id=resident.tenant_id, holiday=holiday, resident=resident)
            _set_amount(credit, days=days, rate=holiday.rate_per_day)
            credit.save()
            _audit('food_holiday_credit.created', credit, after=_state(credit))
        allocate_pending(resident, on_date=on_date)


def delete_holiday_credits(holiday, *, actor=None, request=None):
    """Every credit row of a holiday being deleted (the caller checked it is
    not locked). Draft lines are removed first."""
    for credit in list(holiday.credits.all()):
        delete_credit(credit, actor=actor, request=request)


# --- Move-out / abscond -------------------------------------------------------

@dataclass
class ExitPlan:
    """What settling a resident's food-holiday credits at `through` does.
    Built read-only, so the settlement preview and the real settlement can
    never disagree."""
    settle: list = field(default_factory=list)      # (holiday, credit or None, days)
    drop: list = field(default_factory=list)        # credits with nothing owed any more
    clawback: list = field(default_factory=list)    # (credit, clawback_days)
    credit_total: Decimal = ZERO
    clawback_total: Decimal = ZERO


def plan_exit(resident, *, through):
    """Credits owed / clawed back if the resident leaves on `through`.
    Considers every adjust-in-bill holiday that started by then, plus every
    holiday the resident already has a credit for. Waived and settled credits
    are left alone; credits on issued invoices can only be clawed back."""
    from apps.billing.models import Invoice

    joining_date, with_food = _terms(resident)
    credits = {
        credit.holiday_id: credit
        for credit in FoodHolidayCredit.objects.filter(resident=resident)
        .select_related('holiday', 'line_item__invoice')
    }
    holidays = {
        holiday.pk: holiday
        for holiday in FoodHoliday.objects.filter(
            property_id=resident.property_id, adjust_in_bill=True, start_date__lte=through,
        )
    }
    for credit in credits.values():
        holidays.setdefault(credit.holiday_id, credit.holiday)

    plan = ExitPlan()
    for holiday in sorted(holidays.values(), key=lambda h: (h.end_date, h.start_date, str(h.pk))):
        credit = credits.get(holiday.pk)
        days = entitled_days(holiday=holiday, joining_date=joining_date, with_food=with_food, through=through)
        if credit is None:
            if days > 0:
                plan.settle.append((holiday, None, days))
                plan.credit_total += credit_amount(holiday.rate_per_day, days)
            continue
        if credit.status in (FoodHolidayCredit.Status.WAIVED, FoodHolidayCredit.Status.SETTLED):
            continue
        if (credit.status == FoodHolidayCredit.Status.INVOICED
                and credit.line_item.invoice.status != Invoice.Status.DRAFT):
            extra = max(0, credit.days - days)
            if extra:
                plan.clawback.append((credit, extra))
                plan.clawback_total += credit_amount(credit.rate, extra)
            continue
        # pending, or on a draft that will be released
        if days > 0 and holiday.adjust_in_bill:
            plan.settle.append((holiday, credit, days))
            plan.credit_total += credit_amount(holiday.rate_per_day, days)
        else:
            plan.drop.append(credit)
    check_amount(plan.credit_total, 'food_holiday_credit')
    check_amount(plan.clawback_total, 'food_holiday_clawback')
    return plan


def apply_exit(plan, resident, *, vacate=None, absconded_record=None):
    """Carry out a plan from plan_exit (caller holds Settings -> Resident ->
    Vacate locks): release draft credits, settle what is owed, record
    clawbacks, drop the rest."""
    for credit in plan.drop:
        delete_credit(credit)
    for holiday, credit, days in plan.settle:
        if credit is None:
            credit = FoodHolidayCredit(tenant_id=resident.tenant_id, holiday=holiday, resident=resident)
            _set_amount(credit, days=days, rate=holiday.rate_per_day)
            credit.save()
        elif credit.status == FoodHolidayCredit.Status.INVOICED:
            credit = detach(credit, to=FoodHolidayCredit.Status.PENDING)
        settle(credit, days=days, vacate=vacate, absconded_record=absconded_record)
    for credit, extra in plan.clawback:
        record_clawback(credit, clawback_days=extra, vacate=vacate, absconded_record=absconded_record)


def vacate_amounts(vacate, *, maintenance_deduction, plan):
    """(credit, clawback calculated, recovered, unrecovered) for a move-out.
    Recovery is capped at what the refund can absorb, never below zero."""
    credit = plan.credit_total
    calculated = plan.clawback_total
    capacity = max(ZERO, vacate.refund_before_clawback(maintenance_deduction, credit))
    recovered = min(calculated, capacity)
    unrecovered = calculated - recovered
    for value, name in ((credit, 'food_holiday_credit'), (calculated, 'food_holiday_clawback_calculated'),
                        (recovered, 'food_holiday_clawback_recovered'),
                        (unrecovered, 'food_holiday_clawback_unrecovered')):
        check_amount(value, name)
    return credit, calculated, recovered, unrecovered
