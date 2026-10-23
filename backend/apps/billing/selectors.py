"""Database-side money figures for invoices (metric glossary D0).

Every summary number and every drill-down list is built from these helpers,
so a figure and the list it drills into share one definition:

    net_total     sum of line items (after discount lines)          — Invoice.total
    paid_total    sum of payments allocated to the invoice           — Invoice.amount_paid
    balance       net_total - paid_total                             — Invoice.balance_due
    capped_paid   min(paid_total, max(net_total, 0))                 — counts toward period_collected

"Outstanding" = an issued or partially-paid invoice with balance > 0, any
period. Drafts are never owed. "Overdue" = outstanding with due_date before
today. Neither is a stored status (Invoice.status only holds draft / issued /
partially_paid / paid).

Refunds: there is no rent-refund record in v1 (owner decision 2026-10-16), so
"net payments allocated" == payments allocated. A payment deleted as a
correction is a reversal and simply no longer exists.
"""
from decimal import Decimal

from django.db.models import DecimalField, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Greatest, Least

from .models import Invoice, InvoiceLineItem, Payment

MONEY = DecimalField(max_digits=14, decimal_places=2)
ZERO = Decimal('0.00')
OPEN_STATUSES = (Invoice.Status.ISSUED, Invoice.Status.PARTIALLY_PAID)


def _zero():
    return Value(ZERO, output_field=MONEY)


def _sum_by_invoice(model):
    rows = (
        model.objects.filter(invoice=OuterRef('pk')).order_by()
        .values('invoice').annotate(total=Sum('amount')).values('total')[:1]
    )
    return Coalesce(Subquery(rows, output_field=MONEY), _zero())


def with_money(queryset):
    """Annotate net_total / paid_total / balance / capped_paid. Subqueries
    (not joins) so line items and payments don't multiply each other."""
    return queryset.annotate(
        net_total=_sum_by_invoice(InvoiceLineItem),
        paid_total=_sum_by_invoice(Payment),
    ).annotate(
        balance=F('net_total') - F('paid_total'),
        capped_paid=Least(F('paid_total'), Greatest(F('net_total'), _zero())),
    )


def outstanding(queryset):
    return with_money(queryset).filter(status__in=OPEN_STATUSES, balance__gt=0)


def overdue(queryset, today):
    return outstanding(queryset).filter(due_date__lt=today)


def total_of(queryset, field):
    """Sum an annotated money field across a queryset (Decimal, never None)."""
    return queryset.aggregate(value=Coalesce(Sum(field), _zero()))['value']


def capped_paid(invoice):
    """Python-side capped_paid for an invoice instance (prefetched rows)."""
    return min(invoice.amount_paid, max(invoice.total, ZERO))
