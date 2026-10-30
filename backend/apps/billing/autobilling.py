"""Automatic resident invoicing (Module 08, owner decision 2026-10-28).

Every day the sweep (`run_auto_billing`):

1. issues the auto drafts scheduled for today (they were drafted yesterday,
   so the owner had a day to review, edit, hold or delete them), and
2. drafts each resident's next cycle the day before it starts.

A resident's next cycle continues from what is already billed: the day after
the latest invoice or `AutoBillingCycle` marker ends. That cycle runs to the
day before the next billing day under the property's rule (the resident's
admission day each month, a fixed day of the month, or every 7 days for a
weekly resident). Automation only ever bills forward — gaps before the latest
billed period are left to the owner (the sweep warns once when today itself
is unbilled but a later period is).

Anything unusual (a weekly resident, a partial period, a draft created after
its start date, a resident leaving mid-cycle, ...) gets a review reason and is
never issued automatically; the owner confirms it.

The top half of this module is pure date / money math with no database
access, so the billing rules can be unit-tested directly.
"""
import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from django.db import transaction
from django.db.models import Max, Q

from apps.core.periods import add_months, local_today, month_start
from apps.core.tenancy import tenant_context

logger = logging.getLogger(__name__)

CENT = Decimal('0.01')
WEEK = timedelta(days=7)
ONE_DAY = timedelta(days=1)


# --- Schedule math (pure) -----------------------------------------------------

