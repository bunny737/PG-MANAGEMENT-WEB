"""Analytics summary + trend (UX roadmap D0 glossary, D1 endpoints).

Every figure is defined once here on top of apps/billing/selectors.py and has
a drill-down list that uses the same definition:

    gross_receipts       payments dated in the month           -> /payments/?month=
    refunds_paid         rent refunds dated in the month — always 0 in v1
                         (no rent-refund record; owner decision 2026-10-16)
    cash_collected       gross_receipts - refunds_paid         -> /cash-movements/?month=
    period_invoiced      current net total of issued invoices whose billing
                         period starts in the month ("to date": a later edit
                         can change a past month)              -> /invoices/?period=
    period_collected     sum of min(paid, net total) over those invoices
                                                               -> capped_allocated column
    collection_rate      period_collected / period_invoiced as a % (1 dp);
                         null when nothing was invoiced
    outstanding_total    balance on every open invoice, any period
                                                               -> /invoices/?status=outstanding
    period_outstanding   balance on the month's invoices       -> ?period=&status=outstanding
    overdue_total        outstanding with due_date before today
    expenses_paid        live expenses dated in the month      -> /expenses/?month=
    net_cash_flow        cash_collected - expenses_paid (NOT profit)
    deposits_held        refundable security deposits + unapplied advance of
                         current residents — a liability, never income

Balance metrics (outstanding/overdue/counts) are always as of now, also for
a past month (`balances_as_of`). Months are calendar months in the property
timezone (apps/core/periods.py).

Redaction groups: finance (view_finance), expenses (view_expenses),
cash_flow (both — a derived metric needs every constituent permission),
occupancy (none beyond the entry permission).
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.billing import selectors
from apps.billing.models import Invoice, Payment
from apps.core.periods import (
    add_months,
    local_today,
    month_end,
    month_key,
    month_start,
    parse_month,
    property_timezones,
)
from apps.core.redaction import Redactor
from apps.expenses import services as expense_services
from apps.properties.layout import bed_counts
from apps.properties.models import Bed
from apps.properties.services import scoped_property_ids
from apps.residents.models import Admission, Allocation, Resident

ZERO = selectors.ZERO
CURRENT = (Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD)
MAX_TREND_MONTHS = 24


def _rate(part, whole):
    if not whole:
        return None
    return float((Decimal(part) * 100 / Decimal(whole)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def _jsonify(value):
    if isinstance(value, dict):
        return {key: _jsonify(item) for key, item in value.items()}
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal('0.01')))
    return value


def fiscal_year_start(first, start_month):
    year = first.year if first.month >= start_month else first.year - 1
    return first.replace(year=year, month=start_month, day=1)


def _gross_receipts(property_ids, start, end):
    if end < start:
        return ZERO
    return Payment.objects.filter(
        invoice__resident__property_id__in=property_ids, payment_date__range=(start, end),
    ).aggregate(total=Coalesce(Sum('amount'), ZERO, output_field=selectors.MONEY))['total']


def _period_invoices(property_ids, first, last):
    return selectors.with_money(
        Invoice.objects.filter(
            resident__property_id__in=property_ids, period_start__range=(first, last),
        ).exclude(status=Invoice.Status.DRAFT)
    )


def flow_finance(property_ids, first, last):
    """Month flow figures (also the trend's per-month finance row)."""
    gross = _gross_receipts(property_ids, first, last)
    refunds = ZERO
    period = _period_invoices(property_ids, first, last)
    invoiced = selectors.total_of(period, 'net_total')
    collected = selectors.total_of(period, 'capped_paid')
    return {
        'gross_receipts': gross,
        'refunds_paid': refunds,
        'cash_collected': gross - refunds,
        'period_invoiced': invoiced,
        'period_collected': collected,
        'collection_rate': _rate(collected, invoiced),
    }


def balance_finance(property_ids, first, last, today):
    """Current balances (as of now, whatever month is selected)."""
    open_invoices = selectors.outstanding(Invoice.objects.filter(resident__property_id__in=property_ids))
    owing = open_invoices.values('resident_id')
    deposits = Admission.objects.filter(
        resident__property_id__in=property_ids, resident__status__in=CURRENT,
    ).aggregate(total=Coalesce(
        Sum(F('security_deposit_amount') + F('advance_amount') - F('advance_applied_amount')),
        ZERO, output_field=selectors.MONEY,
    ))['total']
    return {
        'outstanding_total': selectors.total_of(open_invoices, 'balance'),
        'period_outstanding': selectors.total_of(
            open_invoices.filter(period_start__range=(first, last)), 'balance'
        ),
        'overdue_total': selectors.total_of(open_invoices.filter(due_date__lt=today), 'balance'),
        'open_invoice_count': open_invoices.count(),
        'residents_with_balance_count': owing.distinct().count(),
        'occupied_beds_with_balance_count': Allocation.objects.filter(
            allocated_bed__room__floor__building__property_id__in=property_ids,
            allocated_bed__status=Bed.Status.OCCUPIED,
            resident__status__in=CURRENT,
            resident_id__in=owing,
        ).count(),
        'deposits_held': deposits,
    }


def occupancy(property_ids):
    return bed_counts(
        Bed.objects.filter(room__floor__building__property_id__in=property_ids)
        .values_list('status', flat=True)
    )


def summary(user, property_param, month_param):
    property_ids = scoped_property_ids(user, property_param)
    today = local_today()
    first = parse_month(month_param, default=month_start(today))
    last = month_end(first)
    ytd_start = fiscal_year_start(first, user.tenant.fiscal_year_start_month)
    ytd_end = min(last, today)
    redactor = Redactor(user)

    def finance():
        return {
            **flow_finance(property_ids, first, last),
            **balance_finance(property_ids, first, last, today),
            'ytd_cash_collected': _gross_receipts(property_ids, ytd_start, ytd_end),
        }

    def expenses():
        return {
            'expenses_paid': expense_services.total_for(property_ids, first, last),
            'ytd_expenses_paid': (
                expense_services.total_for(property_ids, ytd_start, ytd_end) if ytd_end >= ytd_start else ZERO
            ),
        }

    finance_group = redactor.group('finance', ['view_finance'], finance)
    expenses_group = redactor.group('expenses', ['view_expenses'], expenses)
    cash_flow_group = redactor.group(
        'cash_flow', ['view_finance', 'view_expenses'],
        lambda: {
            'net_cash_flow': finance_group['cash_collected'] - expenses_group['expenses_paid'],
            'ytd_net_cash_flow': finance_group['ytd_cash_collected'] - expenses_group['ytd_expenses_paid'],
        },
    )
    return {
        'month': month_key(first),
        'property': str(property_ids[0]) if property_param else None,
        'timezones': property_timezones(property_ids),
        'balances_as_of': timezone.now(),
        'ytd': {'start': ytd_start, 'end': ytd_end},
        'occupancy': occupancy(property_ids),
        'finance': _jsonify(finance_group) if finance_group is not None else None,
        'expenses': _jsonify(expenses_group) if expenses_group is not None else None,
        'cash_flow': _jsonify(cash_flow_group) if cash_flow_group is not None else None,
        'redacted': redactor.redacted,
    }


def trend(user, property_param, end_param, months_param):
    property_ids = scoped_property_ids(user, property_param)
    end = parse_month(end_param, param='end', default=month_start(local_today()))
    try:
        count = int(months_param) if months_param else 6
    except ValueError:
        count = 0
    if not 1 <= count <= MAX_TREND_MONTHS:
        raise ValidationError(
            {'months': [_('months must be between 1 and %(max)s.') % {'max': MAX_TREND_MONTHS}]},
            code='invalid_months',
        )

    redactor = Redactor(user)
    can_finance = redactor.allows('view_finance')
    can_expenses = redactor.allows('view_expenses')
    for name, allowed in (('finance', can_finance), ('expenses', can_expenses),
                          ('cash_flow', can_finance and can_expenses)):
        if not allowed:
            redactor.redacted.append(name)

    series = []
    for offset in range(count - 1, -1, -1):
        first = add_months(end, -offset)
        last = month_end(first)
        finance = flow_finance(property_ids, first, last) if can_finance else None
        expenses = (
            {'expenses_paid': expense_services.total_for(property_ids, first, last)} if can_expenses else None
        )
        cash_flow = (
            {'net_cash_flow': finance['cash_collected'] - expenses['expenses_paid']}
            if finance is not None and expenses is not None else None
        )
        series.append({
            'month': month_key(first),
            'finance': _jsonify(finance) if finance is not None else None,
            'expenses': _jsonify(expenses) if expenses is not None else None,
            'cash_flow': _jsonify(cash_flow) if cash_flow is not None else None,
        })
    return {
        'end': month_key(end),
        'months': count,
        'property': str(property_ids[0]) if property_param else None,
        'timezones': property_timezones(property_ids),
        'series': series,
        'redacted': redactor.redacted,
    }
