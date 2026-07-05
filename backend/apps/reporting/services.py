"""Row-builders for the four PRD Module 23 exports. Each returns
(columns, rows) — rows are lists of plain, already-formatted values, ready
for any of the three renderers in export.py. Scoped the same way every other
list endpoint in the platform is: visible_property_ids() (Owner/Super Admin
see the whole tenant, Manager only assigned properties); an explicit
?property= filter for a property outside that set silently returns nothing,
same as filtering any other list endpoint by an id you can't see."""
from datetime import date

from apps.billing.models import Invoice, Payment
from apps.properties.models import Bed, Property
from apps.properties.services import visible_property_ids
from apps.residents.models import Resident


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


def payment_rows(user, property_id=None):
    ids = visible_property_ids(user)
    queryset = Payment.objects.filter(invoice__resident__property_id__in=ids).select_related(
        'invoice__resident__property', 'recorded_by'
    )
    if property_id:
        queryset = queryset.filter(invoice__resident__property_id=property_id)

    columns = ['Payment Date', 'Resident', 'Property', 'Invoice Period', 'Amount', 'Mode', 'Reference', 'Recorded By']
    rows = []
    for payment in queryset.order_by('-payment_date', '-created_at'):
        invoice = payment.invoice
        resident = invoice.resident
        rows.append([
            payment.payment_date.isoformat(), str(resident), resident.property.name,
            f'{invoice.period_start.isoformat()} to {invoice.period_end.isoformat()}',
            str(payment.amount), payment.get_payment_mode_display(), payment.reference,
            str(payment.recorded_by) if payment.recorded_by else '',
        ])
    return columns, rows


def outstanding_dues_rows(user, property_id=None):
    ids = visible_property_ids(user)
    queryset = Invoice.objects.filter(
        resident__property_id__in=ids, status__in=(Invoice.Status.ISSUED, Invoice.Status.PARTIALLY_PAID),
    ).select_related('resident__property').prefetch_related('line_items', 'payments')
    if property_id:
        queryset = queryset.filter(resident__property_id=property_id)

    columns = ['Resident', 'Property', 'Period', 'Due Date', 'Total', 'Balance Due', 'Overdue']
    today = date.today()
    rows = []
    for invoice in queryset.order_by('due_date'):
        # A draft invoice is excluded by the status filter above; balance_due
        # <= 0 here means fully paid — not an outstanding due (invariant:
        # never a stored field, same as InvoiceViewSet.outstanding).
        if invoice.balance_due <= 0:
            continue
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
