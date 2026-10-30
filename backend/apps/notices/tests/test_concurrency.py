"""Food-holiday races (Module 24 "Locking"). Every path that writes a holiday
or a credit takes the property's PropertySettings lock first, so they
serialize per property and can't deadlock through the credits' foreign keys.
Each test releases two operations together on separate connections and
asserts there is never a crash (a deadlock surfaces as a database error) and
never an inconsistent result.

Needs real commits on separate connections, so this can't be a
transaction-wrapped TestCase."""
import threading
from datetime import date
from decimal import Decimal
from unittest import mock

from django.db import connection, transaction
from django.test import TransactionTestCase
from rest_framework.exceptions import APIException

from apps.audit.models import AuditLog
from apps.billing import services as billing_services
from apps.billing.models import Invoice, InvoiceLineItem
from apps.billing.tests.base import BillingAPITestCase
from apps.core.tenancy import tenant_context
from apps.properties.models import Property, PropertySettings
from apps.residents import services as resident_services
from apps.residents.models import Admission, Allocation, Resident, Vacate
from apps.subscriptions.models import BedLedgerEntry

from apps.notices import credits, services, sweep
from apps.notices.models import Announcement, FoodHoliday, FoodHolidayCredit

ROUNDS = 3
TODAY = date(2026, 4, 10)
S = FoodHolidayCredit.Status