def clamp_day(year, month, day):
    """`day` of the given month, or the month's last day if it is shorter
    (an admission on the 31st bills on 30 Apr and 28/29 Feb)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class Schedule:
    """When a resident's billing days fall.

    `monthly`: on `anchor_day` (1-31) of every month, clamped to month end.
    `weekly`: every 7 days from `anchor_date` (the joining date)."""
    kind: str
    anchor_day: int = None
    anchor_date: date = None

    def is_billing_day(self, day):
        return self.billing_day_on_or_after(day) == day

    def billing_day_on_or_after(self, day):
        if self.kind == 'weekly':
            if day <= self.anchor_date:
                return self.anchor_date
            weeks = -(-(day - self.anchor_date).days // 7)  # ceil
            return self.anchor_date + WEEK * weeks
        candidate = clamp_day(day.year, day.month, self.anchor_day)
        if candidate >= day:
            return candidate
        following = add_months(month_start(day), 1)
        return clamp_day(following.year, following.month, self.anchor_day)

    def billing_day_after(self, day):
        return self.billing_day_on_or_after(day + ONE_DAY)

    def billing_day_on_or_before(self, day):
        """Start of the cycle containing `day`."""
        if self.kind == 'weekly':
            if day <= self.anchor_date:
                return self.anchor_date
            return self.anchor_date + WEEK * ((day - self.anchor_date).days // 7)
        candidate = clamp_day(day.year, day.month, self.anchor_day)
        if candidate <= day:
            return candidate
        previous = add_months(month_start(day), -1)
        return clamp_day(previous.year, previous.month, self.anchor_day)


def schedule_for(*, billing_mode, joining_date, billing_day_rule, billing_day_of_month):
    """The resident's schedule, or None when automation doesn't bill them
    (daily residents — the owner invoices them at checkout)."""
    from apps.properties.models import PropertySettings
    from apps.residents.models import Admission

    if billing_mode == Admission.BillingMode.WEEKLY:
        # Weekly residents always follow their own joining weekday.
        return Schedule('weekly', anchor_date=joining_date)
    if billing_mode != Admission.BillingMode.MONTHLY:
        return None
    if billing_day_rule == PropertySettings.BillingDayRule.FIXED_DAY and billing_day_of_month:
        return Schedule('monthly', anchor_day=billing_day_of_month)
    return Schedule('monthly', anchor_day=joining_date.day)


@dataclass(frozen=True)
class Cycle:
    start: date
    end: date
    # Share of a full cycle's rent this period is charged (exactly 1 for a
    # full cycle). A Fraction, so the money math stays exact until rounding.
    fraction: Fraction = Fraction(1)
    # Set from the schedule boundaries (the start is not a billing day), never
    # from the price: a capped partial (Jan 16..Feb 14) still costs a full
    # cycle but must still go to the owner for confirmation.
    is_partial: bool = False


def calendar_fraction(start, end, schedule):
    """Share of a full cycle that the partial period start..end (inclusive)
    is worth (owner decision 2026-10-28: split per calendar month).

    Monthly: each calendar month's days over that month's length, summed —
    Jan 20..Feb 14 is 12/31 + 14/28. Weekly: days / 7. Capped at 1: a partial
    period is shorter than a full cycle, so it never costs more than one
    (Jan 16..Feb 14 would otherwise sum to 16/31 + 14/28 > 1)."""
    if schedule.kind == 'weekly':
        fraction = Fraction((end - start).days + 1, 7)
    else:
        fraction = Fraction(0)
        cursor = start
        while cursor <= end:
            days_in_month = calendar.monthrange(cursor.year, cursor.month)[1]
            segment_end = min(end, date(cursor.year, cursor.month, days_in_month))
            fraction += Fraction((segment_end - cursor).days + 1, days_in_month)
            cursor = segment_end + ONE_DAY
    return min(fraction, Fraction(1))


def cycle_starting(start, schedule):
    """The cycle that begins on `start`: a full cycle when `start` is a
    billing day, otherwise a partial running up to the next billing day."""
    end = schedule.billing_day_after(start) - ONE_DAY
    if schedule.is_billing_day(start):
        return Cycle(start, end)
    return Cycle(start, end, calendar_fraction(start, end, schedule), is_partial=True)


def apply_fraction(amount, fraction):
    """`amount` x `fraction`, rounded half-up to paise once at the end."""
    if fraction == 1:
        return amount
    value = amount * Decimal(fraction.numerator) / Decimal(fraction.denominator)
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def partial_discount(discount, *, base_amount, contracted_rent, fraction):
    """Discount line amount (positive) for an auto-generated invoice, or None
    for no line. A percentage discount applies to the rent actually charged;
    a fixed discount is scaled by the same calendar fraction as the rent
    (owner decision 2026-10-28) — not by base / rent, so a first-month
    concession doesn't shrink it twice. Zero rent has nothing to discount."""
    if discount is None or contracted_rent <= 0:
        return None
    if discount.discount_type == discount.DiscountType.PERCENTAGE:
        return discount.computed_amount(base_amount)
    return apply_fraction(discount.discount_value, fraction)


# --- Planning a resident's next draft (DB reads, no writes) -----------------

@dataclass
class Plan:
    cycle: Cycle
    base_amount: Decimal
    partial_note: str
    reasons: list = field(default_factory=list)
    from_issue_date: bool = False

    @property
    def auto_issue_on(self):
        return None if self.reasons else self.cycle.start


def coverage_end(resident):
    """Last day already billed (or handled) for the resident, or None."""
    from .models import AutoBillingCycle, Invoice

    ends = [
        Invoice.objects.filter(resident=resident).aggregate(end=Max('period_end'))['end'],
        AutoBillingCycle.objects.filter(resident=resident).aggregate(end=Max('period_end'))['end'],
    ]
    ends = [end for end in ends if end is not None]
    return max(ends) if ends else None


