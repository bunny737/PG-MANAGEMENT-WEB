import uuid

from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

SUPPORT_NUMBER_VALIDATOR = RegexValidator(
    r'^[0-9]{8,15}$',
    _('Enter digits only, including the country code (for example 919876543210).'),
)


class TenantQuerySet(models.QuerySet):
    def for_tenant(self, tenant_id):
        return self.filter(tenant_id=tenant_id)


class TenantModelMixin(models.Model):
    """
    Abstract base for every business model in the platform.

    Rules (enforced here and in Module 01 RLS migration):
    - tenant_id must be set on every row
    - every query must call .for_tenant(tenant_id) or equivalent
    - RLS policy at the DB level is added in 01-auth-tenancy migration
      (see docs/modules/01-auth-tenancy.md)

    # TODO (Module 01): add PostgreSQL RLS policies in a post-migrate
    #   RunSQL step after the Tenant model is fully created.
    """
    tenant_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True


class PlatformConfig(models.Model):
    """Singleton row of Super-Admin-configurable platform values (invariant 10).

    Never read the field defaults in business code — always go through
    PlatformConfig.get() so a Super Admin edit takes effect without a deploy.
    Per-plan caps (properties, residents) are added by Module 13 on the Plan model.
    """

    trial_days = models.PositiveIntegerField(default=45)
    payment_grace_days = models.PositiveIntegerField(default=5)
    # Module 14: how many days before trial_ends_at to send each reminder
    # (PRD example: Day 45/55 of a 60-day trial == 15/5 days before expiry).
    # Expressed as an offset from expiry (not an absolute day number) so the
    # reminder schedule keeps working if a Super Admin edits trial_days.
    trial_reminder_first_days_before = models.PositiveIntegerField(default=15)
    trial_reminder_second_days_before = models.PositiveIntegerField(default=5)
    # Below this, a PER_BED_MONTHLY cycle is issued as a ₹0 invoice and never
    # sent to Razorpay at all (invariant 10 — Razorpay's minimum chargeable
    # amount is a platform config value, not a literal in services.py).
    min_billable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    # Property layout (D2): an unpaid invoice whose due date is at most this
    # many days away (or already passed but not yet overdue) shows as "due"
    # rather than "upcoming" on the bed grid.
    payment_due_soon_days = models.PositiveIntegerField(default=7)
    # Platform support contacts shown to every client (GET /support/). Blank =
    # channel not offered. Phone/WhatsApp are digits with country code, no '+'
    # (wa.me form), so 1800 toll-free numbers are allowed too.
    support_email = models.EmailField(blank=True, default='')
    support_phone = models.CharField(max_length=15, blank=True, default='', validators=[SUPPORT_NUMBER_VALIDATOR])
    support_whatsapp = models.CharField(max_length=15, blank=True, default='', validators=[SUPPORT_NUMBER_VALIDATOR])
    support_website = models.URLField(blank=True, default='')
    support_hours = models.CharField(max_length=120, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'platform_config'

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config


class ContactMessage(models.Model):
    """A message sent from the public website's contact form (POST /public/contact/).

    Platform-level and deliberately NOT tenant-scoped (no `tenant_id`, no RLS):
    the sender is an anonymous prospect, not a tenant user — same class as
    `PlatformConfig` / `AppVersionPolicy`. Only a Super Admin reads it, in the
    Django admin (read-only content; the status is the one thing they change).
    Holds personal data (name, email, phone, free text, IP), so it is listed in
    the privacy policy; there is no purge job yet (see module 01 spec, [OPEN]).
    """

    class Status(models.TextChoices):
        NEW = 'new', _('New')
        HANDLED = 'handled', _('Handled')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True, default='')
    message = models.TextField(max_length=2000)
    # Active UI language at submission (Accept-Language), so replies can match it.
    language = models.CharField(max_length=8, blank=True, default='')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW)
    handled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'contact_messages'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', '-created_at'], name='contact_msg_status_idx')]

    def __str__(self):
        return f'{self.name} <{self.email}>'
