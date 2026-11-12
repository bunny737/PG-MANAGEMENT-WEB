"""Shared historical cash-ledger & advance-payment classifier and audit helpers.

Used by both the pre-deployment management command (`audit_historical_cash_ledger`)
and the fail-loud migration (`0011_payment_is_advance_adjustment`). Accepts a
Django app registry (`apps` from either `django.apps.apps` or a migration's
`RunPython`) so it works identically with historical and live model classes.
"""
from collections import defaultdict
from decimal import Decimal

from django.db import connection
from django.db.models import DecimalField, Q, Sum
from django.db.models.functions import Coalesce

from apps.core.tenancy import tenant_context

LEGACY_ADVANCE_REFERENCE = 'Advance collected at admission'
AUDIT_PROXIMITY_SECONDS = 5
ZERO = Decimal('0.00')
MONEY_FIELD = DecimalField(max_digits=12, decimal_places=2)


def _passes_legacy_invariants(payment, admission, issue_logs):
    if admission.advance_amount <= ZERO or admission.advance_applied_amount <= ZERO:
        return False, 'admission_has_no_applied_advance'
    if payment.reference != LEGACY_ADVANCE_REFERENCE:
        return False, 'reference_mismatch'
    if admission.advance_collected_date is None:
        return False, 'missing_advance_collected_date'
    if payment.payment_date != admission.advance_collected_date:
        return False, 'payment_date_mismatch'
    if payment.payment_mode != admission.advance_mode:
        return False, 'payment_mode_mismatch'
    if payment.amount != admission.advance_applied_amount:
        return False, 'amount_mismatch'
    if payment.idempotency_key is not None:
        return False, 'has_idempotency_key'
    if payment.invoice.status == 'draft':
        return False, 'invoice_still_draft'
    if issue_logs:
        within_window = any(
            abs((payment.created_at - log.created_at).total_seconds()) <= AUDIT_PROXIMITY_SECONDS
            for log in issue_logs
        )
        if not within_window:
            return False, 'outside_invoice_issue_audit_window'
    return True, 'ok'


