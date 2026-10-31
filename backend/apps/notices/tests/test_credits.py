"""Food-holiday credits (Module 24): entitlement, timing, allocation onto
drafts, rebalance, and the system-owned line / waiver rules."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase
from django.urls import reverse

from apps.billing.models import Invoice, InvoiceLineItem
from apps.core.tenancy import tenant_context
from apps.residents.models import Admission, Resident

from apps.notices import credits
from apps.notices.models import MAX_AMOUNT, FoodHolidayCredit
from apps.notices.sweep import allocate_food_holiday_credits

from .base import APRIL, MAY, NoticesTestCase, today

S = FoodHolidayCredit.Status


class EntitlementMathTests(SimpleTestCase):
    def holiday(self, start=date(2026, 3, 20), end=date(2026, 3, 23), adjust=True):
        return SimpleNamespace(start_date=start, end_date=end, adjust_in_bill=adjust)

    def test_whole_holiday_for_a_resident_who_stayed_throughout(self):
        self.assertEqual(credits.entitled_days(holiday=self.holiday(), joining_date=date(2026, 1, 1),
                                               with_food=True), 4)

    def test_nothing_without_food_or_without_adjustment(self):
        self.assertEqual(credits.entitled_days(holiday=self.holiday(), joining_date=date(2026, 1, 1),
                                               with_food=False), 0)
        self.assertEqual(credits.entitled_days(holiday=self.holiday(adjust=False), joining_date=date(2026, 1, 1),
                                               with_food=True), 0)

    def test_joining_mid_holiday_counts_from_the_joining_day(self):
        self.assertEqual(credits.entitled_days(holiday=self.holiday(), joining_date=date(2026, 3, 22),
                                               with_food=True), 2)
        self.assertEqual(credits.entitled_days(holiday=self.holiday(), joining_date=date(2026, 3, 24),
                                               with_food=True), 0)

    def test_leaving_mid_holiday_counts_up_to_the_last_day_stayed(self):
        self.assertEqual(credits.entitled_days(holiday=self.holiday(), joining_date=date(2026, 1, 1),
                                               with_food=True, through=date(2026, 3, 22)), 3)
        self.assertEqual(credits.entitled_days(holiday=self.holiday(), joining_date=date(2026, 1, 1),
                                               with_food=True, through=date(2026, 3, 19)), 0)

    def test_amount_bound(self):
        self.assertEqual(credits.check_amount(MAX_AMOUNT, 'x'), MAX_AMOUNT)
        with self.assertRaises(Exception) as ctx:
            credits.check_amount(MAX_AMOUNT + Decimal('0.01'), 'food_holiday_credit')
        self.assertIn('settlement_amount_too_large', str(ctx.exception.get_codes()))


class TimingAndAllocationTests(NoticesTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.admit()

    def test_next_bill_after_the_holiday_gets_a_negative_line(self):
        holiday = self.holiday()
        self.assertEqual(self.credit(holiday, self.resident).status, S.PENDING)

        invoice = self.generate(self.resident)

        self.assertEqual(self.food_lines(invoice), [Decimal('-400.00')])
        self.assertEqual(self.total(invoice), Decimal('6600.00'))
        credit = self.credit(holiday, self.resident)
        self.assertEqual((credit.status, credit.days, credit.amount), (S.INVOICED, 4, Decimal('400.00')))
        with tenant_context(self.tenant.id):
            self.assertEqual(credit.line_item.label, 'Food holiday — Dasara (4 days × ₹100.00)')

    def test_without_food_resident_gets_nothing(self):
        other = self.admit(food=Admission.FoodPreference.WITHOUT_FOOD)
        holiday = self.holiday()
        self.assertIsNone(self.credit(holiday, other))
        self.assertEqual(self.food_lines(self.generate(other)), [])

    def test_resident_who_joined_mid_holiday_gets_partial_days(self):
        late = self.admit(joining=date(2026, 3, 22))
        holiday = self.holiday()
        self.assertEqual(self.credit(holiday, late).days, 2)

    def test_holiday_without_adjustment_creates_no_credits(self):
        holiday = self.holiday(adjust=False, rate=None)
        self.assertIsNone(self.credit(holiday, self.resident))
        self.assertEqual(self.food_lines(self.generate(self.resident)), [])

    def test_bill_starting_during_the_holiday_gets_nothing_the_next_one_does(self):
        self.holiday()
        during = self.generate(self.resident, period=(date(2026, 3, 21), date(2026, 4, 20)))
        after = self.generate(self.resident, period=(date(2026, 4, 21), date(2026, 5, 20)))
        self.assertEqual(self.food_lines(during), [])
        self.assertEqual(self.food_lines(after), [Decimal('-400.00')])

    def test_future_draft_gets_no_credit_until_the_holiday_has_ended(self):
        draft = self.generate(self.resident, on=date(2026, 3, 1))
        holiday = self.holiday(on=date(2026, 3, 1))
        self.assertIsNone(self.credit(holiday, self.resident))
        self.assertEqual(self.food_lines(draft), [])

        with today(date(2026, 3, 23)):
            allocate_food_holiday_credits()  # last holiday day: not over yet
        self.assertEqual(self.food_lines(draft), [])

        with today(date(2026, 3, 24)):
            allocate_food_holiday_credits()
        self.assertEqual(self.food_lines(draft), [Decimal('-400.00')])

    def test_missed_sweeps_are_caught_up(self):
        draft = self.generate(self.resident, on=date(2026, 3, 1))
        self.holiday(on=date(2026, 3, 1))
        with today(date(2026, 3, 29)):
            allocate_food_holiday_credits()
        self.assertEqual(self.food_lines(draft), [Decimal('-400.00')])

    def test_an_issued_future_bill_is_never_touched(self):
        april = self.generate(self.resident, on=date(2026, 3, 1))
        april = self.issue(april, on=date(2026, 3, 1))
        holiday = self.holiday(on=date(2026, 3, 1))
        with today(date(2026, 3, 24)):
            allocate_food_holiday_credits()
        self.assertEqual(self.food_lines(april), [])
        self.assertEqual(self.credit(holiday, self.resident).status, S.PENDING)

        may = self.generate(self.resident, period=MAY)
        self.assertEqual(self.food_lines(may), [Decimal('-400.00')])

    def test_lands_on_the_earliest_of_several_drafts(self):
        april = self.generate(self.resident, on=date(2026, 3, 1))
        may = self.generate(self.resident, period=MAY, on=date(2026, 3, 1))
        self.holiday()
        self.assertEqual(self.food_lines(april), [Decimal('-400.00')])
        self.assertEqual(self.food_lines(may), [])

    def test_generating_a_later_draft_still_leaves_it_on_the_earliest(self):
        april = self.generate(self.resident)
        self.holiday()
        may = self.generate(self.resident, period=MAY)
        self.assertEqual(self.food_lines(april), [Decimal('-400.00')])
        self.assertEqual(self.food_lines(may), [])

    def test_generating_an_earlier_draft_does_not_move_an_attached_credit(self):
        may = self.generate(self.resident, period=MAY)
        holiday = self.holiday()
        self.assertEqual(self.food_lines(may), [Decimal('-400.00')])

        april = self.generate(self.resident)
        self.assertEqual(self.food_lines(april), [])
        self.assertEqual(self.food_lines(may), [Decimal('-400.00')])
        with tenant_context(self.tenant.id):
            self.assertEqual(self.credit(holiday, self.resident).line_item.invoice_id, may.pk)

    def test_strict_fifo_a_big_first_credit_blocks_a_smaller_later_one(self):
        self.holiday(start=date(2026, 3, 1), end=date(2026, 3, 10), name='Long')   # ₹1000
        self.holiday(start=date(2026, 3, 20), end=date(2026, 3, 21), name='Short')  # ₹200
        draft = self.draft(self.resident, APRIL, Decimal('800.00'))
        with today(date(2026, 4, 10)):
            allocate_food_holiday_credits()
        self.assertEqual(self.food_lines(draft), [])
        self.assertEqual([c.status for c in self.credits_of(self.resident)], [S.PENDING, S.PENDING])

    def test_pending_credits_retry_when_a_draft_grows(self):
        self.holiday(start=date(2026, 3, 1), end=date(2026, 3, 10), name='Long')
        self.holiday(start=date(2026, 3, 20), end=date(2026, 3, 21), name='Short')
        draft = self.draft(self.resident, APRIL, Decimal('800.00'))
        self.authenticate(self.owner)
        with today(date(2026, 4, 10)):
            response = self.client.post(reverse('invoice-add-line-item', args=[draft.pk]), {
                'line_type': 'electricity', 'label': 'Electricity', 'amount': '600.00', 'order': 2,
            }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        # 1400 total: the ₹1000 credit fits (leaves 400); the ₹200 one then fits too.
        self.assertEqual(sorted(self.food_lines(draft)), [Decimal('-1000.00'), Decimal('-200.00')])
        self.assertEqual(self.total(draft), Decimal('200.00'))

    def test_deleting_a_draft_moves_its_credit_to_the_next_draft(self):
        april = self.generate(self.resident)
        may = self.generate(self.resident, period=MAY)
        holiday = self.holiday()
        self.assertEqual(self.food_lines(april), [Decimal('-400.00')])

        self.authenticate(self.owner)
        with today(date(2026, 4, 10)):
            response = self.client.delete(reverse('invoice-detail', args=[april.pk]))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.food_lines(may), [Decimal('-400.00')])
        self.assertEqual(self.credit(holiday, self.resident).status, S.INVOICED)

    def test_deleting_the_only_draft_returns_the_credit_to_pending(self):
        april = self.generate(self.resident)
        holiday = self.holiday()
        self.authenticate(self.owner)
        with today(date(2026, 4, 10)):
            self.client.delete(reverse('invoice-detail', args=[april.pk]))
        credit = self.credit(holiday, self.resident)
        self.assertEqual((credit.status, credit.line_item_id), (S.PENDING, None))
        self.assertEqual(self.food_lines(self.generate(self.resident)), [Decimal('-400.00')])

    def test_daily_sweep_creates_credits_for_residents_admitted_after_the_holiday_was_saved(self):
        holiday = self.holiday()
        newcomer = self.admit(joining=date(2026, 3, 18))  # admitted later, joined before the holiday
        self.assertIsNone(self.credit(holiday, newcomer))
        with today(date(2026, 4, 11)):
            allocate_food_holiday_credits()
        self.assertEqual(self.credit(holiday, newcomer).days, 4)

    def test_vacated_residents_get_no_new_credits(self):
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=self.resident.pk).update(status=Resident.Status.VACATED)
        holiday = self.holiday()
        self.assertIsNone(self.credit(holiday, self.resident))


class RebalanceTests(NoticesTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.admit()
        self.authenticate(self.owner)

    def accommodation(self, invoice):
        with tenant_context(invoice.tenant_id):
            return InvoiceLineItem.objects.get(invoice=invoice, line_type='accommodation')

    def patch_line(self, invoice, line, amount):
        with today(date(2026, 4, 10)):
            return self.client.patch(reverse('invoice-modify-line-item', args=[invoice.pk, line.pk]),
                                     {'amount': amount}, format='json')

    def test_editing_the_bill_down_detaches_credits_newest_holiday_first(self):
        a = self.holiday(start=date(2026, 2, 1), end=date(2026, 2, 1), name='A')
        b = self.holiday(start=date(2026, 2, 10), end=date(2026, 2, 11), name='B')
        c = self.holiday(start=date(2026, 3, 1), end=date(2026, 3, 3), name='C')
        invoice = self.generate(self.resident)
        self.assertEqual(self.total(invoice), Decimal('6400.00'))  # 7000 - 100 - 200 - 300

        response = self.patch_line(invoice, self.accommodation(invoice), '250.00')
        self.assertEqual(response.status_code, 200, response.data)
        # 250 - 600 <= 0: C (300) comes off first (-> -50), then B (200) -> 250 - 100 = 150 > 0.
        self.assertEqual(self.credit(c, self.resident).status, S.PENDING)
        self.assertEqual(self.credit(b, self.resident).status, S.PENDING)
        self.assertEqual(self.credit(a, self.resident).status, S.INVOICED)
        self.assertEqual(self.total(invoice), Decimal('150.00'))

    def test_order_comes_from_the_holiday_dates_not_the_attach_time(self):
        a = self.holiday(start=date(2026, 2, 1), end=date(2026, 2, 1), name='A')
        b = self.holiday(start=date(2026, 2, 10), end=date(2026, 2, 11), name='B')
        c = self.holiday(start=date(2026, 3, 1), end=date(2026, 3, 3), name='C')
        invoice = self.generate(self.resident)
        # Waive and restore B: it is re-attached last, after C.
        line_b = self.credit(b, self.resident).line_item_id
        with today(date(2026, 4, 10)):
            self.client.delete(reverse('invoice-modify-line-item', args=[invoice.pk, line_b]))
            response = self.client.post(reverse('food-holiday-restore-credit',
                                                args=[b.pk, self.credit(b, self.resident).pk]))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.credit(b, self.resident).status, S.INVOICED)

        self.patch_line(invoice, self.accommodation(invoice), '350.00')
        # 350 - 600: C off (-> 350 - 300 = 50 > 0). B stays despite being attached last.
        self.assertEqual(self.credit(c, self.resident).status, S.PENDING)
        self.assertEqual(self.credit(b, self.resident).status, S.INVOICED)
        self.assertEqual(self.credit(a, self.resident).status, S.INVOICED)

    def test_owner_lines_alone_at_zero_are_left_as_set(self):
        holiday = self.holiday()
        invoice = self.generate(self.resident)
        response = self.patch_line(invoice, self.accommodation(invoice), '0.00')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.credit(holiday, self.resident).status, S.PENDING)
        self.assertEqual(self.lines(invoice), [('accommodation', Decimal('0.00'))])

    def test_detached_credit_moves_to_a_later_draft_that_can_take_it(self):
        holiday = self.holiday()
        april = self.generate(self.resident)
        may = self.generate(self.resident, period=MAY)
        self.patch_line(april, self.accommodation(april), '100.00')
        self.assertEqual(self.food_lines(april), [])
        self.assertEqual(self.food_lines(may), [Decimal('-400.00')])
        self.assertEqual(self.credit(holiday, self.resident).status, S.INVOICED)


class LineRuleTests(NoticesTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.admit()
        self.holiday_obj = self.holiday()
        self.invoice = self.generate(self.resident)
        self.authenticate(self.owner)
        with tenant_context(self.tenant.id):
            self.food_line = InvoiceLineItem.objects.get(invoice=self.invoice, line_type='food_holiday')

    def url(self, line):
        return reverse('invoice-modify-line-item', args=[self.invoice.pk, line.pk])

    def test_cannot_add_a_food_holiday_line_by_hand(self):
        response = self.client.post(reverse('invoice-add-line-item', args=[self.invoice.pk]), {
            'line_type': 'food_holiday', 'label': 'Free food', 'amount': '-999.00',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['line_type'][0].code, 'line_locked')

    def test_cannot_edit_a_food_holiday_line(self):
        response = self.client.patch(self.url(self.food_line), {'amount': '-10.00'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.food_lines(self.invoice), [Decimal('-400.00')])

    def test_cannot_retype_another_line_into_a_food_holiday_line(self):
        with tenant_context(self.tenant.id):
            accommodation = InvoiceLineItem.objects.get(invoice=self.invoice, line_type='accommodation')
        response = self.client.patch(self.url(accommodation), {'line_type': 'food_holiday'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_deleting_the_line_waives_the_credit(self):
        with today(date(2026, 4, 10)):
            response = self.client.delete(self.url(self.food_line))
        self.assertEqual(response.status_code, 200, response.data)
        credit = self.credit(self.holiday_obj, self.resident)
        self.assertEqual((credit.status, credit.line_item_id), (S.WAIVED, None))
        self.assertEqual(self.food_lines(self.invoice), [])
        # A waived credit is never offered again.
        self.assertEqual(self.food_lines(self.generate(self.resident, period=MAY)), [])

    def waive(self):
        with today(date(2026, 4, 10)):
            self.client.delete(self.url(self.food_line))

    def test_waiver_survives_date_and_rate_edits(self):
        self.waive()
        self.edit_holiday(self.holiday_obj, end_date=date(2026, 3, 24), rate_per_day=Decimal('150.00'))
        credit = self.credit(self.holiday_obj, self.resident)
        self.assertEqual((credit.status, credit.days, credit.amount), (S.WAIVED, 5, Decimal('750.00')))
        self.assertEqual(self.food_lines(self.invoice), [])

    def test_waiver_survives_turning_the_adjustment_off_and_on(self):
        self.waive()
        self.edit_holiday(self.holiday_obj, adjust_in_bill=False)
        self.assertEqual(self.credit(self.holiday_obj, self.resident).status, S.WAIVED)
        self.edit_holiday(self.holiday_obj, adjust_in_bill=True)
        self.assertEqual(self.credit(self.holiday_obj, self.resident).status, S.WAIVED)
        self.assertEqual(self.food_lines(self.invoice), [])

    def test_turning_the_adjustment_off_removes_the_line(self):
        self.edit_holiday(self.holiday_obj, adjust_in_bill=False)
        self.assertEqual(self.food_lines(self.invoice), [])
        self.assertIsNone(self.credit(self.holiday_obj, self.resident))

    def restore_url(self):
        return reverse('food-holiday-restore-credit',
                       args=[self.holiday_obj.pk, self.credit(self.holiday_obj, self.resident).pk])

    def test_restore_puts_the_credit_back_on_the_draft(self):
        self.waive()
        with today(date(2026, 4, 10)):
            response = self.client.post(self.restore_url())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], S.INVOICED)
        self.assertEqual(self.food_lines(self.invoice), [Decimal('-400.00')])

    def test_restore_is_refused_after_the_stay_ended(self):
        self.waive()
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=self.resident.pk).update(status=Resident.Status.VACATED)
        response = self.client.post(self.restore_url())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'].code, 'resident_not_current')

    def test_restore_is_refused_while_the_adjustment_is_off(self):
        self.waive()
        self.edit_holiday(self.holiday_obj, adjust_in_bill=False)
        response = self.client.post(self.restore_url())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'].code, 'adjustment_off')

    def test_restore_after_moving_the_holiday_into_the_future_waits_for_it_to_end(self):
        self.waive()
        self.edit_holiday(self.holiday_obj, start_date=date(2026, 4, 20), end_date=date(2026, 4, 22))
        with today(date(2026, 4, 10)):
            response = self.client.post(self.restore_url())
        self.assertEqual(response.status_code, 200, response.data)
        credit = self.credit(self.holiday_obj, self.resident)
        self.assertEqual((credit.status, credit.line_item_id), (S.PENDING, None))

        may = self.generate(self.resident, period=MAY, on=date(2026, 4, 15))
        self.assertEqual(self.food_lines(may), [])
        with today(date(2026, 4, 23)):
            allocate_food_holiday_credits()
        self.assertEqual(self.food_lines(may), [Decimal('-300.00')])


class TransitionGuardTests(NoticesTestCase):
    def setUp(self):
        super().setUp()
        self.resident = self.admit()
        self.holiday_obj = self.holiday()

    def test_detach_only_to_pending_or_waived(self):
        with tenant_context(self.tenant.id), self.assertRaises(ValueError):
            credits.detach(self.credit(self.holiday_obj, self.resident), to=S.SETTLED)

    def test_delete_credit_on_a_draft_removes_its_line(self):
        invoice = self.generate(self.resident)
        with tenant_context(self.tenant.id), transaction.atomic():
            credits.delete_credit(self.credit(self.holiday_obj, self.resident))
        self.assertEqual(self.food_lines(invoice), [])

    def test_deleting_a_draft_outside_the_service_is_refused(self):
        invoice = self.generate(self.resident)
        with tenant_context(self.tenant.id), self.assertRaises(Exception):
            with transaction.atomic():
                Invoice.objects.filter(pk=invoice.pk).delete()  # PROTECT on the credit's line

    def test_status_and_references_must_agree(self):
        credit = self.credit(self.holiday_obj, self.resident)
        with tenant_context(self.tenant.id):
            with self.assertRaises(IntegrityError), transaction.atomic():
                FoodHolidayCredit.objects.filter(pk=credit.pk).update(status=S.INVOICED)
            with self.assertRaises(IntegrityError), transaction.atomic():
                FoodHolidayCredit.objects.filter(pk=credit.pk).update(status=S.SETTLED)
            with self.assertRaises(IntegrityError), transaction.atomic():
                FoodHolidayCredit.objects.filter(pk=credit.pk).update(amount=Decimal('1.00'))
