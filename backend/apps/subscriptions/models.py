import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Tenant
from apps.core.models import TenantModelMixin


class Plan(models.Model):
    """A pricing tier (PRD §4 'Subscription & Pricing Model'). Platform-level
    catalog, not tenant-scoped (like `PlatformConfig`) — Super Admin manages
    it, tenants only read it. `name` is free text, not a fixed enum: the PRD
    explicitly says plan names/limits/count "will be finalised based on
    market feedback" (invariant 10 — nothing about the plan lineup is
    hardcoded). `max_properties`/`max_residents_per_property` are `null`
    for "Unlimited" (the Enterprise tier)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    max_properties = models.PositiveIntegerField(null=True, blank=True)
    max_residents_per_property = models.PositiveIntegerField(null=True, blank=True)
    price_per_month = models.DecimalField(max_digits=10, decimal_places=2)
    # Which plan's limits apply to a tenant still on trial with no plan
    # selected yet (PRD: "60-Day Free Trial (Starter plan features)"). Super
    # Admin flags exactly one plan as the trial default — not hardcoded to a
    # plan named "Starter".
    is_trial_plan = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)  # retire a plan without deleting it
    razorpay_plan_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'plans'
        ordering = ['price_per_month']

    def __str__(self):
        return self.name


class Subscription(models.Model):
    """One row per tenant (PRD Module 20). Deliberately NOT under
    `TenantModelMixin`/RLS: a `tenant` FK here would collide with the
    mixin's own `tenant_id` RLS column, and — like `User` (see its
    docstring) — this table's access is always mediated through
    `request.user.tenant`/Super Admin, not row-level tenant context. See
    the Module 13 spec's Decisions for the full rationale."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name='subscription')
    plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT, null=True, blank=True, related_name='subscriptions'
    )
    razorpay_subscription_id = models.CharField(max_length=100, blank=True)
    razorpay_customer_id = models.CharField(max_length=100, blank=True)
    current_period_start = models.DateField(null=True, blank=True)
    current_period_end = models.DateField(null=True, blank=True)
    # Start of the payment-failure grace period (PRD: 5 days, configurable
    # via PlatformConfig.payment_grace_days).
    payment_failed_at = models.DateTimeField(null=True, blank=True)
    # Super Admin manual override "for a specific tenant if needed (e.g.
    # grace period, enterprise negotiation)" — null defers to the plan.
    max_properties_override = models.PositiveIntegerField(null=True, blank=True)
    max_residents_override = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subscriptions'

    def __str__(self):
        return f'Subscription: {self.tenant.name}'

    def effective_plan(self):
        """The plan whose limits currently apply. A tenant on trial with no
        plan selected yet borrows the Super-Admin-flagged trial-default
        plan's limits (PRD: trial runs on "Starter plan features")."""
        if self.plan is not None:
            return self.plan
        if self.tenant.status == Tenant.Status.TRIAL:
            return Plan.objects.filter(is_trial_plan=True).first()
        return None

    def effective_max_properties(self):
        if self.max_properties_override is not None:
            return self.max_properties_override
        plan = self.effective_plan()
        return plan.max_properties if plan else None

    def effective_max_residents_per_property(self):
        if self.max_residents_override is not None:
            return self.max_residents_override
        plan = self.effective_plan()
        return plan.max_residents_per_property if plan else None


class SubscriptionPayment(TenantModelMixin):
    """Platform billing history — one row per Razorpay charge attempt (PRD
    Module 20 'Billing history and invoices from platform'). RLS-enforced
    like any other tenant-scoped record; `tenant_id` is stamped from
    `subscription.tenant_id` (Subscription itself isn't RLS-scoped, but the
    UUID is still the right value for this row's own RLS policy)."""

    class Status(models.TextChoices):
        SUCCESS = 'success', _('Success')
        FAILED = 'failed', _('Failed')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name='payments')
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices)
    paid_at = models.DateTimeField(null=True, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'subscription_payments'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_status_display()} payment for {self.subscription.tenant.name}'
