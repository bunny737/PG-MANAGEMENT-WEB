import builtins
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModelMixin
from apps.properties.models import Property

# Upper bound on a per-day food rate (holiday rate and the property default).
# rate × a 366-day holiday then always fits decimal(12,2). A sanity bound on
# the field, not a plan limit.
MAX_RATE_PER_DAY = Decimal('999999.99')
# Longest holiday accepted (one calendar year, leap day included).
MAX_HOLIDAY_DAYS = 366
# Largest value a decimal(12,2) column holds.
MAX_AMOUNT = Decimal('9999999999.99')


class Announcement(TenantModelMixin):
    """A notice the owner posts for a property's residents (Module 24). Named
    Announcement in code so it can't be confused with the resident notice
    period (Module 10) or AutoBillingNotice (Module 08); the UI says "Notices".

    A notice created for a food holiday keeps `is_auto_text` while its text is
    still the generated one, and `generated_from` records the holiday values
    the text is known to match. `generated_from` holds the rate, so it is never
    serialized; only the derived `notice_outdated` flag is."""

    class Category(models.TextChoices):
        GENERAL = 'general', _('General')
        HOLIDAY = 'holiday', _('Holiday')
        MAINTENANCE = 'maintenance', _('Maintenance')
        RULES = 'rules', _('Rules')
        EVENT = 'event', _('Event')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='announcements')
    title = models.CharField(max_length=200)
    body = models.TextField()
    category = models.CharField(max_length=15, choices=Category.choices, default=Category.GENERAL)
    is_pinned = models.BooleanField(default=False)
    expires_on = models.DateField(null=True, blank=True)
    is_auto_text = models.BooleanField(default=False)
    generated_from = models.JSONField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='announcements_created',
    )

    class Meta:
        db_table = 'announcements'
        ordering = ['-is_pinned', '-created_at']
        indexes = [models.Index(fields=['property', 'created_at'], name='announcement_property_idx')]

    def __str__(self):
        return self.title


class FoodHoliday(TenantModelMixin):
    """Days a property serves no food (Module 24) — e.g. Dasara. With
    `adjust_in_bill`, each with-food resident is credited `rate_per_day` for
    every holiday day they stayed (see apps.notices.credits)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name='food_holidays')
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()  # inclusive
    adjust_in_bill = models.BooleanField(default=False)
    rate_per_day = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    announcement = models.OneToOneField(
        Announcement, null=True, blank=True, on_delete=models.SET_NULL, related_name='food_holiday',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='food_holidays_created',
    )

    class Meta:
        db_table = 'food_holidays'
        ordering = ['-start_date']
        indexes = [models.Index(fields=['property', 'start_date'], name='food_holiday_property_idx')]
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gte=F('start_date')), name='food_holiday_dates_ordered'),
            models.CheckConstraint(
                condition=Q(rate_per_day__isnull=True)
                | Q(rate_per_day__gte=0, rate_per_day__lte=MAX_RATE_PER_DAY),
                name='food_holiday_rate_in_range',
            ),
            models.CheckConstraint(
                condition=Q(adjust_in_bill=False) | Q(rate_per_day__isnull=False),
                name='food_holiday_adjust_needs_rate',
            ),
        ]

    def __str__(self):
        return f'{self.name} ({self.start_date} – {self.end_date})'

    # NB: `property` is shadowed by the ForeignKey above, hence builtins.property.
    @builtins.property
    def total_days(self):
        return (self.end_date - self.start_date).days + 1

    def snapshot(self):
        """The holiday values an auto-generated notice is built from."""
        return {
            'name': self.name,
            'start': self.start_date.isoformat(),
            'end': self.end_date.isoformat(),
            'adjust': self.adjust_in_bill,
            'rate': None if self.rate_per_day is None else str(self.rate_per_day),
        }


class FoodHolidayCredit(TenantModelMixin):
    """What one resident is owed for one food holiday. Every change goes
    through apps.notices.credits; the PROTECT foreign keys make any path that
    bypasses it (admin, a cascade) fail instead of orphaning a credit.

    pending  — owed, not on any invoice yet
    invoiced — a negative `food_holiday` line on a draft or issued invoice
    settled  — paid out through a move-out refund or netted on abscond
    waived   — the owner removed it for this resident (kept as a tombstone)

    An invoiced credit can also carry a clawback: the resident left before the
    holiday they were already credited for ended (owner decision 2026-10-30)."""

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        INVOICED = 'invoiced', _('On an invoice')
        SETTLED = 'settled', _('Settled at exit')
        WAIVED = 'waived', _('Waived')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    holiday = models.ForeignKey(FoodHoliday, on_delete=models.PROTECT, related_name='credits')
    resident = models.ForeignKey(
        'residents.Resident', on_delete=models.PROTECT, related_name='food_holiday_credits',
    )
    days = models.PositiveSmallIntegerField()
    rate = models.DecimalField(max_digits=12, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    line_item = models.OneToOneField(
        'billing.InvoiceLineItem', null=True, blank=True, on_delete=models.PROTECT,
        related_name='food_holiday_credit',
    )
    vacate = models.ForeignKey(
        'residents.Vacate', null=True, blank=True, on_delete=models.PROTECT, related_name='food_holiday_credits',
    )
    absconded_record = models.ForeignKey(
        'residents.AbscondedRecord', null=True, blank=True, on_delete=models.PROTECT,
        related_name='food_holiday_credits',
    )
    clawback_days = models.PositiveSmallIntegerField(default=0)
    clawback_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        db_table = 'food_holiday_credits'
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(fields=['holiday', 'resident'], name='unique_food_holiday_credit'),
            models.CheckConstraint(
                condition=Q(amount=F('rate') * F('days')), name='food_holiday_credit_amount_exact',
            ),
            models.CheckConstraint(
                condition=Q(clawback_days__lte=F('days'), clawback_amount=F('rate') * F('clawback_days')),
                name='food_holiday_credit_clawback_exact',
            ),
            models.CheckConstraint(
                condition=(
                    Q(status__in=['pending', 'waived'], line_item__isnull=True, vacate__isnull=True,
                      absconded_record__isnull=True, clawback_days=0)
                    | Q(status='invoiced', line_item__isnull=False, clawback_days=0,
                        vacate__isnull=True, absconded_record__isnull=True)
                    | Q(status='invoiced', line_item__isnull=False, clawback_days__gt=0)
                    & (Q(vacate__isnull=False, absconded_record__isnull=True)
                       | Q(vacate__isnull=True, absconded_record__isnull=False))
                    | Q(status='settled', line_item__isnull=True, clawback_days=0)
                    & (Q(vacate__isnull=False, absconded_record__isnull=True)
                       | Q(vacate__isnull=True, absconded_record__isnull=False))
                ),
                name='food_holiday_credit_status_refs',
            ),
        ]

    def __str__(self):
        return f'{self.holiday.name}: {self.amount} for {self.resident}'
