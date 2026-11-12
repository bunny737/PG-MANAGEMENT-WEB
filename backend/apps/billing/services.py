"""Invoice generation (PRD Module 9).

Builds an invoice as a *list of line items* (invariant 6): accommodation from
the resident's contracted rent (invariant 2/3 — never the rack rate, unchanged
by a temporary allocation), then the active discount as its own negative line
(invariant 4). Ad-hoc charges (electricity, penalty, ...) are added afterward
as more line items. Management has full manual control while the invoice is a
draft.
"""
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import NotFound, ValidationError

from apps.audit import log as audit_log
from apps.core.idempotency import key_reused
from apps.core.periods import local_today
from apps.core.tasks import enqueue
from apps.notifications.tasks import send_invoice_issued_email_task, send_payment_receipt_email_task
from apps.residents.models import Admission

from .models import Invoice, InvoiceLineItem, Payment, ReceiptCounter


# Default reference text written on the first-invoice automatic advance payment.
# Reversal and reporting check `Payment.is_advance_adjustment` rather than this text.
ADVANCE_PAYMENT_REFERENCE = 'Advance collected at admission'


def active_discount(resident, on_date):
    """The resident's discount active on a date, or None. Module 07 guarantees
    at most one active at a time (non-overlapping windows)."""
    for discount in resident.discounts.all():
        if discount.is_active_on(on_date):
            return discount
    return None


def _accommodation_label(billing_mode, with_food, partial_note):
    base = 'Accommodation + Food' if with_food else 'Accommodation'
    label = f'{base} ({Admission.BillingMode(billing_mode).label})'
    if partial_note:
        label = f'{label} — {partial_note}'
    return label


class InvoiceConflict(ValidationError):
    """The period clashes with one of the resident's existing invoices
    (`duplicate_invoice` / `overlapping_invoice`). A ValidationError, so the
    API answers 400 as before; automatic billing catches it specifically."""


class ResidentNotBillable(ValidationError):
    """Re-checked under the resident lock: the resident left (vacated,
    absconded...) or lost their bed while the request waited. 400, like the
    serializer's own pre-check; bulk generation skips them."""


