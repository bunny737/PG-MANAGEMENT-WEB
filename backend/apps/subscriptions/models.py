import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from django.db.models import F
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Tenant
from apps.core.models import TenantModelMixin

PRICING_LOCKED_MESSAGE = _(
    'Tenants are using this plan. Create a new plan and retire this one to change its pricing.'
)

class Plan(models.Model):
    """A pricing tier (PRD §4 'Subscription & Pricing Model'). Platform-level
    catalog, not tenant-scoped (like `PlatformConfig`) — Super Admin manages
    it, tenants only read it. `name` is free text, not a fixed enum: the PRD
    explicitly says plan names/limits/count "will be finalised based on
    market feedback" (invariant 10 — nothing about the plan lineup is
    hardcoded). `max_properties`/`max_residents_per_property` are `null`
    for "Unlimited" (the Enterprise tier).

    `pricing_type` splits the catalog in two: FLAT_MONTHLY is the original
    fixed tier price billed in advance via Razorpay Subscriptions.
    PER_BED_MONTHLY (Google-Workspace-style: free allowance, then per seat,
    cheaper above a volume threshold) is billed in arrears at cycle close via
    `PlanBedTier` + `pricing.prorated_charge` + Razorpay Invoices — see
    `services.select_plan`/`handle_webhook_event` and the Module 13 spec's
    Decisions for why the two billing mechanisms differ."""

    class PricingType(models.TextChoices):
        FLAT_MONTHLY = 'flat_monthly', _('Flat monthly')
        PER_BED_MONTHLY = 'per_bed_monthly', _('Per bed monthly')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    max_properties = models.PositiveIntegerField(null=True, blank=True)
    max_residents_per_property = models.PositiveIntegerField(null=True, blank=True)
    # Every Bed row under the tenant (provisioned capacity, like per-bed billing).
    max_beds = models.PositiveIntegerField(null=True, blank=True)
    pricing_type = models.CharField(
        max_length=20, choices=PricingType.choices, default=PricingType.FLAT_MONTHLY
    )
    # Meaningless for PER_BED_MONTHLY (see PlanBedTier for that pricing).
    price_per_month = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
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
        ordering = [F('price_per_month').asc(nulls_last=True), 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['is_trial_plan'], condition=models.Q(is_trial_plan=True), name='single_trial_plan',
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Flagging a plan as the trial default moves the flag here, so there is
        # never more than one (the single_trial_plan constraint is the backstop).
        with transaction.atomic():
            if self.is_trial_plan:
                Plan.objects.filter(is_trial_plan=True).exclude(pk=self.pk).update(is_trial_plan=False)
            super().save(*args, **kwargs)

    def validate_constraints(self, exclude=None):
        # save() resolves trial-flag conflicts, so forms must not reject them first.
        super().validate_constraints(exclude={*(exclude or ()), 'is_trial_plan'})

    def is_locked(self):
        """Live plans: Razorpay holds the price, or tenants are billed on it."""
        if self._state.adding:
            return False
        return bool(self.razorpay_plan_id) or self.subscriptions.exists()

    def is_deletable(self):
        return not self.is_trial_plan and not self.is_locked()

    def validate_protected_changes(self):
        """Pricing of a live plan is frozen (Razorpay can't reprice a plan), and
        the trial default can only be handed over, never cleared."""
        def error(field, message, code):
            return DjangoValidationError({field: DjangoValidationError(message, code=code)})

        if self.is_trial_plan and not self.is_active:
            raise error('is_active', _(
                'The trial plan must stay active. Mark another plan as the trial plan first.'
            ), 'trial_plan_required')
        if self._state.adding:
            return
        stored = Plan.objects.filter(pk=self.pk).first()
        if stored is None:
            return
        if stored.is_trial_plan and not self.is_trial_plan:
            raise error('is_trial_plan', _(
                'A trial plan is required. Mark another plan as the trial plan first.'
            ), 'trial_plan_required')
        pricing_changed = (
            stored.price_per_month != self.price_per_month or stored.pricing_type != self.pricing_type
        )
        if pricing_changed and stored.is_locked():
            raise error('price_per_month', PRICING_LOCKED_MESSAGE, 'plan_pricing_locked')

    def validate_pricing_invariants(self):
        """Cross-field rules between the pricing scheme and the caps. Shared by
        `clean()` (admin) and the plan API, which never calls `clean()`."""
        def error(field, message, code):
            return DjangoValidationError({field: DjangoValidationError(message, code=code)})

        if self.pricing_type == self.PricingType.FLAT_MONTHLY:
            if self.price_per_month is None:
                raise error(
                    'price_per_month', _('Flat-monthly plans require a price_per_month.'),
                    'plan_price_required',
                )
            # Bed tiers only make sense for PER_BED_MONTHLY; guarding here (not just
            # on PlanBedTier) means a plan can never carry the two pricing schemes
            # at once. Skipped when unsaved — bed_tiers needs a pk to query.
            if self.pk and self.bed_tiers.exists():
                raise error(
                    'pricing_type', _('Flat-monthly plans cannot have bed tiers.'),
                    'plan_flat_has_tiers',
                )
        elif self.pricing_type == self.PricingType.PER_BED_MONTHLY:
            # Google-style seat billing has no cap — you pay for what you provision.
            if (
                self.max_properties is not None or self.max_residents_per_property is not None
                or self.max_beds is not None
            ):
                raise DjangoValidationError(
                    _('Per-bed plans cannot also cap properties, residents or beds — '
                      'billing is already usage-based.'),
                    code='plan_per_bed_capped',
                )
            if self.pk:
                tiers = self.bed_tiers.all()
                if not tiers.exists():
                    raise error(
                        'pricing_type', _('Per-bed plans require at least one bed tier.'),
                        'plan_bed_tiers_required',
                    )
                if tiers.filter(up_to_beds__isnull=True).count() != 1:
                    raise error(
                        'pricing_type',
                        _('Per-bed plans must have exactly one open-ended tier (up_to_beds=None).'),
                        'plan_bed_tier_open_ended',
                    )

    def clean(self):
        self.validate_protected_changes()
        self.validate_pricing_invariants()


class PlanBedTier(models.Model):
    """One marginal-rate step of a PER_BED_MONTHLY plan's pricing ladder.

    A free allowance and a volume discount are the same mechanism — an
    ordered list of `(up_to_beds, rate_per_bed)` steps applied marginally
    (see `pricing.monthly_charge`), not four separate fields for two
    competing discount modes. Example ladder: 50 beds @ ₹0 (free
    allowance), 300 beds @ ₹2, unlimited @ ₹1.50 (volume break). This also
    satisfies invariant 6 — the engine iterates a list, so a Super Admin
    changing the ladder needs zero code changes.

    `up_to_beds=None` marks the open-ended top tier; exactly one tier per
    plan must be open-ended (enforced in `Plan.clean`/`full_clean` via the
    admin form — see the Module 13 spec's Decisions)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='bed_tiers')
    up_to_beds = models.PositiveIntegerField(null=True, blank=True)
    rate_per_bed = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = 'plan_bed_tiers'
        ordering = [F('up_to_beds').asc(nulls_last=True)]
        constraints = [
            models.UniqueConstraint(fields=['plan', 'up_to_beds'], name='unique_bed_tier_ceiling_per_plan'),
        ]

    def __str__(self):
        ceiling = self.up_to_beds if self.up_to_beds is not None else '∞'
        return f'{self.plan.name}: up to {ceiling} beds @ ₹{self.rate_per_bed}'

    def clean(self):
        if self.plan_id and self.plan.pricing_type == Plan.PricingType.FLAT_MONTHLY:
            raise DjangoValidationError(_('Flat-monthly plans cannot have bed tiers.'))
        if self.plan_id and self.plan.is_locked():
            raise DjangoValidationError(PRICING_LOCKED_MESSAGE, code='plan_pricing_locked')


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
    # A flat plan the tenant has chosen but not yet paid for. `plan`, its limits and
    # `razorpay_subscription_id` stay as they were until Razorpay's webhook confirms
    # the first charge on `pending_razorpay_subscription_id`, which promotes these
    # (and cancels the old Razorpay subscription). Both are blank/null together.
    pending_plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT, null=True, blank=True, related_name='pending_subscriptions'
    )
    pending_razorpay_subscription_id = models.CharField(max_length=100, blank=True)
    razorpay_customer_id = models.CharField(max_length=100, blank=True)
    current_period_start = models.DateField(null=True, blank=True)
    current_period_end = models.DateField(null=True, blank=True)
    # Start of the payment-failure grace period (PRD: 5 days, configurable
    # via PlatformConfig.payment_grace_days).
    payment_failed_at = models.DateTimeField(null=True, blank=True)
    # Set when a Super Admin suspends or cancels the tenant by hand; no webhook may then change
    # the tenant's status (webhook_policy). Cleared only by an explicit reactivation.
    STATUS_HOLD_MANUAL = 'manual'
    status_hold = models.CharField(max_length=10, blank=True, default='')
    # Super Admin manual override "for a specific tenant if needed (e.g.
    # grace period, enterprise negotiation)" — null defers to the plan.
    max_properties_override = models.PositiveIntegerField(null=True, blank=True)
    max_residents_override = models.PositiveIntegerField(null=True, blank=True)
    max_beds_override = models.PositiveIntegerField(null=True, blank=True)
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

    def max_beds_on(self, plan):
        if self.max_beds_override is not None:
            return self.max_beds_override
        return plan.max_beds if plan else None

    def effective_max_beds(self):
        return self.max_beds_on(self.effective_plan())


class RazorpaySubscription(models.Model):
    """Every Razorpay subscription ever created for a tenant, kept until it reaches a
    terminal state. `Subscription.razorpay_subscription_id` / `pending_*` only say
    which one is current or newest; this table is what makes plan changes
    reconcilable. Webhooks arrive late and out of order, and cancelling can fail, so
    a subscription we have moved on from must still be recognised when a payment (or
    a cancellation) for it turns up, and must keep being cancelled until Razorpay
    confirms. Not under RLS, like Subscription: the webhook that reads it is
    unauthenticated.

    PENDING   chosen, awaiting its first payment (the newest one is shown to the tenant).
    CURRENT   paid; the tenant's live subscription.
    REPLACED  was CURRENT, superseded by a newly paid plan. Must be cancelled; a charge
              on it (a renewal that raced the cancel) is recorded and flagged for refund.
    ABANDONED was PENDING, superseded by a later choice. Must be cancelled, but a payment
              that still lands on it is honoured: the tenant paid for that plan.
    CANCELLING a worker has claimed it and may already have cancelled it at Razorpay (which
              cannot be undone: a cancelled subscription never restarts). Webhooks therefore
              must not promote it; a charge that lands now is recorded and flagged for refund.
              `cancel_from` remembers REPLACED/ABANDONED so a failed attempt can revert.
    CANCELLED terminal: Razorpay confirmed it is cancelled (or finished)."""

    class State(models.TextChoices):
        PENDING = 'pending', _('Pending')
        CURRENT = 'current', _('Current')
        REPLACED = 'replaced', _('Replaced')
        ABANDONED = 'abandoned', _('Abandoned')
        CANCELLING = 'cancelling', _('Cancelling')
        CANCELLED = 'cancelled', _('Cancelled')

    NEEDS_CANCEL = (State.REPLACED, State.ABANDONED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='razorpay_subscriptions')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='razorpay_subscriptions')
    razorpay_subscription_id = models.CharField(max_length=100, unique=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    # The state to return to if a cancellation attempt fails (REPLACED or ABANDONED).
    cancel_from = models.CharField(max_length=10, blank=True)
    cancel_attempts = models.PositiveIntegerField(default=0)
    last_cancel_error = models.TextField(blank=True)
    last_cancel_attempt_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    # The last webhook that moved (or deliberately kept) this subscription's status, by the event's own
    # occurrence time (top-level `created_at`), not by delivery order — see webhook_policy.
    last_status_event_at = models.DateTimeField(null=True, blank=True)
    last_status_event_type = models.CharField(max_length=40, blank=True)
    last_status_event_id = models.CharField(max_length=100, blank=True)
    # Set by the first activation/charge; `subscription.activated` only ever does the initial activation.
    activated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'razorpay_subscriptions'
        indexes = [models.Index(fields=['state'], name='razorpay_sub_state_idx')]

    def __str__(self):
        return f'{self.razorpay_subscription_id} ({self.state})'


class RazorpayWebhookEvent(models.Model):
    """Every valid Razorpay webhook we receive, kept even when it is stale or changes nothing — the
    audit trail for out-of-order and conflicting deliveries. `event_id` is Razorpay's
    `X-Razorpay-Event-Id` (the same across retries, so it also de-duplicates redeliveries); without that
    header it is a hash of the body. `occurred_at` is the payload's top-level `created_at`, which is what
    orders events — `received_at` is when we saw it. Not under RLS, like the ledger: the receiver is
    unauthenticated. The payload holds the customer's contact details, so rows are personal data (see the
    Module 13 spec for retention)."""

    class Outcome(models.TextChoices):
        PENDING = 'pending', _('Pending')
        APPLIED = 'applied', _('Applied')
        STALE_IGNORED = 'stale_ignored', _('Stale, ignored')
        TERMINAL_IGNORED = 'terminal_ignored', _('Subscription finished, ignored')
        MANUAL_HOLD_IGNORED = 'manual_hold_ignored', _('Manual suspension/cancellation, ignored')
        NOT_RECOVERY_IGNORED = 'not_recovery_ignored', _('Not a recovery event, ignored')
        NEEDS_VERIFICATION = 'needs_verification', _('Needs verification with Razorpay')
        VERIFICATION_DECLINED = 'verification_declined', _('Razorpay did not confirm, ignored')
        NON_CURRENT = 'non_current', _('Not the live subscription')
        UNHANDLED = 'unhandled', _('Unhandled event type')
        UNKNOWN_SUBSCRIPTION = 'unknown_subscription', _('Unknown subscription')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_id = models.CharField(max_length=100, unique=True)
    event_type = models.CharField(max_length=60)
    razorpay_subscription_id = models.CharField(max_length=100, blank=True, db_index=True)
    tenant_id = models.UUIDField(null=True, blank=True)
    occurred_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    outcome = models.CharField(max_length=30, choices=Outcome.choices, default=Outcome.PENDING)
    detail = models.TextField(blank=True)
    payload = models.JSONField()

    class Meta:
        db_table = 'razorpay_webhook_events'
        ordering = ['-received_at']

    def __str__(self):
        return f'{self.event_type} {self.event_id} ({self.outcome})'


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
        constraints = [
            # Idempotency backstop: a replayed / concurrently-delivered Razorpay
            # webhook must never double-record the same charge. The exists()
            # guard in services.handle_webhook_event races without this.
            models.UniqueConstraint(
                fields=['razorpay_payment_id'],
                condition=~models.Q(razorpay_payment_id=''),
                name='unique_razorpay_payment_id',
            ),
        ]

    def __str__(self):
        return f'{self.get_status_display()} payment for {self.subscription.tenant.name}'


class BedLedgerEntry(TenantModelMixin):
    """Append-only record of every bed add/remove (PER_BED_MONTHLY billing
    prerequisite). `Bed.delete()` is a hard delete
    (`apps.properties.models.Bed`) with no soft-delete anywhere in that app,
    so bed-days cannot be reconstructed from the live `beds` table once a bed
    is gone. Written by `subscriptions.signals` on `Bed` post_save/post_delete
    — not `properties/models.py` — to keep Module 02 untouched (a soft-delete
    column would have blocked re-using a bed number under the
    `unique_bed_number_per_room` constraint).

    Rows are never updated or deleted (invariant 9, applied to the bed
    dimension). `bed_id` is a plain UUID, not an FK, since the row it once
    pointed at may no longer exist. `pricing.bed_segments` replays this into
    the `(from, to, count)` segments `pricing.prorated_charge` consumes."""

    class Event(models.TextChoices):
        ADDED = 'added', _('Added')
        REMOVED = 'removed', _('Removed')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bed_id = models.UUIDField()
    event = models.CharField(max_length=10, choices=Event.choices)
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = 'bed_ledger_entries'
        ordering = ['occurred_at']
        indexes = [models.Index(fields=['tenant_id', 'occurred_at'])]

    def __str__(self):
        return f'{self.get_event_display()} bed {self.bed_id} at {self.occurred_at}'


class SubscriptionInvoice(TenantModelMixin):
    """One platform invoice per billing cycle (PRD Module 20 'Billing
    history and invoices from platform', previously `[OPEN]`/deferred to
    Module 17 — now required by arrears billing). Per invariant 6 the
    invoice is a list of line items (`SubscriptionInvoiceLine`), never fixed
    fields, so future add-ons drop in with zero schema change.

    Unique on `(subscription, period_start)` so
    `generate_subscription_invoices` is idempotent under a re-run."""

    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        ISSUED = 'issued', _('Issued')
        PAID = 'paid', _('Paid')
        FAILED = 'failed', _('Failed')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name='invoices')
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    billed_bed_count_start = models.PositiveIntegerField()
    billed_bed_count_end = models.PositiveIntegerField()
    razorpay_invoice_id = models.CharField(max_length=100, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    # A priced invoice is saved as DRAFT and issued to Razorpay only after the
    # transaction that created it commits (`services.issue_invoice`), retried by
    # a periodic sweep. `issue_claimed_at` is the lease that stops two workers
    # issuing it at once; the rest records failed attempts.
    issue_claimed_at = models.DateTimeField(null=True, blank=True)
    issue_attempts = models.PositiveIntegerField(default=0)
    last_issue_error = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'subscription_invoices'
        ordering = ['-period_start']
        constraints = [
            models.UniqueConstraint(fields=['subscription', 'period_start'], name='unique_invoice_per_cycle'),
        ]

    def __str__(self):
        return f'Invoice {self.period_start}–{self.period_end} for {self.subscription.tenant.name}'


class SubscriptionInvoiceLine(TenantModelMixin):
    """A single billed component of a `SubscriptionInvoice` — one line per
    tier crossed in the cycle, plus separate lines for mid-cycle bed
    additions, so an owner can see exactly why the total changed (invariant
    6: the engine iterates a list, nothing is hardcoded to 'base + discount')."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(SubscriptionInvoice, on_delete=models.CASCADE, related_name='lines')
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    unit_rate = models.DecimalField(max_digits=12, decimal_places=4)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # Reserved for future non-bed add-ons (diet food, gym) — empty in MVP, per invariant 6.
    addons = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = 'subscription_invoice_lines'

    def __str__(self):
        return f'{self.description}: {self.amount}'
