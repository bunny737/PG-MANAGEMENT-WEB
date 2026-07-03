import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModelMixin
from apps.residents.models import Admission, Resident


class Discount(TenantModelMixin):
    """A per-resident discount applied ON TOP OF contracted_rent (invariant 4),
    never on the rack rate. Module 08 renders it as its own invoice line.

    Scoped to the resident (== allocation level, since Allocation is 1:1 with
    Resident) so two residents in the same room can hold different discounts.
    At most one discount may be active for a resident on any given date — no
    overlapping validity windows (see DiscountSerializer)."""

    class DiscountType(models.TextChoices):
        FIXED = 'fixed', _('Fixed Amount')
        PERCENTAGE = 'percentage', _('Percentage')

    class Reason(models.TextChoices):
        LOYALTY = 'loyalty', _('Loyalty')
        REFERRAL = 'referral', _('Referral')
        CORPORATE = 'corporate', _('Corporate')
        NEGOTIATED = 'negotiated', _('Negotiated')
        SEASONAL = 'seasonal', _('Seasonal')
        OTHER = 'other', _('Other')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resident = models.ForeignKey(Resident, on_delete=models.PROTECT, related_name='discounts')
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices)
    discount_value = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    note = models.TextField(blank=True)
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)  # null = indefinite
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='discounts_approved'
    )

    class Meta:
        db_table = 'discounts'
        ordering = ['-valid_from', '-created_at']

    def __str__(self):
        return f'{self.get_discount_type_display()} discount for {self.resident}'

    def is_active_on(self, on_date):
        if on_date < self.valid_from:
            return False
        if self.valid_until is not None and on_date > self.valid_until:
            return False
        return True

    def computed_amount(self, contracted_rent):
        """The discount figure for a given contracted rent (invariant 4).
        Module 08 owns the final invoice math — including clamping payable to
        >= 0 — so this deliberately does not cap a fixed discount at the rent."""
        if self.discount_type == self.DiscountType.PERCENTAGE:
            return (contracted_rent * self.discount_value / Decimal('100')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        return self.discount_value


class Invoice(TenantModelMixin):
    """A resident's invoice for one billing period (PRD Module 9). Invariant 6:
    the invoice is a *list of line items* (InvoiceLineItem) — the engine never
    hardcodes fixed charge fields, so future add-ons drop in as new lines with
    zero engine changes. `total` is summed from the lines, never stored."""

    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        ISSUED = 'issued', _('Issued')
        PARTIALLY_PAID = 'partially_paid', _('Partially Paid')
        PAID = 'paid', _('Paid')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resident = models.ForeignKey(Resident, on_delete=models.PROTECT, related_name='invoices')
    period_start = models.DateField()
    period_end = models.DateField()
    billing_mode = models.CharField(max_length=10, choices=Admission.BillingMode.choices)
    issue_date = models.DateField(null=True, blank=True)  # set when status -> issued
    due_date = models.DateField()
    # paid / partially_paid are driven by Module 09 (Payments); Module 08 only
    # sets draft/issued. "Overdue" is derived (is_overdue), never stored.
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='invoices_created'
    )

    class Meta:
        db_table = 'invoices'
        ordering = ['-period_start', '-created_at']

    def __str__(self):
        return f'Invoice {self.resident} {self.period_start}'

    @property
    def total(self):
        return sum((item.amount for item in self.line_items.all()), Decimal('0.00'))

    def is_overdue(self, on_date):
        # No payments in Module 08, so an issued invoice past its due date is
        # overdue; Module 09 will factor in amount paid.
        return self.status == self.Status.ISSUED and self.due_date < on_date


class InvoiceLineItem(TenantModelMixin):
    """One charge (or discount) line on an invoice (invariant 6). `amount` is
    negative for a discount line. Fully editable while the invoice is a draft
    so management has full manual control (partial months, transfer splits,
    ad-hoc charges) per the PRD."""

    class LineType(models.TextChoices):
        ACCOMMODATION = 'accommodation', _('Accommodation')
        FOOD = 'food', _('Food')
        ELECTRICITY = 'electricity', _('Electricity')
        WATER = 'water', _('Water')
        LAUNDRY = 'laundry', _('Laundry')
        ADDON = 'addon', _('Add-on Service')
        ADDITIONAL = 'additional', _('Additional')
        DISCOUNT = 'discount', _('Discount')
        PENALTY = 'penalty', _('Late Payment Penalty')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='line_items')
    line_type = models.CharField(max_length=15, choices=LineType.choices)
    label = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)  # negative for discounts
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'invoice_line_items'
        ordering = ['order', 'created_at']

    def __str__(self):
        return f'{self.label}: {self.amount}'