def plan_next_cycle(*, resident, admission, allocation, schedule, on_date):
    """What the sweep should draft for this resident today, or None.

    Must be called with the resident row locked (see generate_next_draft)."""
    from .models import Invoice

    covered = coverage_end(resident)
    reasons = []
    if covered is not None:
        start = covered + ONE_DAY
    else:
        current_cycle_start = schedule.billing_day_on_or_before(on_date)
        if admission.joining_date < current_cycle_start:
            # Rollout: an established resident automation has never billed.
            # Don't backfill from their joining date — start with the cycle
            # we're in (earlier months stay the owner's manual job).
            start = current_cycle_start
            reasons.append(Invoice.ReviewReason.NO_PRIOR_INVOICE)
        else:
            start = admission.joining_date

    # Draft the day before a cycle starts, never earlier.
    if start > on_date + ONE_DAY:
        return None

    vacate = resident.open_vacate
    if vacate is not None and vacate.expected_vacate_date < start:
        return None  # leaves before this cycle even begins

    cycle = cycle_starting(start, schedule)
    contracted_rent = allocation.contracted_rent
    partial_note = ''
    if start == admission.joining_date and admission.first_month_billing_amount is not None:
        # The admission's own first-period amount, only for the period that
        # actually starts on the joining date (never because this happens to
        # be the first invoice in the database).
        base_amount = admission.first_month_billing_amount
        partial_note = admission.first_month_billing_note
    else:
        base_amount = apply_fraction(contracted_rent, cycle.fraction)

    if schedule.kind == 'weekly':
        reasons.append(Invoice.ReviewReason.WEEKLY)
    if cycle.is_partial and Invoice.ReviewReason.NO_PRIOR_INVOICE not in reasons:
        reasons.append(
            Invoice.ReviewReason.FIRST_PARTIAL if start == admission.joining_date
            else Invoice.ReviewReason.TRANSITION
        )
    from_issue_date = False
    if cycle.start <= on_date:
        reasons.append(Invoice.ReviewReason.LATE)
        from_issue_date = True
    if vacate is not None and vacate.expected_vacate_date < cycle.end:
        reasons.append(Invoice.ReviewReason.VACATING)

    return Plan(cycle, base_amount, partial_note, reasons, from_issue_date)


# --- Sweep --------------------------------------------------------------------

@dataclass
class PropertyOutcome:
    created: int = 0
    scheduled: int = 0
    needs_confirmation: int = 0
    flagged: int = 0
    issued: int = 0
    skipped: int = 0
    failed: int = 0
    gaps: list = field(default_factory=list)


def generate_next_draft(*, resident_id, property_id, on_date):
    """Draft one resident's next cycle if it is due. Returns 'scheduled' (will
    auto-issue), 'needs_confirmation', 'skipped' (overlaps a manual invoice) or
    None (nothing due). Runs in its own transaction — the draft, its marker
    and its line in the owner summary commit together; locks Settings ->
    Resident (the global billing lock order), the summary last."""
    from apps.residents.models import Allocation, Resident
    from apps.residents.services import lock_resident

    from . import services
    from .models import AutoBillingCycle, Invoice

    with transaction.atomic():
        settings_obj = services.lock_property_settings(property_id)
        if not settings_obj.auto_billing_enabled:
            return None
        resident = lock_resident(Resident(pk=resident_id))
        if resident.status not in (Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD):
            return None
        allocation = Allocation.objects.filter(resident=resident).first()
        if allocation is None:
            return None
        admission = resident.admission
        schedule = schedule_for(
            billing_mode=admission.billing_mode, joining_date=admission.joining_date,
            billing_day_rule=settings_obj.billing_day_rule,
            billing_day_of_month=settings_obj.billing_day_of_month,
        )
        if schedule is None:
            return None
        # At most one draft per resident per day, so re-running the sweep on
        # the same day is a no-op even while it catches up on missed cycles.
        if AutoBillingCycle.objects.filter(resident=resident, created_on=on_date).exists():
            return None

        plan = plan_next_cycle(
            resident=resident, admission=admission, allocation=allocation,
            schedule=schedule, on_date=on_date,
        )
        if plan is None:
            return None
        cycle = plan.cycle

        marker = AutoBillingCycle(
            tenant_id=resident.tenant_id, resident=resident, period_start=cycle.start,
            period_end=cycle.end, created_on=on_date,
        )
        try:
            invoice = services.generate_invoice(
                resident=resident, period_start=cycle.start, period_end=cycle.end,
                due_date=cycle.start + timedelta(days=settings_obj.penalty_grace_days),
                actor=None, base_amount=plan.base_amount, partial_note=plan.partial_note,
                discount_fraction=cycle.fraction, auto_generated=True,
                review_reasons=plan.reasons, auto_issue_on=plan.auto_issue_on,
                due_date_policy=(
                    Invoice.DueDatePolicy.FROM_ISSUE_DATE if plan.from_issue_date
                    else Invoice.DueDatePolicy.FROM_PERIOD_START
                ),
            )
        except services.InvoiceConflict:
            # Overlaps an invoice the owner created by hand. Mark the cycle
            # handled so the next one continues after it.
            marker.outcome = AutoBillingCycle.Outcome.SKIPPED_OVERLAP
            marker.save()
            return 'skipped'
        marker.outcome = AutoBillingCycle.Outcome.CREATED
        marker.invoice = invoice
        marker.save()
        scheduled = plan.auto_issue_on is not None
        note_in_summary(
            property_id=property_id, tenant_id=resident.tenant_id, on_date=on_date,
            created=1, scheduled=int(scheduled), needs_confirmation=int(not scheduled),
        )
        return 'scheduled' if scheduled else 'needs_confirmation'


