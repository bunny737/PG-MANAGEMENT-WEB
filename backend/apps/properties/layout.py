"""Property layout (UX roadmap D2): buildings -> floors -> rooms -> beds in
one response, replacing the per-floor/per-room walkers the clients used.

Each bed carries three INDEPENDENT attributes:

    availability  the bed's own status (available / occupied / reserved / maintenance)
    resident      the CURRENT occupant (Active or Notice Period allocation), or null
    payment       that occupant's payment state for the requested period, or null

`payment.status` (first match wins):
    overdue     the resident has any overdue balance (any period)
    no_invoice  no issued invoice whose billing period starts in the month
    paid        the period's invoices are settled
    due         a period balance is due within PlatformConfig.payment_due_soon_days
                (or already past due but not yet overdue — i.e. due today)
    upcoming    a period balance is due later than that

A previous occupant's unpaid invoices never colour a vacant bed; they show
up in Invoices -> Outstanding and in the property `finance` block.

Occupancy: occupancy_rate = occupied / (total - maintenance) as a percentage
with one decimal; reserved beds are neither vacant nor occupied. The rate is
null when the denominator is 0 (no beds, or all under maintenance).

Redaction (authorization model): `resident` needs view_resident_profile;
`payment` and `finance` need view_finance. Room/bed rack rates are layout
configuration and are always included.
"""
from collections import defaultdict
from datetime import timedelta

from apps.billing import selectors
from apps.billing.models import Invoice
from apps.core.models import PlatformConfig
from apps.core.periods import local_today, month_end, month_key
from apps.core.redaction import Redactor
from apps.residents.models import Allocation, Resident, Vacate

from .models import Bed, Building, Floor, Room

CURRENT_RESIDENT_STATUSES = (Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD)


def empty_counts():
    return {'total': 0, 'occupied': 0, 'reserved': 0, 'maintenance': 0, 'available': 0}


def add_bed(counts, status):
    counts['total'] += 1
    counts[status] += 1


def with_rate(counts):
    denominator = counts['total'] - counts['maintenance']
    rate = None if denominator <= 0 else round(counts['occupied'] * 100 / denominator, 1)
    return {**counts, 'occupancy_rate': rate}


def bed_counts(beds):
    counts = empty_counts()
    for status in beds:
        add_bed(counts, status)
    return with_rate(counts)


def _money(value):
    return str(value)


def _payment_states(resident_ids, first, today, soon_days):
    """resident_id -> {status, period_balance, overdue_balance}."""
    last = month_end(first)
    invoices = selectors.with_money(
        Invoice.objects.filter(resident_id__in=resident_ids).exclude(status=Invoice.Status.DRAFT)
    )
    overdue = defaultdict(lambda: selectors.ZERO)
    period = defaultdict(list)
    for invoice in invoices:
        if (invoice.status in selectors.OPEN_STATUSES and invoice.balance > 0
                and invoice.due_date < today):
            overdue[invoice.resident_id] += invoice.balance
        if first <= invoice.period_start <= last:
            period[invoice.resident_id].append(invoice)

    due_by = today + timedelta(days=soon_days)
    states = {}
    for resident_id in resident_ids:
        rows = period.get(resident_id, [])
        period_balance = sum((max(inv.balance, selectors.ZERO) for inv in rows), selectors.ZERO)
        if overdue[resident_id] > 0:
            status = 'overdue'
        elif not rows:
            status = 'no_invoice'
        elif period_balance <= 0:
            status = 'paid'
        elif any(inv.balance > 0 and inv.due_date <= due_by for inv in rows):
            status = 'due'
        else:
            status = 'upcoming'
        states[resident_id] = {
            'status': status,
            'period_balance': _money(period_balance),
            'overdue_balance': _money(overdue[resident_id]),
        }
    return states


def _finance_block(prop, today, occupant_ids):
    """Property dues banner: every resident of the property, past or present."""
    open_invoices = selectors.outstanding(Invoice.objects.filter(resident__property=prop))
    owing = set(open_invoices.values_list('resident_id', flat=True).distinct())
    return {
        'outstanding_total': _money(selectors.total_of(open_invoices, 'balance')),
        'overdue_total': _money(
            selectors.total_of(open_invoices.filter(due_date__lt=today), 'balance')
        ),
        'open_invoice_count': open_invoices.count(),
        'residents_with_balance_count': len(owing),
        'occupied_beds_with_balance_count': len(owing & set(occupant_ids)),
    }


