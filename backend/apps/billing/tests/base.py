from datetime import date
from decimal import Decimal

from apps.core.tenancy import tenant_context
from apps.residents.tests.base import ResidentAPITestCase

from apps.billing.models import Discount, Payment


class BillingAPITestCase(ResidentAPITestCase):
    @staticmethod
    def create_discount(resident, discount_type=Discount.DiscountType.FIXED,
                        discount_value=Decimal('500.00'), reason=Discount.Reason.LOYALTY,
                        valid_from=None, valid_until=None, **kwargs):
        if valid_from is None:
            valid_from = date(2026, 7, 1)
        with tenant_context(resident.tenant_id):
            return Discount.objects.create(
                tenant_id=resident.tenant_id, resident=resident, discount_type=discount_type,
                discount_value=discount_value, reason=reason,
                valid_from=valid_from, valid_until=valid_until, **kwargs,
            )

    @staticmethod
    def create_payment(invoice, amount=Decimal('1000.00'), payment_date=None,
                       payment_mode=Payment.Mode.CASH, **kwargs):
        if payment_date is None:
            payment_date = date(2026, 7, 5)
        with tenant_context(invoice.tenant_id):
            return Payment.objects.create(
                tenant_id=invoice.tenant_id, invoice=invoice, amount=amount,
                payment_date=payment_date, payment_mode=payment_mode, **kwargs
            )