def find_new_gap(resident, on_date):
    """Start of the later period sitting after an unbilled `on_date`, if the
    owner hasn't been told about it yet. Skipped-overlap markers don't count
    as billing on_date — they bill nothing. Call inside a transaction: the
    "already warned" notice and the summary line commit together."""
    from .models import AutoBillingCycle, AutoBillingNotice, Invoice

    covering = Q(period_start__lte=on_date, period_end__gte=on_date)
    if Invoice.objects.filter(covering, resident=resident).exists():
        return None
    if AutoBillingCycle.objects.filter(
        covering, resident=resident, outcome=AutoBillingCycle.Outcome.CREATED,
    ).exists():
        return None
    later = (
        Invoice.objects.filter(resident=resident, period_start__gt=on_date)
        .order_by('period_start').values_list('period_start', flat=True).first()
    )
    if later is None:
        return None
    _notice, created = AutoBillingNotice.objects.get_or_create(
        resident=resident, kind=AutoBillingNotice.Kind.COVERAGE_GAP, key_date=later,
        defaults={'tenant_id': resident.tenant_id},
    )
    if not created:
        return None
    note_in_summary(
        property_id=resident.property_id, tenant_id=resident.tenant_id, on_date=on_date,
        gap=str(resident),
    )
    return later


def _issue_due_drafts(prop, on_date, outcome):
    from . import services
    from .models import Invoice

    due_ids = list(
        Invoice.objects.filter(
            resident__property=prop, status=Invoice.Status.DRAFT, auto_generated=True,
            auto_issue_held=False, auto_issue_on__lte=on_date,
        ).values_list('pk', flat=True)
    )
    for invoice_id in due_ids:
        try:
            # A flag and its line in the owner summary commit together.
            with transaction.atomic():
                result = services.issue_invoice(invoice_id=invoice_id, actor=None, on_date=on_date, auto=True)
                if result == services.FLAGGED:
                    note_in_summary(property_id=prop.pk, tenant_id=prop.tenant_id, on_date=on_date,
                                    needs_confirmation=1)
        except Exception:
            logger.exception('Auto billing: issuing invoice %s failed', invoice_id)
            outcome.failed += 1
            continue
        if result == services.ISSUED:
            outcome.issued += 1
        elif result == services.FLAGGED:
            outcome.flagged += 1


