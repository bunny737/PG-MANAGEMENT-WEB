from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.subscriptions import pricing
from apps.subscriptions.models import Plan, PlanBedTier


class PricingEngineTests(TestCase):
    """Pure pricing math (invariant 5: Decimal, never float) — no tenant
    context needed since `Plan`/`PlanBedTier` are the platform catalog."""

    @staticmethod
    def make_plan(tiers):
        plan = Plan.objects.create(
            name='Test Plan', pricing_type=Plan.PricingType.PER_BED_MONTHLY,
            price_per_month=None, max_properties=None, max_residents_per_property=None,
        )
        for up_to_beds, rate in tiers:
            PlanBedTier.objects.create(plan=plan, up_to_beds=up_to_beds, rate_per_bed=rate)
        return plan

    def test_below_free_allowance_is_zero(self):
        plan = self.make_plan([(50, '0.00'), (300, '2.00'), (None, '1.50')])
        breakdown = pricing.monthly_charge(plan, 30)
        self.assertEqual(breakdown.total, Decimal('0.00'))

    def test_mid_tier_charges_only_beds_above_allowance(self):
        plan = self.make_plan([(50, '0.00'), (300, '2.00'), (None, '1.50')])
        # 200 beds: 50 free + 150 @ ₹2 = ₹300
        breakdown = pricing.monthly_charge(plan, 200)
        self.assertEqual(breakdown.total, Decimal('300.00'))

    def test_open_ended_top_tier(self):
        plan = self.make_plan([(50, '0.00'), (300, '2.00'), (None, '1.50')])
        # 400 beds: 50 free + 250 @ ₹2 + 100 @ ₹1.50 = 500 + 150 = ₹650
        breakdown = pricing.monthly_charge(plan, 400)
        self.assertEqual(breakdown.total, Decimal('650.00'))

    def test_boundary_is_monotonically_non_decreasing(self):
        """The defect a percentage-off discount has: adding a bed can lower
        the bill. A marginal tier ladder must never do that."""
        plan = self.make_plan([(50, '0.00'), (300, '2.00'), (None, '1.50')])
        totals = [pricing.monthly_charge(plan, n).total for n in (299, 300, 301)]
        self.assertEqual(totals, sorted(totals))
        self.assertLess(totals[0], totals[2])

    def test_zero_beds(self):
        plan = self.make_plan([(50, '0.00'), (None, '2.00')])
        breakdown = pricing.monthly_charge(plan, 0)
        self.assertEqual(breakdown.total, Decimal('0.00'))
        self.assertEqual(breakdown.tier_lines, [])

    def test_negative_bed_count_rejected(self):
        plan = self.make_plan([(None, '2.00')])
        with self.assertRaises(ValueError):
            pricing.monthly_charge(plan, -1)

    def test_amounts_are_decimal_not_float(self):
        plan = self.make_plan([(50, '0.00'), (300, '2.00'), (None, '1.50')])
        breakdown = pricing.monthly_charge(plan, 275)
        self.assertIsInstance(breakdown.total, Decimal)
        for line in breakdown.tier_lines:
            self.assertIsInstance(line.subtotal, Decimal)
            self.assertIsInstance(line.rate_per_bed, Decimal)

    def test_rounds_half_up_on_the_final_sum(self):
        # `PlanBedTier.rate_per_bed` is itself only 2dp (invariant 5), so
        # monthly_charge's inputs can't produce a mid-cent value — the
        # rounding this exercises happens in `prorated_charge` instead
        # (see test_proration.py). This tests the shared `_quantize` helper
        # directly: exactly halfway rounds up, not to even.
        self.assertEqual(pricing._quantize(Decimal('1.005')), Decimal('1.01'))
        self.assertEqual(pricing._quantize(Decimal('2.675')), Decimal('2.68'))

    def test_tier_lines_sum_to_total(self):
        plan = self.make_plan([(50, '0.00'), (300, '2.00'), (None, '1.50')])
        breakdown = pricing.monthly_charge(plan, 400)
        self.assertEqual(sum(line.subtotal for line in breakdown.tier_lines), breakdown.total)

    def test_monthly_charge_raises_on_empty_tiers(self):
        plan = Plan.objects.create(
            name='Empty Plan', pricing_type=Plan.PricingType.PER_BED_MONTHLY,
        )
        with self.assertRaises(ValueError) as ctx:
            pricing.monthly_charge(plan, 50)
        self.assertIn("has no bed tiers configured", str(ctx.exception))

    def test_monthly_charge_raises_on_missing_open_ended_tier(self):
        plan = self.make_plan([(50, '0.00'), (100, '2.00')])  # missing up_to_beds=None
        with self.assertRaises(ValueError) as ctx:
            pricing.monthly_charge(plan, 150)
        self.assertIn("must have exactly one open-ended tier", str(ctx.exception))

    def test_bed_segments_with_pre_period_entries(self):
        import uuid
        from datetime import datetime, timezone as dt_tz
        from apps.subscriptions.models import BedLedgerEntry
        from apps.core.tenancy import tenant_context

        tenant_id = uuid.uuid4()
        start = date(2026, 7, 1)
        end = date(2026, 8, 1)

        with tenant_context(tenant_id=tenant_id):
            # Pre-period entries (before start date)
            BedLedgerEntry.objects.create(
                tenant_id=tenant_id, bed_id=uuid.uuid4(), event=BedLedgerEntry.Event.ADDED,
                occurred_at=datetime(2026, 5, 10, tzinfo=dt_tz.utc),
            )
            BedLedgerEntry.objects.create(
                tenant_id=tenant_id, bed_id=uuid.uuid4(), event=BedLedgerEntry.Event.ADDED,
                occurred_at=datetime(2026, 6, 1, tzinfo=dt_tz.utc),
            )
            BedLedgerEntry.objects.create(
                tenant_id=tenant_id, bed_id=uuid.uuid4(), event=BedLedgerEntry.Event.REMOVED,
                occurred_at=datetime(2026, 6, 15, tzinfo=dt_tz.utc),
            )
            # Cycle entry (inside start..end)
            BedLedgerEntry.objects.create(
                tenant_id=tenant_id, bed_id=uuid.uuid4(), event=BedLedgerEntry.Event.ADDED,
                occurred_at=datetime(2026, 7, 15, tzinfo=dt_tz.utc),
            )

            segments = pricing.bed_segments(tenant_id, start, end)
        self.assertEqual(len(segments), 2)
        # Seg 1: 2026-07-01 to 2026-07-15 with opening count = 1 (2 added - 1 removed)
        self.assertEqual(segments[0], (date(2026, 7, 1), date(2026, 7, 15), 1))
        # Seg 2: 2026-07-15 to 2026-08-01 with count = 2
        self.assertEqual(segments[1], (date(2026, 7, 15), date(2026, 8, 1), 2))


class NextCycleEndTests(TestCase):
    def test_28_day_february(self):
        self.assertEqual(pricing.next_cycle_end(date(2027, 2, 1)), date(2027, 3, 1))

    def test_leap_year_february(self):
        self.assertEqual(pricing.next_cycle_end(date(2028, 2, 1)), date(2028, 3, 1))

    def test_31_day_month_clamped(self):
        # Jan 31 + 1 month: February has no 31st, so it clamps to Feb 28/29.
        self.assertEqual(pricing.next_cycle_end(date(2027, 1, 31)), date(2027, 2, 28))

    def test_december_rolls_year(self):
        self.assertEqual(pricing.next_cycle_end(date(2026, 12, 15)), date(2027, 1, 15))