@transaction.atomic
def generate_invoice(*, resident, period_start, period_end, due_date,
                     billing_mode=None, actor, request=None,
                     base_amount=None, partial_note='', discount_fraction=None,
                     auto_generated=False, review_reasons=(), auto_issue_on=None,
                     due_date_policy=Invoice.DueDatePolicy.FROM_PERIOD_START, on_date=None):
    """Create a draft invoice with its accommodation and discount lines, plus
    any food-holiday credits now due (Module 24).

    Every generation path (single, bulk, automatic) comes through here, and
    the Settings -> Resident locks taken here serialize them, so the overlap
    check below can't race: a resident never has two invoices covering the
    same day. The Settings lock also serializes credit allocation per
    property (see apps.notices.credits); automatic billing already holds it.

    Automatic billing passes `base_amount` (and `discount_fraction` for a
    partial period) explicitly; manual generation leaves them unset and keeps
    the original first-invoice / contracted-rent behaviour."""
    from apps.notices import credits as food_credits
    from apps.residents.services import lock_resident

    from apps.residents.models import Allocation, Resident

    lock_property_settings(resident.property_id, resident.tenant_id)
    # Work from the locked re-read, never the caller's copy: a move-out or
    # abscond that committed while we waited must stop the invoice (and the
    # food-holiday credits it would create after the settlement).
    resident = lock_resident(resident)
    if resident.status not in (Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD):
        raise ResidentNotBillable(
            {'resident': [_('Only active residents can be invoiced.')]}, code='resident_not_billable',
        )
    if not Allocation.objects.filter(resident=resident).exists():
        raise ResidentNotBillable(
            {'resident': [_('This resident is not allocated to a bed.')]}, code='resident_not_allocated',
        )
    admission = resident.admission
    allocation = resident.allocation
    if billing_mode is None:
        billing_mode = admission.billing_mode

    explicit_base = base_amount is not None
    if not explicit_base:
        # First-ever invoice for this resident may use the manual partial-month
        # amount captured at admission; otherwise the current contracted rent.
        is_first = not resident.invoices.exists()
        if is_first and admission.first_month_billing_amount is not None:
            base_amount = admission.first_month_billing_amount
            partial_note = admission.first_month_billing_note
        else:
            base_amount = allocation.contracted_rent
            partial_note = ''

    existing = Invoice.objects.filter(resident=resident)
    if existing.filter(period_start=period_start).exists():
        raise InvoiceConflict(
            {'period_start': [_('This resident already has an invoice for this period.')]},
            code='duplicate_invoice',
        )
    if existing.filter(period_start__lte=period_end, period_end__gte=period_start).exists():
        raise InvoiceConflict(
            {'period_start': [_('This period overlaps another invoice for this resident.')]},
            code='overlapping_invoice',
        )

    try:
        with transaction.atomic():
            invoice = Invoice.objects.create(
                tenant_id=resident.tenant_id, resident=resident,
                period_start=period_start, period_end=period_end,
                billing_mode=billing_mode, due_date=due_date,
                status=Invoice.Status.DRAFT, created_by=actor,
                auto_generated=auto_generated, review_reasons=list(review_reasons),
                auto_issue_on=auto_issue_on, due_date_policy=due_date_policy,
            )
    except IntegrityError:
        # unique_invoice_per_resident_period — a backstop for writers that
        # bypass this service (admin, scripts); the lock above covers the rest.
        raise InvoiceConflict(
            {'period_start': [_('This resident already has an invoice for this period.')]},
            code='duplicate_invoice',
        )

    with_food = admission.food_preference == Admission.FoodPreference.WITH_FOOD
    InvoiceLineItem.objects.create(
        tenant_id=resident.tenant_id, invoice=invoice,
        line_type=InvoiceLineItem.LineType.ACCOMMODATION,
        label=_accommodation_label(billing_mode, with_food, partial_note),
        amount=base_amount, order=0,
    )

    # Discount is applied on the accommodation charged this period (invariant 4:
    # on contracted rent, not rack rate; for a normal month base == contracted).
    discount = active_discount(resident, period_start)
    if explicit_base:
        from .autobilling import partial_discount

        discount_amount = partial_discount(
            discount, base_amount=base_amount, contracted_rent=allocation.contracted_rent,
            fraction=discount_fraction if discount_fraction is not None else Fraction(1),
        )
    else:
        discount_amount = discount.computed_amount(base_amount) if discount is not None else None
    if discount_amount is not None:
        InvoiceLineItem.objects.create(
            tenant_id=resident.tenant_id, invoice=invoice,
            line_type=InvoiceLineItem.LineType.DISCOUNT,
            label=f'{discount.get_reason_display()} discount',
            amount=-discount_amount, order=1,
        )

    # Module 24: food-holiday credits for holidays that have ended. The new
    # draft is just one more candidate for the shared allocation rule.
    on_date = on_date or local_today()
    food_credits.ensure_credits(resident, on_date=on_date, actor=actor, request=request)
    food_credits.allocate_pending(resident, on_date=on_date, actor=actor, request=request)

    after = {'resident': str(resident.id), 'period_start': period_start.isoformat(),
             'total': str(invoice.total)}
    if auto_generated:
        after.update({
            'auto_generated': True, 'review_reasons': list(review_reasons),
            'auto_issue_on': auto_issue_on.isoformat() if auto_issue_on else None,
        })
    audit_log.record(
        action='invoice.generated', actor=actor, tenant_id=resident.tenant_id, obj=invoice,
        after=after, request=request,
    )
    return invoice


# issue_invoice outcomes
ISSUED, FLAGGED, SKIPPED = 'issued', 'flagged', 'skipped'

# A scheduled draft is still auto-issued if the sweep missed one daily run;
# anything older goes to the owner for review instead.
AUTO_ISSUE_GRACE_DAYS = 1


def require_draft(invoice):
    if invoice.status != Invoice.Status.DRAFT:
        raise ValidationError(
            {'detail': _('Only draft invoices can be modified.')}, code='invoice_not_draft'
        )


def lock_property_settings(property_id, tenant_id=None):
    """First lock of every issue / automatic-generation path: Settings ->
    Resident -> Invoice -> Admission (see the Module 08 spec, "Locking").
    Grace days and the automation switch are read under it, so a concurrent
    settings change can't interleave. Creates the row with defaults if the
    property has never had one (settings are lazily created)."""
    from apps.properties.models import Property, PropertySettings

    if tenant_id is None:
        tenant_id = Property.objects.values_list('tenant_id', flat=True).get(pk=property_id)
    PropertySettings.objects.get_or_create(property_id=property_id, defaults={'tenant_id': tenant_id})
    return PropertySettings.objects.select_for_update().get(property_id=property_id)


