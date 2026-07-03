"""Invoice generation (PRD Module 9).

Builds an invoice as a *list of line items* (invariant 6): accommodation from
the resident's contracted rent (invariant 2/3 — never the rack rate, unchanged
by a temporary allocation), then the active discount as its own negative line
(invariant 4). Ad-hoc charges (electricity, penalty, ...) are added afterward
as more line items. Management has full manual control while the invoice is a
draft.
"""
from django.db import transaction

from apps.audit import log as audit_log
from apps.residents.models import Admission

from .models import Invoice, InvoiceLineItem


def active_discount(resident, on_date):
    """The resident's discount active on a date, or None. Module 07 guarantees
    at most one active at a time (non-overlapping windows)."""
    for discount in resident.discounts.all():
        if discount.is_active_on(on_date):
            return discount
    return None


def _accommodation_label(billing_mode, with_food, partial_note):
    base = 'Accommodation + Food' if with_food else 'Accommodation'
    label = f'{base} ({Admission.BillingMode(billing_mode).label})'
    if partial_note:
        label = f'{label} — {partial_note}'
    return label


@transaction.atomic
def generate_invoice(*, resident, period_start, period_end, due_date,
                     billing_mode=None, actor, request=None):
    """Create a draft invoice with its accommodation and discount lines."""
    admission = resident.admission
    allocation = resident.allocation
    if billing_mode is None:
        billing_mode = admission.billing_mode

    # First-ever invoice for this resident may use the manual partial-month
    # amount captured at admission; otherwise the current contracted rent.
    is_first = not resident.invoices.exists()
    if is_first and admission.first_month_billing_amount is not None:
        base_amount = admission.first_month_billing_amount
        partial_note = admission.first_month_billing_note
    else:
        base_amount = allocation.contracted_rent
        partial_note = ''

    invoice = Invoice.objects.create(
        tenant_id=resident.tenant_id, resident=resident,
        period_start=period_start, period_end=period_end,
        billing_mode=billing_mode, due_date=due_date,
        status=Invoice.Status.DRAFT, created_by=actor,
    )

    with_food = admission.food_preference == Admission.FoodPreference.WITH_FOOD
    InvoiceLineItem.objects.create(
        tenant_id=resident.tenant_id, invoice=invoice,
        line_type=InvoiceLineItem.LineType.ACCOMMODATION,
        label=_accommodation_label(billing_mode, with_food, partial_note),
        amount=base_amount, order=0,
    )

    # Discount is applied on the accommodation charged this period (invariant 4:
    # on contracted rent, not rack rate; for a normal month base == contracted).
    discount = active_discount(resident, period_start)
    if discount is not None:
        InvoiceLineItem.objects.create(
            tenant_id=resident.tenant_id, invoice=invoice,
            line_type=InvoiceLineItem.LineType.DISCOUNT,
            label=f'{discount.get_reason_display()} discount',
            amount=-discount.computed_amount(base_amount), order=1,
        )

    audit_log.record(
        action='invoice.generated', actor=actor, obj=invoice,
        after={'resident': str(resident.id), 'period_start': period_start.isoformat(),
               'total': str(invoice.total)},
        request=request,
    )
    return invoice


def resident_has_invoice_for_period(resident, period_start):
    return resident.invoices.filter(period_start=period_start).exists()
