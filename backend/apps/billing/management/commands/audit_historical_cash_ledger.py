"""Pre-deployment read-only audit of historical advance payments, deposit ledgers, and admission dates.

Usage:
    python manage.py audit_historical_cash_ledger
    python manage.py audit_historical_cash_ledger --tenant <tenant-uuid>

Exits non-zero (CommandError) if any GATE_FAILURE is found on historical advance
application reconciliation. Does not mutate any database records.
"""
import uuid

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from apps.billing.historical_audit import (
    classify_historical_advance_payments,
    inspect_deposit_and_date_integrity,
)


class Command(BaseCommand):
    help = (
        'Read-only audit of historical advance payments (hard migration gate) and '
        'deposit payment ledger / admission collection date integrity.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            type=str,
            default=None,
            help='Optional tenant UUID to scope the audit.',
        )

    def handle(self, *args, **options):
        tenant_id = options.get('tenant')
        if tenant_id is not None:
            try:
                tenant_id = uuid.UUID(tenant_id)
            except ValueError as exc:
                raise CommandError(f'Invalid --tenant UUID: {tenant_id}') from exc

        advance_report = classify_historical_advance_payments(apps, tenant_id=tenant_id)
        integrity_report = inspect_deposit_and_date_integrity(apps, tenant_id=tenant_id)

        self.stdout.write(self.style.MIGRATE_HEADING('=== Historical Advance Payment Audit ==='))
        self.stdout.write(
            f"Verified genuine: {len(advance_report['verified_genuine'])}, "
            f"Manual conflicts (stay non-adjustment): {len(advance_report['manual_conflicts'])}, "
            f"Gate failures: {len(advance_report['gate_failures'])}"
        )

        for entry in advance_report['verified_genuine']:
            self.stdout.write(
                f"  [VERIFIED_GENUINE:{entry['status']}] tenant={entry['tenant_id']} "
                f"admission={entry['admission_id']} applied={entry['advance_applied_amount']} "
                f"payments={entry['payment_ids']}"
            )

        for entry in advance_report['manual_conflicts']:
            self.stdout.write(
                self.style.WARNING(
                    f"  [MANUAL_CONFLICT] tenant={entry['tenant_id']} payment={entry['payment_id']} "
                    f"invoice={entry['invoice_id']} amount={entry['amount']} reason={entry['reason']}"
                )
            )

        for entry in advance_report['gate_failures']:
            self.stdout.write(
                self.style.ERROR(
                    f"  [GATE_FAILURE:{entry['reason']}] tenant={entry['tenant_id']} "
                    f"admission={entry['admission_id']} resident={entry['resident_id']} "
                    f"applied={entry['advance_applied_amount']} details={entry}"
                )
            )

        self.stdout.write(self.style.MIGRATE_HEADING('=== Read-Only Deposit & Date Integrity Report ==='))
        self.stdout.write(
            f"Deposit ledger mismatches: {len(integrity_report['deposit_mismatches'])}, "
            f"Missing advance_collected_date: {len(integrity_report['missing_advance_dates'])}"
        )

        for entry in integrity_report['deposit_mismatches']:
            self.stdout.write(
                self.style.WARNING(
                    f"  [DEPOSIT_MISMATCH] tenant={entry['tenant_id']} admission={entry['admission_id']} "
                    f"resident={entry['resident_name']} ({entry['resident_id']}) "
                    f"joining_date={entry['joining_date']} "
                    f"collected={entry['security_deposit_amount']} ledger_sum={entry['deposit_payments_sum']} "
                    f"diff={entry['difference']} mode={entry['security_deposit_mode']} "
                    f"collected_date={entry['security_deposit_collected_date']} "
                    f"audit_logs={len(entry['audit_logs'])}"
                )
            )

        for entry in integrity_report['missing_advance_dates']:
            self.stdout.write(
                self.style.WARNING(
                    f"  [MISSING_ADVANCE_DATE] tenant={entry['tenant_id']} admission={entry['admission_id']} "
                    f"resident={entry['resident_name']} ({entry['resident_id']}) "
                    f"joining_date={entry['joining_date']} advance_amount={entry['advance_amount']}"
                )
            )

        if advance_report['gate_failures']:
            raise CommandError(
                f"Historical advance gate failed with {len(advance_report['gate_failures'])} "
                'unresolved/ambiguous case(s). Resolve them before running billing.0011.'
            )

        self.stdout.write(self.style.SUCCESS('Historical advance gate passed cleanly.'))

