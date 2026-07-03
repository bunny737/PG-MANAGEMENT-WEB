from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.billing.models import Discount


class DiscountModelTests(SimpleTestCase):
    """computed_amount / is_active_on are pure functions of the instance — no
    DB needed (SimpleTestCase)."""

    def test_percentage_amount_is_computed_from_contracted_rent(self):
        discount = Discount(discount_type=Discount.DiscountType.PERCENTAGE, discount_value=Decimal('10'))
        self.assertEqual(discount.computed_amount(Decimal('6500.00')), Decimal('650.00'))

    def test_percentage_amount_rounds_to_two_places(self):
        discount = Discount(discount_type=Discount.DiscountType.PERCENTAGE, discount_value=Decimal('33.33'))
        self.assertEqual(discount.computed_amount(Decimal('100.00')), Decimal('33.33'))

    def test_fixed_amount_returns_the_flat_value(self):
        discount = Discount(discount_type=Discount.DiscountType.FIXED, discount_value=Decimal('500.00'))
        self.assertEqual(discount.computed_amount(Decimal('6500.00')), Decimal('500.00'))

    def test_is_active_on_within_and_outside_window(self):
        discount = Discount(
            discount_type=Discount.DiscountType.FIXED, discount_value=Decimal('500.00'),
            valid_from=date(2026, 7, 1), valid_until=date(2026, 7, 31),
        )
        self.assertFalse(discount.is_active_on(date(2026, 6, 30)))
        self.assertTrue(discount.is_active_on(date(2026, 7, 1)))   # inclusive start
        self.assertTrue(discount.is_active_on(date(2026, 7, 31)))  # inclusive end
        self.assertFalse(discount.is_active_on(date(2026, 8, 1)))

    def test_indefinite_discount_is_active_forever_after_start(self):
        discount = Discount(
            discount_type=Discount.DiscountType.FIXED, discount_value=Decimal('500.00'),
            valid_from=date(2026, 7, 1), valid_until=None,
        )
        self.assertTrue(discount.is_active_on(date(2030, 1, 1)))
        self.assertFalse(discount.is_active_on(date(2026, 6, 1)))