def classify_historical_advance_payments(apps, *, tenant_id=None):
    """Inspect all admissions and candidate legacy advance payments under super-admin RLS.

    Returns a dict:
      - verified_genuine: list of dicts describing uniquely verified rows
      - manual_conflicts: list of dicts for Payment rows with LEGACY_ADVANCE_REFERENCE that failed invariants
      - gate_failures: list of dicts for unresolved/ambiguous/mismatched Admissions (must abort!)
      - to_mark_ids: list of Payment PKs that should have is_advance_adjustment=True set
      - already_reconciled_ids: list of Payment PKs already marked is_advance_adjustment=True
    """
    Admission = apps.get_model('residents', 'Admission')
    Payment = apps.get_model('billing', 'Payment')
    AuditLog = apps.get_model('audit', 'AuditLog')

    with connection.cursor() as cursor:
        payment_columns = {col.name for col in connection.introspection.get_table_description(cursor, Payment._meta.db_table)}
    has_flag_field = (
        any(f.name == 'is_advance_adjustment' for f in Payment._meta.get_fields())
        and 'is_advance_adjustment' in payment_columns
    )

    admission_fields = (
        'id', 'tenant_id', 'resident_id', 'advance_amount',
        'advance_applied_amount', 'advance_collected_date', 'advance_mode', 'created_at',
    )
    payment_fields = [
        'id', 'tenant_id', 'invoice_id', 'amount', 'payment_date', 'payment_mode',
        'reference', 'idempotency_key', 'created_at',
        'invoice__id', 'invoice__status', 'invoice__resident_id',
    ]
    if has_flag_field:
        payment_fields.append('is_advance_adjustment')

    with tenant_context(is_super_admin=True):
        admissions_qs = Admission.objects.only(*admission_fields).order_by('tenant_id', 'created_at', 'id')
        if tenant_id:
            admissions_qs = admissions_qs.filter(tenant_id=tenant_id)
        admissions = list(admissions_qs)

        admissions_by_resident = {adm.resident_id: adm for adm in admissions}
        applied_resident_ids = {adm.resident_id for adm in admissions if adm.advance_applied_amount > ZERO}

        payment_filter = Q(reference=LEGACY_ADVANCE_REFERENCE) | Q(invoice__resident_id__in=applied_resident_ids)
        if has_flag_field:
            payment_filter |= Q(is_advance_adjustment=True)

        payments_qs = (
            Payment.objects.filter(payment_filter)
            .select_related('invoice')
            .only(*payment_fields)
        )
        if tenant_id:
            payments_qs = payments_qs.filter(tenant_id=tenant_id)
        payments = list(payments_qs.order_by('tenant_id', 'created_at', 'id'))

        invoice_ids = [str(p.invoice_id) for p in payments]
        issue_logs_by_invoice = defaultdict(list)
        if invoice_ids:
            logs_qs = AuditLog.objects.filter(action='invoice.issued', object_id__in=invoice_ids)
            if tenant_id:
                logs_qs = logs_qs.filter(tenant_id=tenant_id)
            for log in logs_qs:
                issue_logs_by_invoice[log.object_id].append(log)

    payments_by_resident = defaultdict(list)
    for p in payments:
        payments_by_resident[p.invoice.resident_id].append(p)

    verified_genuine = []
    manual_conflicts = []
    gate_failures = []
    to_mark_ids = []
    already_reconciled_ids = []
    matched_payment_ids = set()

    for admission in admissions:
        if admission.advance_applied_amount <= ZERO:
            continue
        res_payments = payments_by_resident.get(admission.resident_id, [])
        already_flagged = [
            p for p in res_payments if has_flag_field and getattr(p, 'is_advance_adjustment', False)
        ]

        if already_flagged:
            flagged_sum = sum((p.amount for p in already_flagged), ZERO)
            if flagged_sum == admission.advance_applied_amount:
                for p in already_flagged:
                    matched_payment_ids.add(p.id)
                    already_reconciled_ids.append(p.id)
                verified_genuine.append({
                    'outcome': 'VERIFIED_GENUINE',
                    'status': 'already_reconciled',
                    'tenant_id': str(admission.tenant_id),
                    'admission_id': str(admission.id),
                    'resident_id': str(admission.resident_id),
                    'advance_applied_amount': str(admission.advance_applied_amount),
                    'payment_ids': [str(p.id) for p in already_flagged],
                })
            else:
                gate_failures.append({
                    'outcome': 'GATE_FAILURE',
                    'reason': 'FLAGGED_SUM_MISMATCH',
                    'tenant_id': str(admission.tenant_id),
                    'admission_id': str(admission.id),
                    'resident_id': str(admission.resident_id),
                    'advance_applied_amount': str(admission.advance_applied_amount),
                    'flagged_sum': str(flagged_sum),
                    'payment_ids': [str(p.id) for p in already_flagged],
                })
            continue

        matches = []
        rejection_reasons = []
        for p in res_payments:
            ok, reason = _passes_legacy_invariants(p, admission, issue_logs_by_invoice.get(str(p.invoice_id), []))
            if ok:
                matches.append(p)
            elif p.reference == LEGACY_ADVANCE_REFERENCE:
                rejection_reasons.append({'payment_id': str(p.id), 'reason': reason})

        if len(matches) == 1:
            winner = matches[0]
            matched_payment_ids.add(winner.id)
            to_mark_ids.append(winner.id)
            verified_genuine.append({
                'outcome': 'VERIFIED_GENUINE',
                'status': 'needs_backfill',
                'tenant_id': str(admission.tenant_id),
                'admission_id': str(admission.id),
                'resident_id': str(admission.resident_id),
                'advance_applied_amount': str(admission.advance_applied_amount),
                'payment_ids': [str(winner.id)],
            })
        elif len(matches) > 1:
            gate_failures.append({
                'outcome': 'GATE_FAILURE',
                'reason': 'AMBIGUOUS',
                'tenant_id': str(admission.tenant_id),
                'admission_id': str(admission.id),
                'resident_id': str(admission.resident_id),
                'advance_applied_amount': str(admission.advance_applied_amount),
                'payment_ids': [str(p.id) for p in matches],
            })
        else:
            gate_failures.append({
                'outcome': 'GATE_FAILURE',
                'reason': 'UNMATCHED_APPLIED',
                'tenant_id': str(admission.tenant_id),
                'admission_id': str(admission.id),
                'resident_id': str(admission.resident_id),
                'advance_applied_amount': str(admission.advance_applied_amount),
                'candidate_rejections': rejection_reasons,
            })

    # Any remaining un-matched row carrying LEGACY_ADVANCE_REFERENCE is a manual conflict
    # (remains is_advance_adjustment=False).
    for p in payments:
        if p.reference != LEGACY_ADVANCE_REFERENCE:
            continue
        if p.id in matched_payment_ids:
            continue
        if has_flag_field and getattr(p, 'is_advance_adjustment', False):
            continue
        adm = admissions_by_resident.get(p.invoice.resident_id)
        reason = 'admission_missing'
        if adm is not None:
            _, reason = _passes_legacy_invariants(p, adm, issue_logs_by_invoice.get(str(p.invoice_id), []))
            if reason == 'ok':
                reason = 'duplicate_or_unlinked_reference'
        manual_conflicts.append({
            'outcome': 'MANUAL_CONFLICT',
            'tenant_id': str(p.tenant_id),
            'payment_id': str(p.id),
            'invoice_id': str(p.invoice_id),
            'resident_id': str(p.invoice.resident_id),
            'amount': str(p.amount),
            'payment_date': p.payment_date.isoformat(),
            'payment_mode': p.payment_mode,
            'reason': reason,
        })

    return {
        'verified_genuine': verified_genuine,
        'manual_conflicts': manual_conflicts,
        'gate_failures': gate_failures,
        'to_mark_ids': to_mark_ids,
        'already_reconciled_ids': already_reconciled_ids,
    }