def _auto_issue_blockers(invoice, *, resident, settings_obj, on_date):
    """Reasons an auto draft due today must go to the owner instead."""
    from apps.residents.models import Allocation, Resident

    reasons = []
    if (on_date - invoice.auto_issue_on).days > AUTO_ISSUE_GRACE_DAYS:
        reasons.append(Invoice.ReviewReason.LATE)
    if not settings_obj.auto_billing_enabled:
        reasons.append(Invoice.ReviewReason.RULE_CHANGED)
    if (resident.status not in (Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD)
            or not Allocation.objects.filter(resident=resident).exists()):
        reasons.append(Invoice.ReviewReason.INELIGIBLE)
    else:
        vacate = resident.open_vacate
        if vacate is not None and vacate.expected_vacate_date < invoice.period_end:
            reasons.append(Invoice.ReviewReason.VACATING)
    return reasons


@transaction.atomic
def issue_invoice(*, invoice_id, actor, on_date=None, auto=False, request=None):
    """Issue a draft: draft -> issued, apply the admission advance to a first
    invoice, notify the resident. Returns ISSUED, or for the sweep (`auto`)
    FLAGGED (needs the owner now — eligibility changed or it's stale) or
    SKIPPED (no longer due: held, issued or edited meanwhile).

    Locks Settings -> Resident -> Invoice -> Admission and re-reads everything
    under them, so it can't race a hold, a second issue, a settings change or
    a notice to vacate."""
    from apps.residents.models import Resident
    from apps.residents.services import lock_resident

    on_date = on_date or local_today()
    ref = Invoice.objects.filter(pk=invoice_id).values('resident_id', 'resident__property_id', 'tenant_id').first()
    if ref is None:
        if auto:
            return SKIPPED
        raise NotFound(_('Invoice not found.'))
    settings_obj = lock_property_settings(ref['resident__property_id'], ref['tenant_id'])
    resident = lock_resident(Resident(pk=ref['resident_id']))
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)

    if auto:
        if (invoice.status != Invoice.Status.DRAFT or invoice.review_reasons or invoice.auto_issue_held
                or invoice.auto_issue_on is None or invoice.auto_issue_on > on_date):
            return SKIPPED
        blockers = _auto_issue_blockers(invoice, resident=resident, settings_obj=settings_obj, on_date=on_date)
        if blockers:
            before = {'review_reasons': list(invoice.review_reasons),
                      'auto_issue_on': invoice.auto_issue_on.isoformat()}
            invoice.review_reasons = list(invoice.review_reasons) + blockers
            invoice.auto_issue_on = None
            if Invoice.ReviewReason.LATE in blockers:
                _due_from_issue_date(invoice)
            invoice.save(update_fields=['review_reasons', 'auto_issue_on', 'due_date_policy', 'updated_at'])
            audit_log.record(
                action='invoice.flagged_for_review', actor=None, tenant_id=invoice.tenant_id, obj=invoice,
                before=before, after={'review_reasons': invoice.review_reasons},
            )
            return FLAGGED
        if on_date > invoice.period_start:
            # Issued after its billing date (one missed sweep): the resident
            # still gets the full grace period from the day they receive it.
            _due_from_issue_date(invoice)
    else:
        require_draft(invoice)

    if invoice.due_date_policy == Invoice.DueDatePolicy.FROM_ISSUE_DATE:
        invoice.due_date = on_date + timedelta(days=settings_obj.penalty_grace_days)
    invoice.status = Invoice.Status.ISSUED
    invoice.issue_date = on_date
    invoice.save(update_fields=['status', 'issue_date', 'due_date', 'due_date_policy', 'updated_at'])
    audit_log.record(
        action='invoice.issued', actor=actor, tenant_id=invoice.tenant_id, obj=invoice,
        after={'status': invoice.status, 'issue_date': invoice.issue_date.isoformat(),
               'due_date': invoice.due_date.isoformat(), 'automatic': auto},
        request=request,
    )
    # The advance (rent paid upfront at admission) settles the first invoice.
    apply_advance_to_first_invoice(invoice=invoice, actor=actor, request=request)
    # Module 14: "Invoice generated notification to resident" (PRD).
    # Issuing (not the draft) is when it becomes a real obligation the
    # resident should be told about — see the Module 14 spec's Decisions.
    invoice_id = str(invoice.id)
    transaction.on_commit(lambda: enqueue(send_invoice_issued_email_task, invoice_id))
    return ISSUED


