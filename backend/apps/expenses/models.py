import os
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModelMixin
from apps.properties.models import Property

# System categories every tenant gets (seeded lazily per tenant — see
# services.ensure_system_categories). Keyed by a stable `code`; the label is
# translated at render time (invariant 7), never stored.
SYSTEM_CATEGORIES = {
    'rent_lease': _('Building rent / lease'),
    'electricity': _('Electricity'),
    'water': _('Water'),
    'internet': _('Internet'),
    'gas': _('Gas / LPG'),
    'groceries': _('Groceries & food supplies'),
    'salaries': _('Staff salaries'),
    'maintenance': _('Repairs & maintenance'),
    'cleaning': _('Cleaning & housekeeping'),
    'laundry': _('Laundry'),
    'furniture': _('Furniture & equipment'),
    'taxes': _('Taxes & fees'),
    'marketing': _('Marketing'),
    'other': _('Other'),
}


class ExpenseCategory(TenantModelMixin):
    """An expense category with a stable id. System categories (`code` set,
    `is_system`) are seeded per tenant and can't be renamed, archived or
    deleted. Custom categories (`name` set) can be renamed and archived, and
    deleted only while unused. An archived category is hidden from pickers
    but still labels its existing expenses."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=30, blank=True)
    # Owner-entered label for a custom category (invariant 7 governs UI
    # chrome, not owner data — same as TenantFeature.label).
    name = models.CharField(max_length=60, blank=True)
    is_system = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'expense_categories'
        ordering = ['-is_system', 'order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'code'], condition=Q(is_system=True),
                name='unique_system_expense_category',
            ),
            models.UniqueConstraint(
                'tenant_id', Lower('name'), condition=Q(is_system=False),
                name='unique_custom_expense_category_name',
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_system=True) & ~Q(code='') | Q(is_system=False) & Q(code='') & ~Q(name='')
                ),
                name='expense_category_system_xor_custom',
            ),
        ]

    def __str__(self):
        return str(self.label)

    @property
    def label(self):
        if self.is_system:
            return SYSTEM_CATEGORIES.get(self.code, self.code)
        return self.name


def expense_attachment_path(instance, filename):
    # Random name: the original filename is user data and can leak into the
    # signed URL; the extension is kept so the browser/share sheet picks the
    # right viewer.
    extension = os.path.splitext(filename)[1].lower()[:10]
    return f'expenses/{instance.tenant_id}/{instance.id}/{uuid.uuid4().hex}{extension}'


class Expense(TenantModelMixin):
    """Money the PG spent (UX roadmap D5) — the outflow side of the cash-flow
    view. `deleted_at` is a soft delete: a deleted expense is excluded from
    every list, total and export but kept for the audit trail."""

    class Mode(models.TextChoices):
        UPI = 'upi', _('UPI')
        CASH = 'cash', _('Cash')
        BANK_TRANSFER = 'bank_transfer', _('Bank Transfer')
        CARD = 'card', _('Card')
        CHEQUE = 'cheque', _('Cheque')
        OTHER = 'other', _('Other')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name='expenses')
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name='expenses')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    payment_mode = models.CharField(max_length=15, choices=Mode.choices)
    note = models.TextField(blank=True)
    attachment = models.FileField(upload_to=expense_attachment_path, null=True, blank=True, max_length=255)
    attachment_content_type = models.CharField(max_length=50, blank=True)
    idempotency_key = models.CharField(max_length=100, null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='expenses_created',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='expenses_updated',
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='expenses_deleted',
    )

    class Meta:
        db_table = 'expenses'
        ordering = ['-date', '-created_at']
        indexes = [models.Index(fields=['property', 'date'], name='expense_property_date_idx')]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='expense_amount_positive'),
            models.UniqueConstraint(
                fields=['tenant_id', 'idempotency_key'], condition=Q(idempotency_key__isnull=False),
                name='unique_expense_idempotency_key',
            ),
        ]

    def __str__(self):
        return f'{self.amount} on {self.date} ({self.category})'