class FoodHolidayRaceTests(TransactionTestCase):
    def _fixture_teardown(self):
        pass  # see AutoBillingRaceTests: tearDown removes exactly what was created

    def setUp(self):
        for target in ('apps.notices.credits.local_today', 'apps.billing.services.local_today'):
            patcher = mock.patch(target, return_value=TODAY)
            patcher.start()
            self.addCleanup(patcher.stop)
        enqueue = mock.patch.object(billing_services, 'enqueue')
        enqueue.start()
        self.addCleanup(enqueue.stop)
        self.tenant = BillingAPITestCase.create_tenant('Holiday Race Tenant')
        self.owner = BillingAPITestCase.create_owner(self.tenant, email='race-owner@holidays.example.com')
        self.made = 0
        self.new_property()

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            rows = {'tenant_id': self.tenant.id}
            for model in (FoodHolidayCredit, FoodHoliday, Announcement, InvoiceLineItem, Invoice, Vacate,
                          Allocation, Admission, Resident, AuditLog, PropertySettings):
                model.objects.filter(**rows).delete()
            Property.objects.filter(**rows).delete()
            BedLedgerEntry.objects.filter(**rows).delete()
        self.owner.delete()
        self.tenant.delete()

    # --- fixtures ----------------------------------------------------------------

    def new_property(self):
        """A fresh property per round, so one round's holidays and settled
        credits never leak into the next."""
        self.property = BillingAPITestCase.create_property(self.tenant, name=f'Race PG {self.made}')
        self.room = BillingAPITestCase.create_room(
            BillingAPITestCase.create_floor(self.property), room_number='101', rack_rate_with_food=Decimal('7000.00'),
        )

    def resident(self, status=Resident.Status.ACTIVE):
        self.made += 1
        resident = BillingAPITestCase.create_resident(
            self.property, first_name=f'Race{self.made}', phone=f'94{self.made:08d}',
            status=Resident.Status.RESERVED,
        )
        bed = BillingAPITestCase.create_bed(self.room, bed_number=f'R-{self.made}')
        BillingAPITestCase.check_in(resident, bed, joining_date=date(2026, 1, 1))
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=resident.pk).update(status=status)
            return Resident.objects.get(pk=resident.pk)

    def holiday(self, start=date(2026, 3, 20), end=date(2026, 3, 23), name='Dasara'):
        with tenant_context(self.tenant.id):
            return services.create_holiday(
                data={'property': self.property, 'name': name, 'start_date': start, 'end_date': end,
                      'adjust_in_bill': True, 'rate_per_day': Decimal('100.00')},
                post_notice=False, actor=self.owner,
            )

    # --- harness -----------------------------------------------------------------

    def race(self, **operations):
        """Each operation on its own connection, released together. Returns
        {name: result or the APIException raised}; anything else (a deadlock
        surfaces as a database error) fails the test."""
        barrier = threading.Barrier(len(operations))
        results, crashes = {}, []

        def run(name, fn):
            try:
                with tenant_context(self.tenant.id):
                    barrier.wait(timeout=10)
                    results[name] = fn()
            except APIException as exc:
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

    # --- races -------------------------------------------------------------------

    def test_two_overlapping_creates_never_both_succeed(self):
        for round_no in range(ROUNDS):
            start = date(2026, 2, 1 + round_no * 5)

            def create(name):
                return lambda: services.create_holiday(
                    data={'property': self.property, 'name': name, 'start_date': start, 'end_date': start,
                          'adjust_in_bill': False}, post_notice=True, actor=self.owner,
                )

            results = self.race(first=create('A'), second=create('B'))
            outcomes = sorted('created' if isinstance(r, FoodHoliday) else r.get_codes() for r in results.values())
            self.assertEqual(outcomes, ['created', 'holiday_overlap'])

    def test_holiday_edit_and_manual_generate_converge_on_one_correct_credit(self):
        for _ in range(ROUNDS):
            self.new_property()
            resident = self.resident()
            holiday = self.holiday()

            edit = lambda: services.update_holiday(  # noqa: E731
                holiday=holiday, data={'rate_per_day': Decimal('150.00')}, actor=self.owner,
            )
            generate = lambda: billing_services.generate_invoice(  # noqa: E731
                resident=resident, period_start=date(2026, 4, 1), period_end=date(2026, 4, 30),
                due_date=date(2026, 4, 6), actor=self.owner,
            )
            self.race(edit=edit, generate=generate)

            with tenant_context(self.tenant.id):
                rows = list(FoodHolidayCredit.objects.filter(holiday=holiday, resident=resident))
                self.assertEqual(len(rows), 1)
                credit = rows[0]
                self.assertEqual((credit.status, credit.amount), (S.INVOICED, Decimal('600.00')))
                lines = list(InvoiceLineItem.objects.filter(
                    invoice__resident=resident, line_type='food_holiday').values_list('amount', flat=True))
                self.assertEqual(lines, [Decimal('-600.00')])

    def test_finalize_and_holiday_edit_settle_exactly_once(self):
        for _ in range(ROUNDS):
            self.new_property()
            resident = self.resident(status=Resident.Status.NOTICE_PERIOD)
            vacate = BillingAPITestCase.create_vacate(resident, notice_given_date=date(2026, 3, 1),
                                                      expected_vacate_date=date(2026, 4, 1))
            holiday = self.holiday()

            finalize = lambda: resident_services.finalize_vacate(  # noqa: E731
                vacate=vacate, actual_vacate_date=date(2026, 4, 5), maintenance_deduction=Decimal('0.00'),
                maintenance_deduction_note='', refund_date=None, refund_mode='', refund_note='', actor=self.owner,
            )
            edit = lambda: services.update_holiday(  # noqa: E731
                holiday=holiday, data={'rate_per_day': Decimal('150.00')}, actor=self.owner,
            )
            results = self.race(finalize=finalize, edit=edit)

            with tenant_context(self.tenant.id):
                credit = FoodHolidayCredit.objects.get(holiday=holiday, resident=resident)
                settled = Vacate.objects.get(pk=vacate.pk)
            self.assertEqual(credit.status, S.SETTLED)
            self.assertEqual(settled.food_holiday_credit, credit.amount)
            if isinstance(results['edit'], APIException):
                self.assertEqual(results['edit'].get_codes(), 'holiday_locked')  # finalize won
                self.assertEqual(credit.amount, Decimal('400.00'))
            else:
                self.assertEqual(credit.amount, Decimal('600.00'))  # edit won, finalize settled the new rate

    def test_holiday_edit_never_overwrites_a_concurrent_notice_edit(self):
        custom = 'Mess closed — enjoy the festival!'
        for _ in range(ROUNDS):
            self.new_property()
            with tenant_context(self.tenant.id):
                holiday = services.create_holiday(
                    data={'property': self.property, 'name': 'Dasara', 'start_date': date(2026, 3, 20),
                          'end_date': date(2026, 3, 23), 'adjust_in_bill': False},
                    post_notice=True, actor=self.owner,
                )
                notice = holiday.announcement

            edit_holiday = lambda: services.update_holiday(  # noqa: E731
                holiday=holiday, data={'name': 'Vijayadashami'}, actor=self.owner,
            )
            edit_notice = lambda: services.update_announcement(  # noqa: E731
                announcement=notice, data={'body': custom}, actor=self.owner,
            )
            self.race(holiday=edit_holiday, notice=edit_notice)

            with tenant_context(self.tenant.id):
                notice = Announcement.objects.get(pk=notice.pk)
            # The owner's text always survives; only the title may have been regenerated first.
            self.assertEqual(notice.body, custom)
            self.assertFalse(notice.is_auto_text)

    def test_waive_and_daily_allocation_leave_a_consistent_state(self):
        for _ in range(ROUNDS):
            self.new_property()
            resident = self.resident()
            holiday = self.holiday()
            with tenant_context(self.tenant.id):
                draft = billing_services.generate_invoice(
                    resident=resident, period_start=date(2026, 4, 1), period_end=date(2026, 4, 30),
                    due_date=date(2026, 4, 6), actor=self.owner,
                )
                credit = FoodHolidayCredit.objects.get(holiday=holiday, resident=resident)

            def waive():
                # What the line-item DELETE does: Settings -> Invoice -> credit.
                with transaction.atomic():
                    billing_services.lock_property_settings(self.property.pk, self.tenant.id)
                    Invoice.objects.select_for_update().get(pk=draft.pk)
                    return credits.waive(credit, actor=self.owner)

            self.race(waive=waive, sweep=lambda: sweep.run_for_property(self.property.pk, TODAY))

            with tenant_context(self.tenant.id):
                credit = FoodHolidayCredit.objects.get(pk=credit.pk)
                self.assertEqual((credit.status, credit.line_item_id), (S.WAIVED, None))
                self.assertFalse(InvoiceLineItem.objects.filter(invoice=draft, line_type='food_holiday').exists())
