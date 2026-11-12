"""Tests for the historical cash-ledger audit command, fail-loud advance backfill
migration (billing.0011), residents.0013 backfill, and DB check constraints."""
import importlib
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction

from apps.audit.models import AuditLog
from apps.billing.historical_audit import (
    LEGACY_ADVANCE_REFERENCE,
    classify_historical_advance_payments,
    inspect_deposit_and_date_integrity,
)
from apps.billing.models import Invoice, Payment
from apps.core.tenancy import tenant_context
from apps.residents.models import Admission, DepositPayment, Resident

from .base import BillingAPITestCase

mig_0011 = importlib.import_module('apps.billing.migrations.0011_payment_is_advance_adjustment')
mig_0013 = importlib.import_module('apps.residents.migrations.0013_admission_advance_guards')


class HistoricalAdvanceAuditAndBackfillTests(BillingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.prop = self.create_property(self.tenant)
        self.floor = self.create_floor(self.prop)
        self.room_idx = 0

    def _admit_with_advance(
        self,
        *,
        phone='9000000010',
        advance_amount='14000.00',
        advance_applied='7000.00',
        advance_collected_date=date(2026, 7, 1),
        advance_mode='upi',
        deposit_amount='0.00',
        deposit_collected_date=None,
        deposit_mode='',
    ):
        self.room_idx += 1
        room = self.create_room(self.floor, room_number=str(100 + self.room_idx))
        bed = self.create_bed(room, bed_number=f'{100 + self.room_idx}-A')
        resident = self.create_resident(self.prop, phone=phone, status=Resident.Status.RESERVED)
        self.check_in(
            resident, bed,
            joining_date=date(2026, 7, 1),
            advance_amount=Decimal(advance_amount),
            advance_applied_amount=Decimal(advance_applied),
            advance_collected_date=advance_collected_date,
            advance_mode=advance_mode,
            security_deposit_amount=Decimal(deposit_amount),
            security_deposit_agreed=Decimal(deposit_amount),
            security_deposit_collected_date=deposit_collected_date,
            security_deposit_mode=deposit_mode,
        )
        with tenant_context(self.tenant.id):
            return resident, resident.admission

    def test_verified_genuine_backfill_is_classified_and_idempotent(self):
        resident, admission = self._admit_with_advance(advance_amount='14000.00', advance_applied='7000.00')
        invoice = self.create_invoice(resident, date(2026, 7, 1))
        payment = self.create_payment(
            invoice, amount=Decimal('7000.00'), payment_date=date(2026, 7, 1),
            payment_mode='upi', reference=LEGACY_ADVANCE_REFERENCE, is_advance_adjustment=False,
        )
        with tenant_context(self.tenant.id):
            AuditLog.objects.create(
                tenant_id=self.tenant.id, actor=self.owner,
                action='invoice.issued', object_type='Invoice', object_id=str(invoice.id),
            )

        out = StringIO()
        call_command('audit_historical_cash_ledger', tenant=str(self.tenant.id), stdout=out)
        self.assertIn('Verified genuine: 1, Manual conflicts (stay non-adjustment): 0, Gate failures: 0', out.getvalue())

        report = classify_historical_advance_payments(apps, tenant_id=self.tenant.id)
        self.assertEqual(report['to_mark_ids'], [payment.id])
        self.assertEqual(report['gate_failures'], [])
        self.assertEqual(report['manual_conflicts'], [])

        mig_0011.backfill_advance_adjustments(apps, None)
        with tenant_context(self.tenant.id):
            payment.refresh_from_db()
            self.assertTrue(payment.is_advance_adjustment)

        # Running migration backfill a second time succeeds cleanly (already_reconciled).
        mig_0011.backfill_advance_adjustments(apps, None)
        report_after = classify_historical_advance_payments(apps, tenant_id=self.tenant.id)
        self.assertEqual(report_after['to_mark_ids'], [])
        self.assertEqual(report_after['already_reconciled_ids'], [payment.id])

    def test_manual_payments_failing_invariants_remain_non_adjustments(self):
        resident, _ = self._admit_with_advance(advance_amount='14000.00', advance_applied='7000.00')
        invoice = self.create_invoice(resident, date(2026, 7, 1), total=Decimal('25000.00'))
        genuine = self.create_payment(
            invoice, amount=Decimal('7000.00'), payment_date=date(2026, 7, 1),
            payment_mode='upi', reference=LEGACY_ADVANCE_REFERENCE, is_advance_adjustment=False,
        )
        wrong_date = self.create_payment(
            invoice, amount=Decimal('7000.00'), payment_date=date(2026, 7, 2),
            payment_mode='upi', reference=LEGACY_ADVANCE_REFERENCE, is_advance_adjustment=False,
        )
        wrong_mode = self.create_payment(
            invoice, amount=Decimal('7000.00'), payment_date=date(2026, 7, 1),
            payment_mode='cash', reference=LEGACY_ADVANCE_REFERENCE, is_advance_adjustment=False,
        )
        with_key = self.create_payment(
            invoice, amount=Decimal('7000.00'), payment_date=date(2026, 7, 1),
            payment_mode='upi', reference=LEGACY_ADVANCE_REFERENCE, is_advance_adjustment=False,
            idempotency_key='manual-key-1',
        )
        late_payment = self.create_payment(
            invoice, amount=Decimal('7000.00'), payment_date=date(2026, 7, 1),
            payment_mode='upi', reference=LEGACY_ADVANCE_REFERENCE, is_advance_adjustment=False,
        )
        with tenant_context(self.tenant.id):
            log = AuditLog.objects.create(
                tenant_id=self.tenant.id, actor=self.owner,
                action='invoice.issued', object_type='Invoice', object_id=str(invoice.id),
            )
            Payment.objects.filter(pk=late_payment.pk).update(
                created_at=log.created_at + timedelta(seconds=30),
            )

        report = classify_historical_advance_payments(apps, tenant_id=self.tenant.id)
        self.assertEqual(report['gate_failures'], [])
        self.assertEqual(report['to_mark_ids'], [genuine.id])
        conflict_reasons = {c['payment_id']: c['reason'] for c in report['manual_conflicts']}
        self.assertEqual(conflict_reasons[str(wrong_date.id)], 'payment_date_mismatch')
        self.assertEqual(conflict_reasons[str(wrong_mode.id)], 'payment_mode_mismatch')
        self.assertEqual(conflict_reasons[str(with_key.id)], 'has_idempotency_key')
        self.assertEqual(conflict_reasons[str(late_payment.id)], 'outside_invoice_issue_audit_window')

        mig_0011.backfill_advance_adjustments(apps, None)
        with tenant_context(self.tenant.id):
            self.assertTrue(Payment.objects.get(pk=genuine.pk).is_advance_adjustment)
            for pid in (wrong_date.pk, wrong_mode.pk, with_key.pk, late_payment.pk):
                self.assertFalse(Payment.objects.get(pk=pid).is_advance_adjustment)

    def test_unmatched_and_ambiguous_fail_command_and_abort_migration(self):
        # Case 1: advance_applied_amount > 0 with no matching legacy payment -> UNMATCHED_APPLIED
        resident, _ = self._admit_with_advance(advance_amount='7000.00', advance_applied='7000.00')
        with self.assertRaises(CommandError):
            call_command('audit_historical_cash_ledger', tenant=str(self.tenant.id), stdout=StringIO())
        with self.assertRaises(RuntimeError):
            mig_0011.backfill_advance_adjustments(apps, None)

        # Case 2: two identical legacy payments matching invariants -> AMBIGUOUS
        invoice = self.create_invoice(resident, date(2026, 7, 1), total=Decimal('20000.00'))
        self.create_payment(
            invoice, amount=Decimal('7000.00'), payment_date=date(2026, 7, 1),
            payment_mode='upi', reference=LEGACY_ADVANCE_REFERENCE, is_advance_adjustment=False,
        )
        self.create_payment(
            invoice, amount=Decimal('7000.00'), payment_date=date(2026, 7, 1),
            payment_mode='upi', reference=LEGACY_ADVANCE_REFERENCE, is_advance_adjustment=False,
        )
        report = classify_historical_advance_payments(apps, tenant_id=self.tenant.id)
        self.assertEqual(report['gate_failures'][0]['reason'], 'AMBIGUOUS')
        with self.assertRaises(CommandError):
            call_command('audit_historical_cash_ledger', tenant=str(self.tenant.id), stdout=StringIO())
        with self.assertRaises(RuntimeError):
            mig_0011.backfill_advance_adjustments(apps, None)

    def test_tenant_flag_scopes_audit_and_rejects_invalid_uuid(self):
        self._admit_with_advance(advance_amount='7000.00', advance_applied='7000.00')
        other_tenant = self.create_tenant('Clean Tenant')
        out = StringIO()
        call_command('audit_historical_cash_ledger', tenant=str(other_tenant.id), stdout=out)
        self.assertIn('Historical advance gate passed cleanly.', out.getvalue())

        with self.assertRaises(CommandError):
            call_command('audit_historical_cash_ledger', tenant='not-a-uuid', stdout=StringIO())

    def test_audit_reports_deposit_mismatch_and_missing_advance_date_without_synthesizing_rows(self):
        self._admit_with_advance(
            advance_amount='5000.00',
            advance_applied='0.00',
            advance_collected_date=None,
            advance_mode='cash',
            deposit_amount='2000.00',
            deposit_collected_date=date(2026, 7, 1),
            deposit_mode='cash',
        )
        with tenant_context(self.tenant.id):
            before_count = DepositPayment.objects.count()

        integrity = inspect_deposit_and_date_integrity(apps, tenant_id=self.tenant.id)
        self.assertEqual(len(integrity['deposit_mismatches']), 1)
        self.assertEqual(integrity['deposit_mismatches'][0]['difference'], '2000.00')
        self.assertEqual(len(integrity['missing_advance_dates']), 1)
        self.assertEqual(integrity['missing_advance_dates'][0]['advance_amount'], '5000.00')

        out = StringIO()
        call_command('audit_historical_cash_ledger', tenant=str(self.tenant.id), stdout=out)
        self.assertIn('[DEPOSIT_MISMATCH]', out.getvalue())
        self.assertIn('[MISSING_ADVANCE_DATE]', out.getvalue())
        with tenant_context(self.tenant.id):
            self.assertEqual(DepositPayment.objects.count(), before_count)

    def test_residents_0013_backfill_sets_first_invoice_settled(self):
        r_unissued, adm_unissued = self._admit_with_advance(
            phone='9000000011', advance_amount='10000.00', advance_applied='0.00',
        )
        self.create_invoice(r_unissued, date(2026, 7, 1), status=Invoice.Status.DRAFT)

        r_issued, adm_issued = self._admit_with_advance(
            phone='9000000012', advance_amount='10000.00', advance_applied='0.00',
        )
        self.create_invoice(r_issued, date(2026, 7, 1), status=Invoice.Status.ISSUED)

        with tenant_context(self.tenant.id):
            Admission.objects.filter(pk__in=[adm_unissued.pk, adm_issued.pk]).update(
                first_invoice_advance_settled=False,
            )

        mig_0013.backfill_first_invoice_settled(apps, None)
        with tenant_context(self.tenant.id):
            adm_unissued.refresh_from_db()
            adm_issued.refresh_from_db()
        self.assertFalse(adm_unissued.first_invoice_advance_settled)
        self.assertTrue(adm_issued.first_invoice_advance_settled)

    def test_db_check_constraints_enforce_payment_mode_and_advance_bounds(self):
        resident, admission = self._admit_with_advance(advance_amount='10000.00', advance_applied='0.00')
        invoice = self.create_invoice(resident, date(2026, 7, 1))

        # Blank payment_mode is allowed for is_advance_adjustment=True, rejected for direct payments.
        adj = self.create_payment(
            invoice, amount=Decimal('1000.00'), payment_mode='', is_advance_adjustment=True,
        )
        self.assertEqual(adj.payment_mode, '')

        with tenant_context(self.tenant.id):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Payment.objects.create(
                        tenant_id=self.tenant.id, invoice=invoice, amount=Decimal('1000.00'),
                        payment_date=date(2026, 7, 5), payment_mode='', is_advance_adjustment=False,
                    )
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Admission.objects.filter(pk=admission.pk).update(advance_applied_amount=Decimal('-1.00'))
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Admission.objects.filter(pk=admission.pk).update(advance_applied_amount=Decimal('10001.00'))