def _due_from_issue_date(invoice):
    """The draft is (or will be) issued after its billing date: recompute the
    due date from the issue date — unless the owner set it by hand."""
    if invoice.due_date_policy != Invoice.DueDatePolicy.MANUAL:
        invoice.due_date_policy = Invoice.DueDatePolicy.FROM_ISSUE_DATE


def _require_auto_issuable(invoice):
    require_draft(invoice)
    if not invoice.can_auto_issue:
        raise ValidationError(
            {'detail': _('Only automatically generated drafts that need no confirmation can be '
                         'scheduled for automatic issue.')},
            code='not_auto_issuable',
        )


@transaction.atomic
def hold_auto_issue(*, invoice_id, actor, request=None):
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    _require_auto_issuable(invoice)
    if not invoice.auto_issue_held:
        invoice.auto_issue_held = True
        invoice.save(update_fields=['auto_issue_held', 'updated_at'])
        audit_log.record(
            action='invoice.auto_issue_held', actor=actor, tenant_id=invoice.tenant_id, obj=invoice,
            before={'auto_issue_on': invoice.auto_issue_on.isoformat() if invoice.auto_issue_on else None},
            request=request,
        )
    return invoice


@transaction.atomic
def resume_auto_issue(*, invoice_id, actor, on_date=None, request=None):
    """Lift the owner's hold. The draft is issued no earlier than the next
    calendar day's sweep (a calendar-day boundary, not 24 hours); issued after
    its billing date, the due date is recomputed from the issue date."""
    on_date = on_date or local_today()
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    _require_auto_issuable(invoice)
    before = {'auto_issue_held': invoice.auto_issue_held,
              'auto_issue_on': invoice.auto_issue_on.isoformat() if invoice.auto_issue_on else None}
    invoice.auto_issue_held = False
    invoice.auto_issue_on = max(invoice.period_start, on_date + timedelta(days=1))
    if invoice.auto_issue_on > invoice.period_start:
        _due_from_issue_date(invoice)
    invoice.save(update_fields=['auto_issue_held', 'auto_issue_on', 'due_date_policy', 'updated_at'])
    audit_log.record(
        action='invoice.auto_issue_resumed', actor=actor, tenant_id=invoice.tenant_id, obj=invoice,
        before=before, after={'auto_issue_on': invoice.auto_issue_on.isoformat()}, request=request,
    )
    return invoice


def flag_scheduled_drafts(*, property_id, actor, request=None):
    """The property's automatic-billing settings changed: every draft still
    waiting to be auto-issued (held ones included) goes to the owner for
    confirmation instead. Call with the PropertySettings row locked (Settings
    -> Invoice is the lock order)."""
    drafts = list(
        Invoice.objects.select_for_update(of=('self',)).filter(
            resident__property_id=property_id, status=Invoice.Status.DRAFT,
            auto_generated=True, auto_issue_on__isnull=False,
        )
    )
    for invoice in drafts:
        invoice.review_reasons = list(invoice.review_reasons) + [Invoice.ReviewReason.RULE_CHANGED]
        invoice.auto_issue_on = None
        invoice.save(update_fields=['review_reasons', 'auto_issue_on', 'updated_at'])
        audit_log.record(
            action='invoice.flagged_for_review', actor=actor, tenant_id=invoice.tenant_id, obj=invoice,
            after={'review_reasons': invoice.review_reasons}, request=request,
        )
    return len(drafts)


