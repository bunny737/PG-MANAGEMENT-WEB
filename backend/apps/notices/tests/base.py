from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from apps.billing import services as billing_services
from apps.billing.models import Invoice, InvoiceLineItem
from apps.billing.tests.base import BillingAPITestCase
from apps.core.tenancy import tenant_context
from apps.residents.models import Admission, Resident

from apps.notices import services
from apps.notices.models import FoodHoliday, FoodHolidayCredit

JOINED = date(2026, 1, 1)
# Dasara-style holiday used throughout: 4 days, ₹100/day.
H_START, H_END = date(2026, 3, 20), date(2026, 3, 23)
RATE = Decimal('100.00')
APRIL = (date(2026, 4, 1), date(2026, 4, 30))
MAY = (date(2026, 5, 1), date(2026, 5, 31))


@contextmanager
def today(day):
    """Pin the product-timezone date every food-holiday path reads."""
    with mock.patch('apps.notices.credits.local_today', return_value=day), \
            mock.patch('apps.notices.sweep.local_today', return_value=day), \
            mock.patch('apps.billing.services.local_today', return_value=day):
        yield


class NoticesTestCase(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        enqueue = mock.patch.object(billing_services, 'enqueue')
        enqueue.start()
        self.addCleanup(enqueue.stop)
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.room = self.create_room(
            self.create_floor(self.property), room_number='101',
            rack_rate_with_food=Decimal('7000.00'), rack_rate_without_food=Decimal('5500.00'),
        )
        self.made = 0

    # --- fixtures --------------------------------------------------------------

    def admit(self, joining=JOINED, food=Admission.FoodPreference.WITH_FOOD, prop=None, room=None, **admission):
        self.made += 1
        n = self.made
        prop = prop or self.property
        resident = self.create_resident(
            prop, first_name=f'Resident{n}', phone=f'93{n:08d}', status=Resident.Status.RESERVED,
        )
        bed = self.create_bed(room or self.room, bed_number=f'B-{n}')
        self.check_in(resident, bed, joining_date=joining, food_preference=food, **admission)
        with tenant_context(resident.tenant_id):
            return Resident.objects.select_related('admission').get(pk=resident.pk)

    def holiday(self, start=H_START, end=H_END, rate=RATE, adjust=True, name='Dasara', post_notice=True,
                on=date(2026, 4, 10), prop=None):
        prop = prop or self.property
        with today(on), tenant_context(prop.tenant_id):
            return services.create_holiday(
                data={'property': prop, 'name': name, 'start_date': start, 'end_date': end,
                      'adjust_in_bill': adjust, 'rate_per_day': rate},
                post_notice=post_notice, actor=self.owner,
            )

    def edit_holiday(self, holiday, on=date(2026, 4, 10), **data):
        with today(on), tenant_context(holiday.tenant_id):
            return services.update_holiday(holiday=holiday, data=data, actor=self.owner)

    def generate(self, resident, period=APRIL, on=date(2026, 4, 10)):
        with today(on), tenant_context(resident.tenant_id):
            return billing_services.generate_invoice(
                resident=resident, period_start=period[0], period_end=period[1],
                due_date=period[0] + timedelta(days=5), actor=self.owner,
            )

    def issue(self, invoice, on=date(2026, 4, 10)):
        with today(on), tenant_context(invoice.tenant_id):
            billing_services.issue_invoice(invoice_id=invoice.pk, actor=self.owner, on_date=on)
        return self.fresh(invoice)

    def fresh(self, obj):
        with tenant_context(obj.tenant_id):
            obj.refresh_from_db()
        return obj

    def credit(self, holiday, resident):
        with tenant_context(holiday.tenant_id):
            return FoodHolidayCredit.objects.filter(holiday=holiday, resident=resident).first()

    def credits_of(self, resident):
        with tenant_context(resident.tenant_id):
            return list(FoodHolidayCredit.objects.filter(resident=resident).order_by('holiday__start_date'))

    def lines(self, invoice):
        with tenant_context(invoice.tenant_id):
            return [(line.line_type, line.amount) for line in
                    InvoiceLineItem.objects.filter(invoice=invoice).order_by('order', 'created_at')]

    def food_lines(self, invoice):
        return [amount for kind, amount in self.lines(invoice) if kind == InvoiceLineItem.LineType.FOOD_HOLIDAY]

    def total(self, invoice):
        return sum((amount for _kind, amount in self.lines(invoice)), Decimal('0.00'))

    def draft(self, resident, period, total):
        """A draft with one accommodation line of `total`, created directly."""
        return self.create_invoice(resident, period[0], period_end=period[1], total=total,
                                   status=Invoice.Status.DRAFT)

    def holidays(self):
        with tenant_context(self.tenant.id):
            return list(FoodHoliday.objects.all())
