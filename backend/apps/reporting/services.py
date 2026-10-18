"""Row-builders for the four PRD Module 23 exports. Each returns
(columns, rows) — rows are lists of plain, already-formatted values, ready
for any of the three renderers in export.py. Scoped the same way every other
list endpoint in the platform is: visible_property_ids() (Owner/Super Admin
see the whole tenant, Manager only assigned properties); an explicit
?property= filter for a property outside that set silently returns nothing,
same as filtering any other list endpoint by an id you can't see."""
from django.utils.translation import gettext_lazy as _

from apps.billing import selectors
from apps.billing.models import Invoice, Payment
from apps.core.periods import local_today, month_end
from apps.expenses import services as expense_services
from apps.properties.models import Bed, Property
from apps.properties.services import scoped_property_ids, visible_property_ids
from apps.residents.models import Resident

from . import analytics


def resident_rows(user, property_id=None):
    ids = visible_property_ids(user)
    queryset = Resident.objects.filter(property_id__in=ids).select_related('property')
    if property_id:
        queryset = queryset.filter(property_id=property_id)

    columns = ['First Name', 'Last Name', 'Phone', 'Email', 'Property', 'Status', 'Room / Bed']
    rows = []
    for resident in queryset.select_related('allocation__allocated_bed__room').order_by('first_name', 'last_name'):
        allocation = getattr(resident, 'allocation', None)
        bed_label = ''
        if allocation is not None:
            bed = allocation.allocated_bed
            bed_label = f'{bed.room.room_number} ({bed.bed_number})'
        rows.append([
            resident.first_name, resident.last_name, resident.phone, resident.email,
            resident.property.name, resident.get_status_display(), bed_label,
        ])
    return columns, rows


def payment_rows(user, property_id=None, month=None):
    ids = visible_property_ids(user)
    queryset = Payment.objects.filter(invoice__resident__property_id__in=ids).select_related(
        'invoice__resident__property', 'recorded_by'
    )
    if property_id:
        queryset = queryset.filter(invoice__resident__property_id=property_id)
    if month:
        queryset = queryset.filter(payment_date__range=(month, month_end(month)))

    # Receipt No. is appended last so existing column positions don't shift.
    columns = [
        'Payment Date', 'Resident', 'Property', 'Invoice Period', 'Amount', 'Mode',
        'Reference', 'Recorded By', 'Receipt No.',
    ]
    rows = []
    for payment in queryset.order_by('-payment_date', '-created_at'):
        invoice = payment.invoice
        resident = invoice.resident
        rows.append([
            payment.payment_date.isoformat(), str(resident), resident.property.name,
            f'{invoice.period_start.isoformat()} to {invoice.period_end.isoformat()}',
            str(payment.amount), payment.get_payment_mode_display(), payment.reference,
            str(payment.recorded_by) if payment.recorded_by else '', payment.receipt_number or '',
        ])
    return columns, rows


def outstanding_dues_rows(user, property_id=None, period=None):
    """Same definition as Invoices -> Outstanding (apps/billing/selectors.py);
    `period` narrows to invoices whose billing period starts in that month."""
    ids = visible_property_ids(user)
    queryset = selectors.outstanding(
        Invoice.objects.filter(resident__property_id__in=ids)
    ).select_related('resident__property')
    if property_id:
        queryset = queryset.filter(resident__property_id=property_id)
    if period:
        queryset = queryset.filter(period_start__range=(period, month_end(period)))

    columns = ['Resident', 'Property', 'Period', 'Due Date', 'Total', 'Balance Due', 'Overdue']
    today = local_today()
    rows = []
    for invoice in queryset.prefetch_related('line_items', 'payments').order_by('due_date'):
        rows.append([
            str(invoice.resident), invoice.resident.property.name,
            f'{invoice.period_start.isoformat()} to {invoice.period_end.isoformat()}',
            invoice.due_date.isoformat(), str(invoice.total), str(invoice.balance_due),
            'Yes' if invoice.is_overdue(today) else 'No',
        ])
    return columns, rows


def occupancy_rows(user, property_id=None):
    ids = visible_property_ids(user)
    properties = Property.objects.filter(id__in=ids)
    if property_id:
        properties = properties.filter(id=property_id)

    columns = ['Property', 'Total Beds', 'Occupied', 'Available', 'Reserved', 'Maintenance', 'Occupancy %']
    rows = []
    for prop in properties.order_by('name'):
        beds = Bed.objects.filter(room__floor__building__property=prop)
        total = beds.count()
        occupied = beds.filter(status=Bed.Status.OCCUPIED).count()
        available = beds.filter(status=Bed.Status.AVAILABLE).count()
        reserved = beds.filter(status=Bed.Status.RESERVED).count()
        maintenance = beds.filter(status=Bed.Status.MAINTENANCE).count()
        occupancy_pct = round(occupied / total * 100, 1) if total else 0.0
        rows.append([prop.name, total, occupied, available, reserved, maintenance, occupancy_pct])
    return columns, rows


def expense_rows(user, property_id=None, month=None):
    ids = visible_property_ids(user)
    queryset = expense_services.live_expenses().filter(property_id__in=ids).select_related(
        'property', 'category', 'created_by'
    )
    if property_id:
        queryset = queryset.filter(property_id=property_id)
    if month:
        queryset = queryset.filter(date__range=(month, month_end(month)))

    columns = [str(_('Date')), str(_('Property')), str(_('Category')), str(_('Amount')),
               str(_('Mode')), str(_('Note')), str(_('Recorded By'))]
    rows = [
        [
            expense.date.isoformat(), expense.property.name, str(expense.category.label),
            str(expense.amount), expense.get_payment_mode_display(), expense.note,
            str(expense.created_by) if expense.created_by else '',
        ]
        for expense in queryset.order_by('-date', '-created_at')
    ]
    return columns, rows


def cash_flow_rows(user, property_id, month):
    """One month's cash-flow statement (D0 cash basis — not accrual profit).
    ?property= outside the caller's scope is a 404, as on analytics."""
    ids = scoped_property_ids(user, property_id)
    last = month_end(month)
    flow = analytics.flow_finance(ids, month, last)
    by_category = expense_services.summary(
        expense_services.live_expenses().filter(property_id__in=ids, date__range=(month, last))
    )
    expenses_paid = expense_services.total_for(ids, month, last)

    rows = [
        [str(_('Gross receipts')), str(flow['gross_receipts'])],
        [str(_('Refunds paid')), str(flow['refunds_paid'])],
        [str(_('Cash collected')), str(flow['cash_collected'])],
    ]
    rows += [[str(_('Expense: %(name)s') % {'name': row['name']}), row['total']]
             for row in by_category['by_category']]
    rows += [
        [str(_('Total expenses')), str(expenses_paid)],
        [str(_('Net cash flow')), str(flow['cash_collected'] - expenses_paid)],
    ]
    return [str(_('Line')), str(_('Amount (INR)'))], rows
