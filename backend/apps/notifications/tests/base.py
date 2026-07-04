from decimal import Decimal

from django.urls import reverse

from apps.billing.tests.base import BillingAPITestCase
from apps.core.tenancy import tenant_context
from apps.residents.models import Resident

from apps.notifications.models import NotificationLog

PERIOD = {'period_start': '2026-07-01', 'period_end': '2026-07-31', 'due_date': '2026-07-10'}


class NotificationAPITestCase(BillingAPITestCase):
    """Shared fixture: a checked-in resident with an email on file, ready to
    have an invoice generated/issued or a payment recorded against them."""

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.floor = self.create_floor(self.property)
        self.room = self.create_room(
            self.floor, room_number='101', sharing_type=4, category='ac',
            rack_rate_with_food=Decimal('7000.00'), rack_rate_without_food=Decimal('5500.00'),
        )
        self.bed = self.create_bed(self.room, bed_number='101-A')
        self.resident = self.create_resident(
            self.property, status=Resident.Status.RESERVED, email='resident@example.com',
        )
        self.check_in(self.resident, self.bed)
        self.authenticate(self.owner)

    def generate_invoice(self, resident=None, **overrides):
        resident = resident or self.resident
        payload = {'resident': str(resident.id), **PERIOD}
        payload.update(overrides)
        return self.client.post(reverse('invoice-list'), payload).data

    def issue_invoice(self, invoice_id):
        return self.client.post(reverse('invoice-issue', args=[invoice_id]))

    def pay(self, invoice_id, **overrides):
        payload = {
            'invoice': invoice_id, 'amount': '2000.00',
            'payment_date': '2026-07-05', 'payment_mode': 'upi',
        }
        payload.update(overrides)
        return self.client.post(reverse('payment-list'), payload)

    @staticmethod
    def notifications_for(tenant_id, **filters):
        with tenant_context(tenant_id):
            return list(NotificationLog.objects.filter(tenant_id=tenant_id, **filters))
