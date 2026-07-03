import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModelMixin
from apps.residents.models import Resident


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
