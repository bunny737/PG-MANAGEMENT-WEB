"""Automatic billing races (Module 08 "Locking"). Every path that issues,
holds, generates or changes billing settings takes its locks in one order —
Settings -> Resident -> Vacate -> Invoice -> Admission — and re-checks under
them. These tests release two operations together on separate connections and
assert there is never a deadlock (an unexpected database error) and never an
inconsistent result.

Needs real commits on separate connections, so this can't be a
transaction-wrapped TestCase."""
import threading
from datetime import date
from decimal import Decimal
from unittest import mock

from django.db import connection, transaction
from django.test import TransactionTestCase
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.billing import autobilling, services
from apps.billing.models import (
    AutoBillingCycle, AutoBillingNotice, Invoice, InvoiceLineItem, Payment, ReceiptCounter,
)
from apps.core.tenancy import tenant_context
from apps.notifications.models import NotificationLog
from apps.properties.models import Property, PropertySettings
from apps.residents.models import Admission, Allocation, Resident, Vacate
from apps.residents.services import give_notice
from apps.subscriptions.models import BedLedgerEntry

from .base import BillingAPITestCase

ROUNDS = 5
DRAFT_DAY = date(2026, 8, 14)
BILLING_DAY = date(2026, 8, 15)


class AutoBillingRaceTests(TransactionTestCase):
    def _fixture_teardown(self):
        # The default flush would also wipe migration-seeded tables (plans,
        # feature_catalog, notification templates) for the rest of the run;
        # tearDown removes exactly what this test created instead.
        pass

    def setUp(self):
        # Resident emails (invoice issued, advance receipt) aren't under test
        # here, and an eagerly-run task would write rows after tearDown.
        enqueue_patch = mock.patch.object(services, 'enqueue')
        enqueue_patch.start()
        self.addCleanup(enqueue_patch.stop)
        self.tenant = BillingAPITestCase.create_tenant('Race Tenant')
        self.owner = BillingAPITestCase.create_owner(self.tenant, email='race-owner@concurrency.example.com')
        self.property = BillingAPITestCase.create_property(self.tenant)
        self.room = BillingAPITestCase.create_room(
            BillingAPITestCase.create_floor(self.property), room_number='101',
            rack_rate_with_food=Decimal('7000.00'),
        )
        self.made = 0

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            tenant_rows = {'tenant_id': self.tenant.id}
            for model in (Payment, ReceiptCounter, InvoiceLineItem, AutoBillingCycle, AutoBillingNotice, Invoice,
                          Vacate, Allocation, Admission, Resident, AuditLog, NotificationLog, PropertySettings):
                model.objects.filter(**tenant_rows).delete()
            Property.objects.filter(pk=self.property.pk).delete()
            # After the property: removing its beds writes ledger rows of its own.
            BedLedgerEntry.objects.filter(**tenant_rows).delete()
        self.owner.delete()
        self.tenant.delete()

    # --- fixtures ------------------------------------------------------------

    def scheduled_draft(self, **admission):
        """A resident billed Jul 15..Aug 14 whose Aug 15 draft is scheduled."""
        self.made += 1
        resident = BillingAPITestCase.create_resident(
            self.property, first_name=f'Race{self.made}', phone=f'91{self.made:08d}',
            status=Resident.Status.RESERVED,
        )
        bed = BillingAPITestCase.create_bed(self.room, bed_number=f'R-{self.made}')
        BillingAPITestCase.check_in(resident, bed, joining_date=date(2026, 7, 15), **admission)
        BillingAPITestCase.create_invoice(resident, date(2026, 7, 15), period_end=date(2026, 8, 14))
        with tenant_context(self.tenant.id):
            # Every round starts from the default rule (a race may have changed it).
            PropertySettings.objects.update_or_create(
                property=self.property,
                defaults={'tenant_id': self.tenant.id, 'billing_day_rule': 'admission_date',
                          'billing_day_of_month': None},
            )
            autobilling.generate_next_draft(resident_id=resident.pk, property_id=self.property.pk,
                                            on_date=DRAFT_DAY)
            draft = Invoice.objects.get(resident=resident, period_start=BILLING_DAY)
        return resident, draft

    def fresh(self, invoice):
        with tenant_context(self.tenant.id):
            return Invoice.objects.get(pk=invoice.pk)

    # --- race harness ----------------------------------------------------------

    def race(self, **operations):
        """Run each operation on its own connection, released together. Returns
        {name: result or the ValidationError raised}; any other exception (a
        deadlock surfaces as a database error) fails the test."""
        barrier = threading.Barrier(len(operations))
        results, crashes = {}, []

        def run(name, fn):
            try:
                with tenant_context(self.tenant.id):
                    barrier.wait(timeout=10)
                    results[name] = fn()
            except ValidationError as exc:
                results[name] = exc
            except Exception as exc:  # noqa: BLE001 - surfaced through `crashes`
                crashes.append((name, repr(exc)))
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=item) for item in operations.items()]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(crashes, [], 'an operation crashed instead of finishing or refusing cleanly')
        return results

    @staticmethod
    def auto_issue(draft):
        return lambda: services.issue_invoice(invoice_id=draft.pk, actor=None, on_date=BILLING_DAY, auto=True)

    # --- races -----------------------------------------------------------------

    def test_two_issues_of_one_draft_issue_it_once_and_apply_the_advance_once(self):
        for _ in range(ROUNDS):
            resident, draft = self.scheduled_draft(advance_amount=Decimal('7000.00'),
                                                   advance_collected_date=date(2026, 7, 15), advance_mode='cash')
            with tenant_context(self.tenant.id):
                # `scheduled_draft` created a prior Jul invoice so auto-billing would
                # draft Aug; delete Jul so Aug is genuinely the first invoice and not
                # blocked by an earlier unissued draft.
                Invoice.objects.filter(resident=resident, period_start=date(2026, 7, 15)).delete()
            issue = lambda: services.issue_invoice(invoice_id=draft.pk, actor=self.owner, on_date=BILLING_DAY)  # noqa: E731
            results = self.race(first=issue, second=issue)

            outcomes = sorted('issued' if r == services.ISSUED else r.get_codes()['detail'] for r in results.values())
            self.assertEqual(outcomes, ['invoice_not_draft', 'issued'])
            with tenant_context(self.tenant.id):
                self.assertEqual(Payment.objects.filter(invoice=draft).count(), 1)

    def test_hold_and_auto_issue_never_both_win(self):
        for _ in range(ROUNDS):
            _resident, draft = self.scheduled_draft()
            hold = lambda: services.hold_auto_issue(invoice_id=draft.pk, actor=self.owner)  # noqa: E731
            results = self.race(hold=hold, issue=self.auto_issue(draft))

            draft = self.fresh(draft)
            if draft.status == Invoice.Status.ISSUED:
                self.assertIsInstance(results['hold'], ValidationError)  # invoice_not_draft
            else:
                self.assertTrue(draft.auto_issue_held)
                self.assertEqual(results['issue'], services.SKIPPED)

    def test_settings_change_and_auto_issue_serialize(self):
        for _ in range(ROUNDS):
            _resident, draft = self.scheduled_draft()

            def change_rule():
                # What the settings PATCH does: lock Settings, save, flag drafts.
                with transaction.atomic():
                    settings_obj = PropertySettings.objects.select_for_update().get(property=self.property)
                    settings_obj.billing_day_rule = 'fixed_day'
                    settings_obj.billing_day_of_month = 1
                    settings_obj.save()
                    return services.flag_scheduled_drafts(property_id=self.property.pk, actor=self.owner)

            results = self.race(settings=change_rule, issue=self.auto_issue(draft))

            draft = self.fresh(draft)
            if draft.status == Invoice.Status.ISSUED:
                self.assertEqual(results['issue'], services.ISSUED)
            else:
                self.assertEqual(draft.review_reasons, [Invoice.ReviewReason.RULE_CHANGED])
                self.assertEqual(results['issue'], services.SKIPPED)

    def test_notice_and_auto_issue_serialize(self):
        for _ in range(ROUNDS):
            resident, draft = self.scheduled_draft()
            # Leaves Sep 10, inside the Aug 15..Sep 14 cycle.
            notice = lambda: give_notice(resident=resident, notice_given_date=date(2026, 8, 10), actor=self.owner)  # noqa: E731
            results = self.race(notice=notice, issue=self.auto_issue(draft))

            self.assertIsInstance(results['notice'], Vacate)
            draft = self.fresh(draft)
            if results['issue'] == services.ISSUED:
                self.assertEqual(draft.status, Invoice.Status.ISSUED)  # issued before the notice existed
            else:
                self.assertEqual(results['issue'], services.FLAGGED)
                self.assertEqual(draft.review_reasons, [Invoice.ReviewReason.VACATING])

    def test_manual_overlapping_generate_and_auto_generate_never_both_create(self):
        for _ in range(ROUNDS):
            self.made += 1
            resident = BillingAPITestCase.create_resident(
                self.property, first_name=f'Gen{self.made}', phone=f'92{self.made:08d}',
                status=Resident.Status.RESERVED,
            )
            bed = BillingAPITestCase.create_bed(self.room, bed_number=f'G-{self.made}')
            BillingAPITestCase.check_in(resident, bed, joining_date=date(2026, 7, 15))
            BillingAPITestCase.create_invoice(resident, date(2026, 7, 15), period_end=date(2026, 8, 14))

            manual = lambda: services.generate_invoice(  # noqa: E731
                resident=resident, period_start=date(2026, 8, 20), period_end=date(2026, 9, 19),
                due_date=date(2026, 8, 25), actor=self.owner,
            )
            auto = lambda: autobilling.generate_next_draft(  # noqa: E731
                resident_id=resident.pk, property_id=self.property.pk, on_date=DRAFT_DAY,
            )
            self.race(manual=manual, auto=auto)

            with tenant_context(self.tenant.id):
                periods = sorted(
                    Invoice.objects.filter(resident=resident).exclude(period_start=date(2026, 7, 15))
                    .values_list('period_start', 'period_end')
                )
            # Whichever ran first wins; the other sees it under the resident lock.
            self.assertIn(periods, (
                [(date(2026, 8, 15), date(2026, 9, 14))],
                [(date(2026, 8, 20), date(2026, 9, 19))],
            ))

    def test_grace_change_and_manual_issue_of_a_late_draft_serialize(self):
        for _ in range(ROUNDS):
            _resident, draft = self.scheduled_draft()
            with tenant_context(self.tenant.id):
                Invoice.objects.filter(pk=draft.pk).update(
                    review_reasons=[Invoice.ReviewReason.LATE], auto_issue_on=None,
                    due_date_policy=Invoice.DueDatePolicy.FROM_ISSUE_DATE,
                )
                PropertySettings.objects.filter(property=self.property).update(penalty_grace_days=5)

            def change_grace():
                with transaction.atomic():
                    settings_obj = PropertySettings.objects.select_for_update().get(property=self.property)
                    settings_obj.penalty_grace_days = 10
                    settings_obj.save()

            issue = lambda: services.issue_invoice(invoice_id=draft.pk, actor=self.owner, on_date=BILLING_DAY)  # noqa: E731
            self.race(grace=change_grace, issue=issue)

            # Whichever committed first decides — never a mix.
            self.assertIn(self.fresh(draft).due_date, (date(2026, 8, 20), date(2026, 8, 25)))
