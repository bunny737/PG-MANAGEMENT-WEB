"""Daily food-holiday credit allocation (Module 24), run at 05:30 IST by the
beat task `notices.allocate_food_holiday_credits` (seeded by migration 0002;
ops fallback: `manage.py allocate_food_holiday_credits [--date YYYY-MM-DD]`).

For every property with an adjust-in-bill holiday that has ended, or with a
pending credit, it creates the credits now due and offers pending ones to the
residents' drafts again — so a credit that didn't fit yesterday (draft too
small) is retried. One effective date for the whole run; each property in its
own transaction under its tenant's RLS context, Settings locked first, so one
property failing never rolls back another.
"""
import logging

from django.db import transaction
from django.db.models import Q

from apps.core.periods import local_today
from apps.core.tenancy import tenant_context

from . import credits
from .models import FoodHoliday, FoodHolidayCredit

logger = logging.getLogger(__name__)


def _residents_to_process(property_id, on_date):
    from apps.residents.models import Admission, Resident

    pending = FoodHolidayCredit.objects.filter(
        resident__property_id=property_id, status=FoodHolidayCredit.Status.PENDING,
    ).values_list('resident_id', flat=True)
    # Current with-food residents of a property that has an ended adjusting
    # holiday may be missing a credit row (admitted later, or the holiday just
    # ended); ensure_credits creates only the missing ones.
    has_ended_holiday = FoodHoliday.objects.filter(
        property_id=property_id, adjust_in_bill=True, end_date__lt=on_date,
    ).exists()
    current = Resident.objects.none()
    if has_ended_holiday:
        current = Resident.objects.filter(
            property_id=property_id, status__in=(Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD),
            admission__food_preference=Admission.FoodPreference.WITH_FOOD,
        ).values_list('pk', flat=True)
    return sorted(set(pending) | set(current))


def run_for_property(property_id, on_date):
    from apps.billing.services import lock_property_settings
    from apps.residents.models import Resident

    created = attached = 0
    with transaction.atomic():
        lock_property_settings(property_id)
        for resident_id in _residents_to_process(property_id, on_date):
            resident = Resident.objects.select_related('admission').get(pk=resident_id)
            created += len(credits.ensure_credits(resident, on_date=on_date))
            attached += credits.allocate_pending(resident, on_date=on_date)
    return created, attached


def allocate_food_holiday_credits(on_date=None):
    from apps.properties.models import Property

    on_date = on_date or local_today()
    with tenant_context(is_super_admin=True):
        holiday_props = FoodHoliday.objects.filter(adjust_in_bill=True, end_date__lt=on_date).values('property_id')
        pending_props = FoodHolidayCredit.objects.filter(
            status=FoodHolidayCredit.Status.PENDING,
        ).values('resident__property_id')
        properties = list(
            Property.objects.filter(Q(pk__in=holiday_props) | Q(pk__in=pending_props))
            .order_by('tenant_id', 'created_at').values_list('pk', 'tenant_id')
        )
    totals = {'properties': 0, 'created': 0, 'attached': 0, 'failed': 0}
    for property_id, tenant_id in properties:
        try:
            with tenant_context(tenant_id):
                created, attached = run_for_property(property_id, on_date)
        except Exception:
            logger.exception('Food-holiday credits: property %s failed', property_id)
            totals['failed'] += 1
            continue
        totals['properties'] += 1
        totals['created'] += created
        totals['attached'] += attached
    return totals