def _generate_due_drafts(prop, on_date, outcome):
    from apps.residents.models import Admission, Resident

    residents = (
        Resident.objects.filter(
            property=prop, status__in=(Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD),
            allocation__isnull=False,
        )
        .exclude(admission__billing_mode=Admission.BillingMode.DAILY)
        .order_by('created_at')
    )
    for resident in residents:
        try:
            result = generate_next_draft(resident_id=resident.pk, property_id=prop.pk, on_date=on_date)
        except Exception:
            # One resident's bad data must not stop the rest. Nothing was
            # written for them (the transaction rolled back, marker included),
            # so the next run retries.
            logger.exception('Auto billing: drafting for resident %s failed', resident.pk)
            outcome.failed += 1
            continue
        if result == 'skipped':
            outcome.skipped += 1
        elif result is not None:
            outcome.created += 1
            if result == 'scheduled':
                outcome.scheduled += 1
            else:
                outcome.needs_confirmation += 1
        try:
            with transaction.atomic():
                gap = find_new_gap(resident, on_date)
        except Exception:
            logger.exception('Auto billing: gap check for resident %s failed', resident.pk)
            continue
        if gap is not None:
            outcome.gaps.append((resident, gap))


def run_for_property(prop, on_date):
    from apps.properties.models import PropertySettings

    PropertySettings.objects.get_or_create(property=prop, defaults={'tenant_id': prop.tenant_id})
    outcome = PropertyOutcome()
    # Issue before drafting: today's drafts were created yesterday.
    _issue_due_drafts(prop, on_date, outcome)
    if PropertySettings.objects.filter(property=prop, auto_billing_enabled=True).exists():
        _generate_due_drafts(prop, on_date, outcome)
    # Every draft, flag and gap recorded its summary line in its own
    # transaction, so this (and the retry task) only has to deliver.
    try:
        deliver_pending_summaries(prop, on_date)
    except Exception:
        logger.exception('Auto billing: notifying staff of property %s failed', prop.pk)
    return outcome


# --- Owner summaries (persisted, retried until delivered) ---------------------

# How far back an undelivered summary is still worth sending.
SUMMARY_RETRY_DAYS = 2


def note_in_summary(*, property_id, tenant_id, on_date, created=0, scheduled=0, needs_confirmation=0,
                    gap=None):
    """Add one piece of news to the property's summary for the day. Must run
    inside the transaction that makes the news (draft, flag, gap notice), so
    the owner is owed a summary exactly when the change commits. Locked last
    in the billing lock order. New news after a delivered summary re-opens
    it, so everyone hears the combined figures."""
    from .models import AutoBillingSummary

    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('note_in_summary() must run inside the transaction that makes the news.')
    AutoBillingSummary.objects.get_or_create(
        property_id=property_id, on_date=on_date, defaults={'tenant_id': tenant_id},
    )
    summary = AutoBillingSummary.objects.select_for_update().get(property_id=property_id, on_date=on_date)
    summary.created += created
    summary.scheduled += scheduled
    summary.needs_confirmation += needs_confirmation
    if gap:
        summary.gaps = ', '.join([name for name in summary.gaps.split(', ') if name] + [gap])
    summary.delivered_to = []
    summary.completed = False
    summary.save()
    return summary


def summary_recipients(prop):
    """The Owner(s) and the property's staff who can manage invoices."""
    from django.contrib.auth import get_user_model

    from apps.core.modules import resolve_permissions
    from apps.core.roles import Role

    user_model = get_user_model()
    recipients = {
        user.pk: user
        for user in user_model.objects.filter(tenant_id=prop.tenant_id, role=Role.OWNER, is_active=True)
    }
    staff = user_model.objects.filter(
        tenant_id=prop.tenant_id, is_active=True, property_assignments__property=prop,
    )
    for user in staff:
        if 'manage_invoices' in resolve_permissions(user):
            recipients[user.pk] = user
    return list(recipients.values())