def build_layout(prop, user, period_first):
    today = local_today()
    redactor = Redactor(user)
    soon_days = PlatformConfig.get().payment_due_soon_days

    buildings = list(Building.objects.filter(property=prop).order_by('order'))
    floors = list(Floor.objects.filter(building__property=prop).order_by('order'))
    rooms = list(Room.objects.filter(floor__building__property=prop).order_by('room_number'))
    beds = list(Bed.objects.filter(room__floor__building__property=prop).order_by('bed_number'))

    allocations = {
        allocation.allocated_bed_id: allocation
        for allocation in Allocation.objects.filter(
            allocated_bed__in=[bed.id for bed in beds],
            resident__status__in=CURRENT_RESIDENT_STATUSES,
        ).select_related('resident')
    }
    occupant_ids = [allocation.resident_id for allocation in allocations.values()]
    open_vacates = {
        vacate.resident_id: vacate
        for vacate in Vacate.objects.filter(
            resident_id__in=occupant_ids, cancelled_date__isnull=True, actual_vacate_date__isnull=True,
        )
    }
    reserved_names = {
        resident.id: str(resident)
        for resident in Resident.objects.filter(
            id__in=[bed.reserved_for_id for bed in beds if bed.reserved_for_id]
        )
    }

    payments = redactor.group(
        'payment', ['view_finance'],
        lambda: _payment_states(occupant_ids, period_first, today, soon_days),
    )
    can_see_residents = redactor.allows('view_resident_profile')
    if not can_see_residents:
        redactor.redacted.append('resident')

    def resident_payload(allocation):
        if allocation is None or not can_see_residents:
            return None
        resident = allocation.resident
        vacate = open_vacates.get(resident.id)
        return {
            'id': str(resident.id),
            'name': str(resident),
            'phone': resident.phone,
            'status': resident.status,
            'on_notice': resident.status == Resident.Status.NOTICE_PERIOD,
            'notice_date': vacate.notice_given_date if vacate else None,
            'expected_vacate_date': vacate.expected_vacate_date if vacate else None,
            'is_temporary': allocation.is_temporary,
        }

    def bed_payload(bed):
        allocation = allocations.get(bed.id)
        reserved_for = None
        if bed.reserved_for_id and can_see_residents:
            reserved_for = {'id': str(bed.reserved_for_id), 'name': reserved_names.get(bed.reserved_for_id)}
        return {
            'id': str(bed.id),
            'bed_number': bed.bed_number,
            'availability': bed.status,
            'reserved_for': reserved_for,
            'reserved_until': bed.reserved_until,
            'rack_rate_with_food': _money(bed.rack_rate(with_food=True)),
            'rack_rate_without_food': _money(bed.rack_rate(with_food=False)),
            'resident': resident_payload(allocation),
            'payment': (
                payments.get(allocation.resident_id)
                if payments is not None and allocation is not None else None
            ),
        }

    beds_by_room = defaultdict(list)
    for bed in beds:
        beds_by_room[bed.room_id].append(bed)
    rooms_by_floor = defaultdict(list)
    for room in rooms:
        rooms_by_floor[room.floor_id].append(room)
    floors_by_building = defaultdict(list)
    for floor in floors:
        floors_by_building[floor.building_id].append(floor)

    def room_payload(room):
        room_beds = beds_by_room[room.id]
        return {
            'id': str(room.id),
            'room_number': room.room_number,
            'sharing_type': room.sharing_type,
            'category': room.category,
            'status': room.status,
            'rack_rate_with_food': _money(room.rack_rate_with_food),
            'rack_rate_without_food': _money(room.rack_rate_without_food),
            'counts': bed_counts(bed.status for bed in room_beds),
            'beds': [bed_payload(bed) for bed in room_beds],
        }

    def floor_payload(floor):
        floor_rooms = rooms_by_floor[floor.id]
        return {
            'id': str(floor.id),
            'name': floor.name,
            'order': floor.order,
            'counts': bed_counts(bed.status for room in floor_rooms for bed in beds_by_room[room.id]),
            'rooms': [room_payload(room) for room in floor_rooms],
        }

    def building_payload(building):
        building_floors = floors_by_building[building.id]
        return {
            'id': str(building.id),
            'name': building.name,
            'order': building.order,
            'counts': bed_counts(
                bed.status for floor in building_floors
                for room in rooms_by_floor[floor.id] for bed in beds_by_room[room.id]
            ),
            'floors': [floor_payload(floor) for floor in building_floors],
        }

    return {
        'property': {'id': str(prop.id), 'name': prop.name},
        'period': month_key(period_first),
        'as_of': today,
        'due_soon_days': soon_days,
        'counts': bed_counts(bed.status for bed in beds),
        'finance': redactor.group(
            'finance', ['view_finance'], lambda: _finance_block(prop, today, occupant_ids),
        ),
        'buildings': [building_payload(building) for building in buildings],
        'redacted': redactor.redacted,
    }
