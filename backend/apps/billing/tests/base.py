from datetime import date
from decimal import Decimal

from apps.core.tenancy import tenant_context
from apps.residents.tests.base import ResidentAPITestCase

from apps.billing.models import Discount, Invoice, InvoiceLineItem, Payment
from apps.core.modules import role_default_levels, storage_value


class BillingAPITestCase(ResidentAPITestCase):
    @staticmethod
    def create_invoice(resident, period_start, total=Decimal('7000.00'), due_date=None,
                       status=Invoice.Status.ISSUED, discount=None, period_end=None):
        """An invoice with one accommodation line (and an optional discount
        line), created directly — no advance application, no emails."""
        if due_date is None:
            due_date = period_start.replace(day=10)
        if period_end is None:
            period_end = period_start.replace(day=28)
        with tenant_context(resident.tenant_id):
            invoice = Invoice.objects.create(
                tenant_id=resident.tenant_id, resident=resident, period_start=period_start,
                period_end=period_end, billing_mode='monthly', due_date=due_date, status=status,
                issue_date=None if status == Invoice.Status.DRAFT else period_start,
            )
            InvoiceLineItem.objects.create(
                tenant_id=resident.tenant_id, invoice=invoice, line_type='accommodation',
                label='Accommodation', amount=total, order=0,
            )
            if discount:
                InvoiceLineItem.objects.create(
                    tenant_id=resident.tenant_id, invoice=invoice, line_type='discount',
                    label='Discount', amount=-discount, order=1,
                )
            return invoice

    def pay(self, invoice, amount, payment_date=None):
        """Record through the model and resync the invoice status, like the service."""
        payment = self.create_payment(invoice, amount=amount, payment_date=payment_date or invoice.period_start)
        with tenant_context(invoice.tenant_id):
            invoice.refresh_from_db()
            invoice.recompute_status()
        return payment

    @staticmethod
    def customize(user, **levels):
        """Give a staff user a custom module_access (role defaults + changes)."""
        resolved = role_default_levels(user.role)
        resolved.update(levels)
        user.module_access = storage_value(user.role, resolved)
        user.save(update_fields=['module_access', 'updated_at'])
        return user
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
