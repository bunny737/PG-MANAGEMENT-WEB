"""Pure cycle / money math behind automatic billing (no database)."""
from datetime import date
from decimal import Decimal
from fractions import Fraction

from django.test import SimpleTestCase

from apps.billing.autobilling import (
    Schedule,
    apply_fraction,
    calendar_fraction,
    cycle_starting,
    partial_discount,
    schedule_for,
)
from apps.billing.models import Discount

MONTHLY_31 = Schedule('monthly', anchor_day=31)
FIXED_15 = Schedule('monthly', anchor_day=15)
FIXED_1 = Schedule('monthly', anchor_day=1)


def fixed(value):
    return Discount(discount_type=Discount.DiscountType.FIXED, discount_value=Decimal(value))


def percent(value):
    return Discount(discount_type=Discount.DiscountType.PERCENTAGE, discount_value=Decimal(value))


class ScheduleTests(SimpleTestCase):
    def test_admission_day_31_clamps_to_month_end_and_returns(self):
        days, cursor = [], date(2026, 1, 31)
        for _ in range(4):
            days.append(cursor)
            cursor = MONTHLY_31.billing_day_after(cursor)
        self.assertEqual(days, [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)])

    def test_leap_february_uses_the_29th(self):
        self.assertEqual(MONTHLY_31.billing_day_after(date(2028, 1, 31)), date(2028, 2, 29))
        self.assertEqual(Schedule('monthly', anchor_day=29).billing_day_after(date(2027, 1, 29)),
                         date(2027, 2, 28))

    def test_cycle_containing_a_day(self):
        self.assertEqual(FIXED_15.billing_day_on_or_before(date(2026, 3, 10)), date(2026, 2, 15))
        self.assertEqual(FIXED_15.billing_day_on_or_before(date(2026, 3, 15)), date(2026, 3, 15))
        self.assertEqual(MONTHLY_31.billing_day_on_or_before(date(2026, 3, 5)), date(2026, 2, 28))

    def test_weekly_follows_the_joining_weekday(self):
        weekly = Schedule('weekly', anchor_date=date(2026, 7, 1))
        self.assertTrue(weekly.is_billing_day(date(2026, 7, 15)))
        self.assertFalse(weekly.is_billing_day(date(2026, 7, 16)))
        self.assertEqual(weekly.billing_day_after(date(2026, 7, 9)), date(2026, 7, 15))
        self.assertEqual(weekly.billing_day_on_or_before(date(2026, 7, 14)), date(2026, 7, 8))

    def test_schedule_for_billing_modes(self):
        joining = date(2026, 7, 20)
        common = dict(joining_date=joining, billing_day_rule='admission_date', billing_day_of_month=None)
        self.assertEqual(schedule_for(billing_mode='monthly', **common), Schedule('monthly', anchor_day=20))
        self.assertEqual(schedule_for(billing_mode='weekly', **common), Schedule('weekly', anchor_date=joining))
        self.assertIsNone(schedule_for(billing_mode='daily', **common))
        self.assertEqual(
            schedule_for(billing_mode='monthly', joining_date=joining,
                         billing_day_rule='fixed_day', billing_day_of_month=1),
            Schedule('monthly', anchor_day=1),
        )
        # Weekly residents ignore the property's fixed day.
        self.assertEqual(
            schedule_for(billing_mode='weekly', joining_date=joining,
                         billing_day_rule='fixed_day', billing_day_of_month=1).kind,
            'weekly',
        )