def deliver_summary(summary):
    """Send the summary to every recipient it hasn't reached yet. A recipient
    counts as reached once any channel sent it — or when no channel could
    (no template / no address: retrying wouldn't help); a failed send or an
    exception leaves them for the next attempt."""
    from apps.notifications import services as notifications
    from apps.notifications.models import NotificationLog

    from .models import AutoBillingSummary

    with transaction.atomic():
        summary = AutoBillingSummary.objects.select_for_update().select_related('property').get(pk=summary.pk)
        if summary.completed:
            return summary
        prop = summary.property
        recipients = summary_recipients(prop)
        delivered = set(summary.delivered_to)
        for user in recipients:
            if user.pk in delivered:
                continue
            try:
                logs = notifications.notify(
                    tenant_id=prop.tenant_id, notification_type='invoice_drafts_ready', recipient_user=user,
                    context={
                        'name': user.first_name, 'property': prop.name, 'date': summary.on_date.isoformat(),
                        'created': summary.created, 'scheduled': summary.scheduled,
                        'needs_confirmation': summary.needs_confirmation, 'gaps': summary.gaps,
                    },
                    reference=f'auto_billing:{prop.pk}:{summary.on_date.isoformat()}',
                )
            except Exception:
                logger.exception('Auto billing: summary %s to user %s failed', summary.pk, user.pk)
                continue
            statuses = {log.status for log in logs}
            if NotificationLog.Status.SENT in statuses or NotificationLog.Status.FAILED not in statuses:
                delivered.add(user.pk)
        summary.delivered_to = sorted(delivered, key=str)
        summary.attempts += 1
        summary.completed = all(user.pk in delivered for user in recipients)
        summary.save(update_fields=['delivered_to', 'attempts', 'completed', 'updated_at'])
    return summary


def _pending_summaries(today):
    from .models import AutoBillingSummary

    return AutoBillingSummary.objects.filter(
        completed=False, on_date__gte=today - timedelta(days=SUMMARY_RETRY_DAYS), on_date__lte=today,
    )


def deliver_pending_summaries(prop, on_date):
    for summary in _pending_summaries(on_date).filter(property=prop):
        deliver_summary(summary)


def retry_pending_summaries(today=None):
    """Every undelivered recent summary, across tenants — run every 30 min by
    `billing.retry_auto_billing_summaries` so a failed send is retried well
    before the drafts it announces are auto-issued."""
    from .models import AutoBillingSummary

    today = today or local_today()
    with tenant_context(is_super_admin=True):
        pending = list(_pending_summaries(today).values_list('pk', 'tenant_id'))
    delivered = 0
    for summary_id, tenant_id in pending:
        try:
            with tenant_context(tenant_id):
                summary = deliver_summary(AutoBillingSummary(pk=summary_id))
        except Exception:
            logger.exception('Auto billing: retrying summary %s failed', summary_id)
            continue
        delivered += int(summary.completed)
    return {'pending': len(pending), 'completed': delivered}


def run_auto_billing(on_date=None):
    """The daily sweep, across every tenant. `on_date` is the effective day
    for everything it does (selection, issue date, due dates); defaults to
    today in the product timezone."""
    from apps.properties.models import Property, PropertySettings

    on_date = on_date or local_today()
    with tenant_context(is_super_admin=True):
        # A property switched off is skipped entirely: switching it off already
        # moved its scheduled drafts to review (flag_scheduled_drafts).
        properties = list(
            Property.objects.filter(status=Property.Status.ACTIVE)
            .exclude(pk__in=PropertySettings.objects.filter(auto_billing_enabled=False)
                     .values('property_id'))
            .order_by('tenant_id', 'created_at')
            .values_list('pk', 'tenant_id')
        )
    totals = {'issued': 0, 'flagged': 0, 'created': 0, 'skipped': 0, 'failed': 0, 'gaps': 0}
    for property_id, tenant_id in properties:
        try:
            with tenant_context(tenant_id):
                prop = Property.objects.get(pk=property_id)
                outcome = run_for_property(prop, on_date)
        except Exception:
            logger.exception('Auto billing: property %s failed', property_id)
            totals['failed'] += 1
            continue
        for key in ('issued', 'flagged', 'created', 'skipped', 'failed'):
            totals[key] += getattr(outcome, key)
        totals['gaps'] += len(outcome.gaps)
    return totals
