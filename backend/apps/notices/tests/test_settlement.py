"""Food-holiday credits at move-out and abscond (Module 24, owner decisions
2026-10-30): owed credit joins the refund (or the forfeited pool), and days
already credited on an issued bill after the departure are clawed back."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.residents import services as resident_services
from apps.residents.models import Resident, Vacate

from apps.notices import credits
from apps.notices.models import MAX_AMOUNT, FoodHolidayCredit

from .base import NoticesTestCase

S = FoodHolidayCredit.Status
ZERO = Decimal('0.00')


class VacateAmountMathTests(SimpleTestCase):
    def vacate(self, refund_before):
        return SimpleNamespace(refund_before_clawback=lambda deduction, credit: refund_before)

    def plan(self, credit=ZERO, clawback=ZERO):
        return SimpleNamespace(credit_total=credit, clawback_total=clawback)

    def test_clawback_is_recovered_from_the_refund(self):
        self.assertEqual(
            credits.vacate_amounts(self.vacate(Decimal('1500.00')), maintenance_deduction=ZERO,
                                   plan=self.plan(clawback=Decimal('100.00'))),
            (ZERO, Decimal('100.00'), Decimal('100.00'), ZERO),
        )

    def test_recovery_is_capped_at_the_refund(self):
        self.assertEqual(
            credits.vacate_amounts(self.vacate(Decimal('60.00')), maintenance_deduction=ZERO,
                                   plan=self.plan(clawback=Decimal('100.00'))),
            (ZERO, Decimal('100.00'), Decimal('60.00'), Decimal('40.00')),
        )

    def test_a_negative_refund_recovers_nothing_never_a_negative_amount(self):
        self.assertEqual(
            credits.vacate_amounts(self.vacate(Decimal('-50.00')), maintenance_deduction=ZERO,
                                   plan=self.plan(clawback=Decimal('100.00'))),
            (ZERO, Decimal('100.00'), ZERO, Decimal('100.00')),
        )

    def test_amounts_over_the_column_size_are_rejected(self):
        with self.assertRaises(Exception) as ctx:
            credits.vacate_amounts(self.vacate(ZERO), maintenance_deduction=ZERO,
                                   plan=self.plan(credit=MAX_AMOUNT + Decimal('0.01')))
        self.assertIn('settlement_amount_too_large', str(ctx.exception.get_codes()))
        credits.vacate_amounts(self.vacate(ZERO), maintenance_deduction=ZERO, plan=self.plan(credit=MAX_AMOUNT))


class VacateSettlementTests(NoticesTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.admit(security_deposit_amount=Decimal('1500.00'))
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=self.resident.pk).update(status=Resident.Status.NOTICE_PERIOD)
        self.resident = self.fresh(self.resident)
        self.vacate = self.create_vacate(self.resident, notice_given_date=date(2026, 3, 1),
                                         expected_vacate_date=date(2026, 4, 1))

    def finalize(self, actual, deduction=ZERO):
        with tenant_context(self.tenant.id):
            return resident_services.finalize_vacate(
                vacate=self.vacate, actual_vacate_date=actual, maintenance_deduction=deduction,
                maintenance_deduction_note='', refund_date=None, refund_mode='', refund_note='', actor=self.owner,
            )

    def preview(self, actual, deduction=ZERO):
        with tenant_context(self.tenant.id):
            return resident_services.settlement_preview(
                vacate=self.vacate, maintenance_deduction=deduction, actual_vacate_date=actual,
            )

    def test_leaving_mid_holiday_settles_the_days_stayed(self):
        holiday = self.holiday(on=date(2026, 3, 22))  # not over yet: no credit row
        self.assertIsNone(self.credit(holiday, self.resident))

        vacate = self.finalize(date(2026, 3, 22))

        self.assertEqual(vacate.food_holiday_credit, Decimal('300.00'))  # 20, 21, 22
        self.assertEqual(vacate.refund_amount, Decimal('1800.00'))
        credit = self.credit(holiday, self.resident)
        self.assertEqual((credit.status, credit.days, credit.vacate_id), (S.SETTLED, 3, vacate.pk))

    def test_credit_on_a_future_draft_moves_into_the_refund(self):
        holiday = self.holiday()
        draft = self.generate(self.resident)
        self.assertEqual(self.food_lines(draft), [Decimal('-400.00')])

        vacate = self.finalize(date(2026, 4, 5))

        self.assertEqual(self.food_lines(draft), [])
        self.assertEqual(vacate.food_holiday_credit, Decimal('400.00'))
        self.assertEqual(self.credit(holiday, self.resident).status, S.SETTLED)

    def test_credit_already_on_an_issued_bill_is_not_paid_twice(self):
        holiday = self.holiday()
        self.issue(self.generate(self.resident))

        vacate = self.finalize(date(2026, 4, 15))

        self.assertEqual(vacate.food_holiday_credit, ZERO)
        self.assertEqual(vacate.food_holiday_clawback_calculated, ZERO)
        self.assertEqual(vacate.refund_amount, Decimal('1500.00'))
        self.assertEqual(self.credit(holiday, self.resident).status, S.INVOICED)

    def test_waived_credit_is_not_paid_at_move_out(self):
        holiday = self.holiday()
        self.generate(self.resident)
        with tenant_context(self.tenant.id):
            credits.waive(self.credit(holiday, self.resident), actor=self.owner)
        vacate = self.finalize(date(2026, 4, 5))
        self.assertEqual(vacate.food_holiday_credit, ZERO)
        self.assertEqual(self.credit(holiday, self.resident).status, S.WAIVED)

    def test_backdated_move_out_claws_back_the_extra_days(self):
        holiday = self.holiday()
        self.issue(self.generate(self.resident))  # 4 days credited on an issued bill

        vacate = self.finalize(date(2026, 3, 22))  # stayed 3 of them

        self.assertEqual(vacate.food_holiday_clawback_calculated, Decimal('100.00'))
        self.assertEqual(vacate.food_holiday_clawback_recovered, Decimal('100.00'))
        self.assertEqual(vacate.food_holiday_clawback_unrecovered, ZERO)
        self.assertEqual(vacate.refund_amount, Decimal('1400.00'))
        credit = self.credit(holiday, self.resident)
        self.assertEqual((credit.status, credit.clawback_days, credit.clawback_amount, credit.vacate_id),
                         (S.INVOICED, 1, Decimal('100.00'), vacate.pk))

    def test_clawback_larger_than_the_refund_is_capped_and_reported(self):
        with tenant_context(self.tenant.id):
            self.resident.admission.__class__.objects.filter(pk=self.resident.admission.pk).update(
                security_deposit_amount=Decimal('50.00'))
        self.resident = self.fresh(self.resident)
        self.vacate = self.fresh(self.vacate)
        self.holiday()
        self.issue(self.generate(self.resident))

        vacate = self.finalize(date(2026, 3, 21))  # 2 of 4 days stayed -> 200 to claw back

        self.assertEqual(vacate.food_holiday_clawback_calculated, Decimal('200.00'))
        self.assertEqual(vacate.food_holiday_clawback_recovered, Decimal('50.00'))
        self.assertEqual(vacate.food_holiday_clawback_unrecovered, Decimal('150.00'))
        self.assertEqual(vacate.refund_amount, ZERO)

        # Persisted: a reload reproduces the settlement exactly.
        with tenant_context(self.tenant.id):
            reloaded = Vacate.objects.get(pk=vacate.pk)
            self.assertEqual((reloaded.food_holiday_clawback_calculated, reloaded.food_holiday_clawback_recovered,
                              reloaded.food_holiday_clawback_unrecovered, reloaded.refund_amount),
                             (Decimal('200.00'), Decimal('50.00'), Decimal('150.00'), ZERO))

    def test_preview_writes_nothing_and_matches_finalize(self):
        self.holiday()
        self.issue(self.generate(self.resident))
        draft_may = self.generate(self.resident, period=(date(2026, 5, 1), date(2026, 5, 31)))
        self.holiday(start=date(2026, 4, 2), end=date(2026, 4, 3), name='Ugadi', on=date(2026, 4, 10))
        with tenant_context(self.tenant.id):
            rows = (FoodHolidayCredit.objects.count(), AuditLog.objects.count())
            lines_before = self.lines(draft_may)

        preview = self.preview(date(2026, 3, 22), deduction=Decimal('100.00'))

        with tenant_context(self.tenant.id):
            self.assertEqual((FoodHolidayCredit.objects.count(), AuditLog.objects.count()), rows)
        self.assertEqual(self.lines(draft_may), lines_before)

        vacate = self.finalize(date(2026, 3, 22), deduction=Decimal('100.00'))
        self.assertEqual(preview['food_holiday_credit'], vacate.food_holiday_credit)
        self.assertEqual(preview['food_holiday_clawback_calculated'], vacate.food_holiday_clawback_calculated)
        self.assertEqual(preview['food_holiday_clawback_recovered'], vacate.food_holiday_clawback_recovered)
        self.assertEqual(preview['refund_amount'], vacate.refund_amount)

    def test_preview_endpoint_reports_the_food_holiday_figures(self):
        self.holiday()
        self.authenticate(self.owner)
        response = self.client.get(reverse('vacate-settlement-preview', args=[self.vacate.pk]),
                                   {'actual_vacate_date': '2026-03-22'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['food_holiday_credit'], '300.00')
        self.assertEqual(response.data['refund_amount'], '1800.00')

    def test_holiday_entered_after_the_settlement_creates_nothing(self):
        self.finalize(date(2026, 3, 25))
        holiday = self.holiday()
        self.assertIsNone(self.credit(holiday, self.resident))

    def test_vacate_amount_check_constraint(self):
        with tenant_context(self.tenant.id):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Vacate.objects.filter(pk=self.vacate.pk).update(food_holiday_clawback_calculated=Decimal('5.00'))


class AbscondTests(NoticesTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.admit(security_deposit_amount=Decimal('1000.00'))

    def abscond(self, on):
        with tenant_context(self.tenant.id):
            return resident_services.mark_absconded(
                resident=self.resident, absconded_date=on, last_seen_date=on, absconded_note='', actor=self.owner,
            )

    def test_owed_credit_joins_the_forfeited_pool(self):
        holiday = self.holiday()
        self.create_invoice(self.resident, date(2026, 3, 1), period_end=date(2026, 3, 31), total=Decimal('1200.00'))

        record = self.abscond(date(2026, 4, 5))

        self.assertEqual(record.food_holiday_credit, Decimal('400.00'))
        # Dues 1200 vs pool 1000 + 400: fully covered.
        self.assertEqual((record.deposit_applied_to_dues, record.remaining_dues), (Decimal('1200.00'), ZERO))
        credit = self.credit(holiday, self.resident)
        self.assertEqual((credit.status, credit.absconded_record_id), (S.SETTLED, record.pk))

    def test_surplus_credit_is_forfeited_like_the_deposit(self):
        self.holiday()
        record = self.abscond(date(2026, 4, 5))
        self.assertEqual((record.deposit_applied_to_dues, record.remaining_dues), (ZERO, ZERO))
        self.assertEqual(record.food_holiday_credit, Decimal('400.00'))

    def test_clawback_is_added_to_the_dues(self):
        self.holiday()
        april = self.issue(self.generate(self.resident))  # 6600 owed, 4 food days credited
        record = self.abscond(date(2026, 3, 21))  # only 2 of them stayed

        self.assertEqual(record.food_holiday_clawback, Decimal('200.00'))
        with tenant_context(self.tenant.id):
            owed = april.balance_due
        self.assertEqual(record.deposit_applied_to_dues, Decimal('1000.00'))
        self.assertEqual(record.remaining_dues, owed + Decimal('200.00') - Decimal('1000.00'))


class AggregateBoundTests(NoticesTestCase):
    def test_abscond_rejects_dues_over_the_column_size(self):
        resident = self.admit()
        self.create_invoice(resident, date(2026, 3, 1), period_end=date(2026, 3, 31), total=MAX_AMOUNT)
        self.holiday()
        self.issue(self.generate(resident))
        with tenant_context(self.tenant.id), self.assertRaises(Exception) as ctx:
            resident_services.mark_absconded(resident=resident, absconded_date=date(2026, 3, 21),
                                             last_seen_date=None, absconded_note='', actor=self.owner)
        self.assertIn('settlement_amount_too_large', str(ctx.exception.get_codes()))
        with tenant_context(self.tenant.id):
            self.assertEqual(self.fresh(resident).status, Resident.Status.ACTIVE)