class CycleTests(SimpleTestCase):
    def test_full_cycle_from_a_billing_day_has_fraction_one(self):
        cycle = cycle_starting(date(2026, 1, 31), MONTHLY_31)
        self.assertEqual((cycle.start, cycle.end), (date(2026, 1, 31), date(2026, 2, 27)))
        # Per-month segments would be 1/31 + 27/28 != 1 — a full cycle is 1 by definition.
        self.assertEqual(cycle.fraction, 1)
        self.assertFalse(cycle.is_partial)

    def test_partial_spanning_two_months_is_split_per_calendar_month(self):
        cycle = cycle_starting(date(2026, 1, 20), FIXED_15)
        self.assertEqual((cycle.start, cycle.end), (date(2026, 1, 20), date(2026, 2, 14)))
        self.assertEqual(cycle.fraction, Fraction(12, 31) + Fraction(14, 28))
        # 7000 x 12/31 + 7000 x 14/28 = 2709.677... + 3500
        self.assertEqual(apply_fraction(Decimal('7000.00'), cycle.fraction), Decimal('6209.68'))

    def test_partial_within_one_month(self):
        cycle = cycle_starting(date(2026, 7, 20), FIXED_1)
        self.assertEqual((cycle.start, cycle.end), (date(2026, 7, 20), date(2026, 7, 31)))
        self.assertEqual(apply_fraction(Decimal('7000.00'), cycle.fraction), Decimal('2709.68'))

    def test_partial_never_costs_more_than_a_full_cycle(self):
        # Jan 16..Feb 14 sums to 16/31 + 14/28 > 1.
        self.assertEqual(calendar_fraction(date(2026, 1, 16), date(2026, 2, 14), FIXED_15), 1)

    def test_a_capped_partial_is_still_partial(self):
        # Priced like a full cycle, but it doesn't start on a billing day, so
        # it must still go to the owner for confirmation.
        cycle = cycle_starting(date(2026, 1, 16), FIXED_15)
        self.assertEqual(cycle.fraction, 1)
        self.assertTrue(cycle.is_partial)
        self.assertFalse(cycle_starting(date(2026, 1, 15), FIXED_15).is_partial)

    def test_weekly_partial_is_days_over_seven(self):
        weekly = Schedule('weekly', anchor_date=date(2026, 7, 1))
        cycle = cycle_starting(date(2026, 7, 4), weekly)
        self.assertEqual((cycle.start, cycle.end), (date(2026, 7, 4), date(2026, 7, 7)))
        self.assertEqual(cycle.fraction, Fraction(4, 7))


class PartialDiscountTests(SimpleTestCase):
    HALF = Fraction(1, 2)

    def test_fixed_discount_is_prorated_by_the_calendar_fraction(self):
        amount = partial_discount(fixed('500.00'), base_amount=Decimal('3500.00'),
                                  contracted_rent=Decimal('7000.00'), fraction=self.HALF)
        self.assertEqual(amount, Decimal('250.00'))

    def test_full_cycle_keeps_the_full_fixed_discount(self):
        amount = partial_discount(fixed('500.00'), base_amount=Decimal('7000.00'),
                                  contracted_rent=Decimal('7000.00'), fraction=Fraction(1))
        self.assertEqual(amount, Decimal('500.00'))

    def test_percentage_discount_applies_to_the_rent_charged(self):
        amount = partial_discount(percent('10'), base_amount=Decimal('3500.00'),
                                  contracted_rent=Decimal('7000.00'), fraction=self.HALF)
        self.assertEqual(amount, Decimal('350.00'))

    def test_overridden_first_month_amount_does_not_change_the_fixed_fraction(self):
        # A 1000 concession for a half period: the fixed discount is still
        # half of 500, not 500 x (1000 / 7000).
        amount = partial_discount(fixed('500.00'), base_amount=Decimal('1000.00'),
                                  contracted_rent=Decimal('7000.00'), fraction=self.HALF)
        self.assertEqual(amount, Decimal('250.00'))

    def test_zero_rent_gets_no_discount_line(self):
        self.assertIsNone(partial_discount(fixed('500.00'), base_amount=Decimal('0.00'),
                                           contracted_rent=Decimal('0.00'), fraction=Fraction(1)))
        self.assertIsNone(partial_discount(None, base_amount=Decimal('7000.00'),
                                           contracted_rent=Decimal('7000.00'), fraction=Fraction(1)))

    def test_rounding_is_half_up_to_paise(self):
        self.assertEqual(apply_fraction(Decimal('100.00'), Fraction(1, 3)), Decimal('33.33'))
        self.assertEqual(apply_fraction(Decimal('0.05'), Fraction(1, 2)), Decimal('0.03'))
