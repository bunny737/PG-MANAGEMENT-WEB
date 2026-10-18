"""Resident finance block on GET /residents/{id}/ (UX roadmap D6).

Built from apps/billing/selectors.py so the card's figures match Invoices ->
Outstanding and the analytics summary. Shape:

    current_period    the property-timezone month containing today
        period        "YYYY-MM"
        invoices      issued invoices whose billing period starts in it
        total / paid / balance   summed across those invoices
        status        no_invoice | paid | partially_paid | unpaid | overdue
        has_draft     a draft (not yet issued, so not owed) exists for it
    outstanding_total     balance on every open invoice, any period
    overdue_total         the part of it past its due date
    prior_outstanding     outstanding from periods before the current month
    last_payment_date

Drafts are never owed, so they never count toward any figure.
"""
from django.db.models import Max

from apps.billing import selectors
from apps.billing.models import Invoice, Payment
from apps.core.periods import local_today, month_end, month_key, month_start


def _period_status(rows, total, paid, balance, today):
    if not rows:
        return 'no_invoice'
    if balance <= 0:
        return 'paid'
    if any(row.balance > 0 and row.due_date < today for row in rows):
        return 'overdue'
    if paid > 0:
        return 'partially_paid'
    return 'unpaid'


def resident_finance(resident):
    today = local_today()
    first = month_start(today)
    last = month_end(first)

    invoices = selectors.with_money(Invoice.objects.filter(resident=resident))
    issued = invoices.exclude(status=Invoice.Status.DRAFT)
    current = list(issued.filter(period_start__range=(first, last)).order_by('period_start'))
    open_invoices = issued.filter(status__in=selectors.OPEN_STATUSES, balance__gt=0)

    total = sum((row.net_total for row in current), selectors.ZERO)
    paid = sum((row.paid_total for row in current), selectors.ZERO)
    balance = sum((max(row.balance, selectors.ZERO) for row in current), selectors.ZERO)

    return {
        'current_period': {
            'period': month_key(first),
            'invoices': [
                {
                    'id': str(row.id),
                    'period_start': row.period_start,
                    'period_end': row.period_end,
                    'total': str(row.net_total),
                    'paid': str(row.paid_total),
                    'balance': str(row.balance),
                    'due_date': row.due_date,
                    'status': row.status,
                    'is_overdue': row.is_overdue(today),
                }
                for row in current
            ],
            'total': str(total),
            'paid': str(paid),
            'balance': str(balance),
            'status': _period_status(current, total, paid, balance, today),
            'has_draft': invoices.filter(
                status=Invoice.Status.DRAFT, period_start__range=(first, last),
            ).exists(),
        },
        'outstanding_total': str(selectors.total_of(open_invoices, 'balance')),
        'overdue_total': str(selectors.total_of(open_invoices.filter(due_date__lt=today), 'balance')),
        'prior_outstanding': str(
            selectors.total_of(open_invoices.filter(period_start__lt=first), 'balance')
        ),
        'last_payment_date': Payment.objects.filter(invoice__resident=resident).aggregate(
            last=Max('payment_date')
        )['last'],
    }