@transaction.atomic
def apply_advance_to_first_invoice(*, invoice, actor, request=None):
    """Apply held admission advance automatically when a resident's first invoice
    is issued (capped at the invoice total). Any surplus stays on the admission's
    `advance_refundable` balance for explicit later adjustment or exit refund.

    Always marks `first_invoice_advance_settled = True` once a resident's first
    invoice is issued so subsequent invoices (or payment deletions) never
    re-trigger automatic application. Lock order: Invoice -> Admission -> ReceiptCounter."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status == Invoice.Status.DRAFT:
        return None
    admission = Admission.objects.select_for_update().get(resident_id=invoice.resident_id)
    if admission.first_invoice_advance_settled:
        return None
    other_issued = (
        Invoice.objects.filter(resident_id=invoice.resident_id).exclude(pk=invoice.pk)
        .exclude(status=Invoice.Status.DRAFT).exists()
    )
    admission.first_invoice_advance_settled = True
    if other_issued or admission.advance_amount <= 0 or admission.advance_applied_amount > 0:
        admission.save(update_fields=['first_invoice_advance_settled', 'updated_at'])
        return None
    amount = min(admission.advance_refundable, invoice.balance_due)
    if amount <= 0:
        admission.save(update_fields=['first_invoice_advance_settled', 'updated_at'])
        return None
    payment_date = admission.advance_collected_date or invoice.issue_date or local_today()
    payment = _create_payment_locked(
        invoice=invoice, amount=amount, payment_date=payment_date,
        payment_mode=admission.advance_mode, is_advance_adjustment=True,
        reference=ADVANCE_PAYMENT_REFERENCE, actor=actor, request=request,
    )
    admission.advance_applied_amount += amount
    admission.save(update_fields=['advance_applied_amount', 'first_invoice_advance_settled', 'updated_at'])
    return payment


def resident_has_invoice_for_period(resident, period_start):
    return resident.invoices.filter(period_start=period_start).exists()


def next_receipt_number(tenant_id):
    """Allocate the tenant's next receipt number under the counter row lock.
    Must run inside the caller's transaction so the number is released with
    it on rollback (a gap is possible only if the payment insert itself fails
    after this, which the caller's atomic block also rolls back)."""
    counter = ReceiptCounter.objects.select_for_update().filter(tenant_id=tenant_id).first()
    if counter is None:
        try:
            with transaction.atomic():
                counter = ReceiptCounter.objects.create(tenant_id=tenant_id)
        except IntegrityError:
            pass  # a concurrent first payment created it — lock that row instead
        counter = ReceiptCounter.objects.select_for_update().get(tenant_id=tenant_id)
    counter.last_number += 1
    counter.save(update_fields=['last_number', 'updated_at'])
    return ReceiptCounter.format(counter.last_number)


def payment_matches(existing, *, invoice_id, amount, payment_date, payment_mode, reference,
                    is_advance_adjustment=False):
    """True when a request carries exactly the inputs `existing` persisted."""
    return (
        str(existing.invoice_id) == str(invoice_id)
        and existing.is_advance_adjustment == is_advance_adjustment
        and existing.amount == amount
        and existing.payment_date == payment_date
        and existing.payment_mode == payment_mode
        and existing.reference == reference
    )


def find_replayed_payment(*, tenant_id, idempotency_key, invoice_id, amount,
                          payment_date, payment_mode, reference, is_advance_adjustment=False):
    """The payment an earlier request with this key created, or None. A key
    reused with any different persisted input is a client bug: 409."""
    existing = Payment.objects.filter(tenant_id=tenant_id, idempotency_key=idempotency_key).first()
    if existing is None:
        return None
    if not payment_matches(
        existing, invoice_id=invoice_id, amount=amount, payment_date=payment_date,
        payment_mode=payment_mode, reference=reference,
        is_advance_adjustment=is_advance_adjustment,
    ):
        raise key_reused()
    return existing


def _create_payment_locked(*, invoice, amount, payment_date, payment_mode, reference='',
                           is_advance_adjustment=False, actor, request=None, idempotency_key=None):
    """Shared payment persistence under an already-held Invoice lock (and
    Resident/Admission locks when adjusting held advance)."""
    if idempotency_key:
        existing = find_replayed_payment(
            tenant_id=invoice.tenant_id, idempotency_key=idempotency_key,
            invoice_id=invoice.pk, amount=amount, payment_date=payment_date,
            payment_mode=payment_mode, reference=reference,
            is_advance_adjustment=is_advance_adjustment,
        )
        if existing is not None:
            existing.replayed = True
            return existing

    if invoice.status == Invoice.Status.DRAFT:
        raise ValidationError(
            {'invoice': _('Payments can only be recorded against an issued invoice.')},
            code='invoice_not_issued',
        )
    balance = invoice.balance_due
    if balance <= 0:
        raise ValidationError(
            {'invoice': _('This invoice is already fully paid.')}, code='invoice_fully_paid',
        )
    if amount > balance:
        raise ValidationError(
            {'amount': _('Payment exceeds the outstanding balance of %(balance)s.')
             % {'balance': balance}},
            code='overpayment',
        )

    try:
        with transaction.atomic():
            payment = Payment.objects.create(
                tenant_id=invoice.tenant_id, invoice=invoice, amount=amount,
                payment_date=payment_date, payment_mode=payment_mode,
                is_advance_adjustment=is_advance_adjustment,
                reference=reference, recorded_by=actor,
                receipt_number=next_receipt_number(invoice.tenant_id),
                idempotency_key=idempotency_key,
            )
    except IntegrityError:
        # unique_payment_idempotency_key: a concurrent request with the same
        # key on a *different* invoice (so it held a different lock) won.
        if not idempotency_key:
            raise
        existing = find_replayed_payment(
            tenant_id=invoice.tenant_id, idempotency_key=idempotency_key,
            invoice_id=invoice.pk, amount=amount, payment_date=payment_date,
            payment_mode=payment_mode, reference=reference,
            is_advance_adjustment=is_advance_adjustment,
        )
        if existing is None:
            raise
        existing.replayed = True
        return existing
    payment.replayed = False
    invoice.recompute_status()
    audit_log.record(
        action='payment.recorded', actor=actor, tenant_id=invoice.tenant_id, obj=payment,
        after={'invoice': str(invoice.id), 'amount': str(amount),
               'mode': payment_mode, 'is_advance_adjustment': is_advance_adjustment,
               'source': payment.payment_source,
               'invoice_status': invoice.status,
               'receipt_number': payment.receipt_number},
        request=request,
    )
    # Module 14: "Payment receipt to resident" (PRD).
    transaction.on_commit(lambda: enqueue(send_payment_receipt_email_task, str(payment.id)))
    return payment


@transaction.atomic
def record_payment(*, invoice, amount, payment_date, payment_mode, reference='',
                   actor, request=None, idempotency_key=None):
    """Record a manual payment (PRD Module 10) and recompute the invoice status
    (issued -> partially_paid -> paid).

    Locks Invoice -> ReceiptCounter."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    return _create_payment_locked(
        invoice=invoice, amount=amount, payment_date=payment_date,
        payment_mode=payment_mode, is_advance_adjustment=False,
        reference=reference, actor=actor, request=request,
        idempotency_key=idempotency_key,
    )


@transaction.atomic
def adjust_from_advance(*, invoice_id, amount, adjustment_date=None, note='',
                        actor, request=None, idempotency_key=None):
    """Explicitly draw down a resident's remaining held advance against an
    issued invoice. Never generates new cash receipts in cash reporting.

    Lock order: PropertySettings -> Resident -> Invoice -> Admission -> ReceiptCounter."""
    from apps.residents.models import Resident
    from apps.residents.services import lock_resident

    ref = Invoice.objects.filter(pk=invoice_id).values(
        'resident_id', 'resident__property_id', 'tenant_id',
    ).first()
    if ref is None:
        raise NotFound(_('Invoice not found.'))

    lock_property_settings(ref['resident__property_id'], ref['tenant_id'])
    resident = lock_resident(Resident(pk=ref['resident_id']))
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    admission = Admission.objects.select_for_update().get(resident_id=resident.pk)

    effective_date = adjustment_date or local_today()
    cleaned_note = (note or '').strip()
    effective_ref = cleaned_note or 'Advance adjustment'

    # Replay check before business-rule guards so retries after full settlement return 200.
    if idempotency_key:
        existing = find_replayed_payment(
            tenant_id=invoice.tenant_id, idempotency_key=idempotency_key,
            invoice_id=invoice.pk, amount=amount, payment_date=effective_date,
            payment_mode=admission.advance_mode, reference=effective_ref,
            is_advance_adjustment=True,
        )
        if existing is not None:
            existing.replayed = True
            return existing

    if resident.status not in (Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD):
        raise ValidationError(
            {'detail': _('Held advance adjustments can only be made for an Active or Notice Period resident.')},
            code='resident_not_current',
        )
    if invoice.status == Invoice.Status.DRAFT:
        raise ValidationError(
            {'invoice': _('Advance can only be adjusted against an issued invoice.')},
            code='invoice_not_issued',
        )
    if not admission.first_invoice_advance_settled:
        raise ValidationError(
            {'detail': _("Issue the resident's first invoice before adjusting held advance on another invoice.")},
            code='first_invoice_not_issued',
        )
    balance = invoice.balance_due
    if balance <= 0:
        raise ValidationError(
            {'invoice': _('This invoice is already fully paid.')}, code='invoice_fully_paid',
        )
    if amount is None or amount <= 0:
        raise ValidationError(
            {'amount': _('Adjustment amount must be greater than zero.')}, code='invalid_amount',
        )
    if amount > balance:
        raise ValidationError(
            {'amount': _('Adjustment exceeds the outstanding balance of %(balance)s.') % {'balance': balance}},
            code='overpayment',
        )
    refundable = admission.advance_refundable
    if amount > refundable:
        raise ValidationError(
            {'amount': _('Adjustment exceeds the remaining held advance of %(advance)s.') % {'advance': refundable}},
            code='exceeds_held_advance',
        )

    payment = _create_payment_locked(
        invoice=invoice, amount=amount, payment_date=effective_date,
        payment_mode=admission.advance_mode, is_advance_adjustment=True,
        reference=effective_ref, actor=actor, request=request,
        idempotency_key=idempotency_key,
    )
    if not payment.replayed:
        before_applied = admission.advance_applied_amount
        admission.advance_applied_amount = before_applied + amount
        admission.save(update_fields=['advance_applied_amount', 'updated_at'])
        audit_log.record(
            action='invoice.advance_adjusted', actor=actor, tenant_id=invoice.tenant_id, obj=invoice,
            before={
                'advance_applied_amount': str(before_applied),
                'advance_refundable': str(admission.advance_amount - before_applied),
            },
            after={
                'payment': str(payment.id),
                'amount': str(amount),
                'advance_applied_amount': str(admission.advance_applied_amount),
                'advance_refundable': str(admission.advance_refundable),
                'invoice_status': invoice.status,
            },
            request=request,
        )
    return payment


@transaction.atomic
def delete_payment(*, payment, actor, request=None):
    """Delete a payment (a correction) and recompute the invoice status back
    down (paid -> partially_paid -> issued).

    When deleting an advance adjustment (`payment.is_advance_adjustment`), locks
    Resident -> Invoice -> Admission, rejects reversal after exit, and restores
    the held balance on Admission."""
    from apps.residents.models import Resident
    from apps.residents.services import lock_resident

    ref = Payment.objects.filter(pk=payment.pk).values(
        'invoice_id', 'invoice__resident_id', 'is_advance_adjustment',
    ).first()
    if ref is None:
        return  # already deleted concurrently

    resident = None
    if ref['is_advance_adjustment']:
        resident = lock_resident(Resident(pk=ref['invoice__resident_id']))

    invoice = Invoice.objects.select_for_update().get(pk=ref['invoice_id'])
    locked_payment = Payment.objects.select_for_update().filter(pk=payment.pk).first()
    if locked_payment is None:
        return  # deleted while waiting for lock

    if locked_payment.is_advance_adjustment:
        if resident.status not in (Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD):
            raise ValidationError(
                {'detail': _('Advance adjustments cannot be reversed after a resident has exited.')},
                code='resident_not_current',
            )
        admission = Admission.objects.select_for_update().get(resident_id=invoice.resident_id)
        if admission.advance_applied_amount < locked_payment.amount:
            raise ValidationError(
                {'detail': _('Cannot restore advance adjustment: held advance applied amount is smaller than the payment.')},
                code='advance_integrity_error',
            )
        admission.advance_applied_amount = admission.advance_applied_amount - locked_payment.amount
        admission.save(update_fields=['advance_applied_amount', 'updated_at'])

    audit_log.record(
        action='payment.deleted', actor=actor, tenant_id=invoice.tenant_id, obj=locked_payment,
        before={'invoice': str(invoice.id), 'amount': str(locked_payment.amount),
                'mode': locked_payment.payment_mode,
                'is_advance_adjustment': locked_payment.is_advance_adjustment,
                'source': locked_payment.payment_source},
        request=request,
    )
    locked_payment.delete()
    invoice.recompute_status()