def inspect_deposit_and_date_integrity(apps, *, tenant_id=None):
    """Read-only inspection of deposit ledger mismatches and missing advance dates."""
    Admission = apps.get_model('residents', 'Admission')
    AuditLog = apps.get_model('audit', 'AuditLog')

    with tenant_context(is_super_admin=True):
        admissions_qs = (
            Admission.objects.select_related('resident')
            .only(
                'id', 'tenant_id', 'resident_id', 'joining_date',
                'security_deposit_collected_date', 'security_deposit_mode',
                'security_deposit_amount', 'advance_amount', 'advance_collected_date',
                'resident__id', 'resident__first_name', 'resident__last_name',
            )
            .annotate(deposit_sum=Coalesce(Sum('deposit_payments__amount'), ZERO, output_field=MONEY_FIELD))
            .order_by('tenant_id', 'joining_date', 'id')
        )
        if tenant_id:
            admissions_qs = admissions_qs.filter(tenant_id=tenant_id)
        admissions = list(admissions_qs)

        mismatches = []
        missing_advance_dates = []
        audit_target_ids = []

        for adm in admissions:
            if adm.security_deposit_amount != adm.deposit_sum:
                audit_target_ids.extend([str(adm.id), str(adm.resident_id)])
                mismatches.append(adm)
            if adm.advance_amount > ZERO and adm.advance_collected_date is None:
                missing_advance_dates.append({
                    'tenant_id': str(adm.tenant_id),
                    'admission_id': str(adm.id),
                    'resident_id': str(adm.resident_id),
                    'resident_name': f'{adm.resident.first_name} {adm.resident.last_name}'.strip(),
                    'joining_date': adm.joining_date.isoformat(),
                    'advance_amount': str(adm.advance_amount),
                })

        logs_by_object = defaultdict(list)
        if audit_target_ids:
            logs_qs = AuditLog.objects.filter(object_id__in=audit_target_ids).order_by('created_at')
            if tenant_id:
                logs_qs = logs_qs.filter(tenant_id=tenant_id)
            for log in logs_qs:
                logs_by_object[log.object_id].append({
                    'action': log.action,
                    'created_at': log.created_at.isoformat(),
                    'before': log.before,
                    'after': log.after,
                })

    deposit_mismatches = [
        {
            'tenant_id': str(adm.tenant_id),
            'admission_id': str(adm.id),
            'resident_id': str(adm.resident_id),
            'resident_name': f'{adm.resident.first_name} {adm.resident.last_name}'.strip(),
            'joining_date': adm.joining_date.isoformat(),
            'security_deposit_collected_date': (
                adm.security_deposit_collected_date.isoformat() if adm.security_deposit_collected_date else None
            ),
            'security_deposit_mode': adm.security_deposit_mode,
            'security_deposit_amount': str(adm.security_deposit_amount),
            'deposit_payments_sum': str(adm.deposit_sum),
            'difference': str(adm.security_deposit_amount - adm.deposit_sum),
            'audit_logs': logs_by_object[str(adm.id)] + logs_by_object[str(adm.resident_id)],
        }
        for adm in mismatches
    ]

    return {
        'deposit_mismatches': deposit_mismatches,
        'missing_advance_dates': missing_advance_dates,
    }
