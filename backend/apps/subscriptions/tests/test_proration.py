from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal, ROUND_HALF_UP
import uuid

from apps.core.tenancy import tenant_context
from apps.subscriptions import pricing
from apps.subscriptions.models import BedLedgerEntry
from apps.subscriptions.tests.base import SubscriptionAPITestCase


def _entry(tenant_id, event, day):
    return BedLedgerEntry.objects.create(
        tenant_id=tenant_id, bed_id=uuid.uuid4(), event=event,
        occurred_at=datetime(day.year, day.month, day.day, tzinfo=dt_timezone.utc),
    )


class BedSegmentsTests(SubscriptionAPITestCase):
    """`pricing.bed_segments` replays the ledger into constant-count slices —
    tested against directly-constructed ledger rows (not real Bed
    add/delete) so the segment math is isolated from the signal wiring,
    which `BedLedgerSignalTests` below covers separately."""

    def setUp(self):
        self.tenant = self.create_tenant()

    def test_no_entries_before_cycle_is_zero_beds_throughout(self):
        with tenant_context(self.tenant.id):
            segments = pricing.bed_segments(self.tenant.id, date(2026, 8, 1), date(2026, 9, 1))
        self.assertEqual(segments, [(date(2026, 8, 1), date(2026, 9, 1), 0)])

    def test_bed_added_mid_cycle(self):
        with tenant_context(self.tenant.id):
            _entry(self.tenant.id, BedLedgerEntry.Event.ADDED, date(2026, 8, 15))
            segments = pricing.bed_segments(self.tenant.id, date(2026, 8, 1), date(2026, 9, 1))
        self.assertEqual(segments, [
            (date(2026, 8, 1), date(2026, 8, 15), 0),
            (date(2026, 8, 15), date(2026, 9, 1), 1),
        ])

    def test_bed_removed_mid_cycle_only_billed_for_days_held(self):
        with tenant_context(self.tenant.id):
            _entry(self.tenant.id, BedLedgerEntry.Event.ADDED, date(2026, 7, 20))  # before cycle
            _entry(self.tenant.id, BedLedgerEntry.Event.REMOVED, date(2026, 8, 10))
            segments = pricing.bed_segments(self.tenant.id, date(2026, 8, 1), date(2026, 9, 1))
        self.assertEqual(segments, [
            (date(2026, 8, 1), date(2026, 8, 10), 1),
            (date(2026, 8, 10), date(2026, 9, 1), 0),
        ])

    def test_bed_added_and_removed_within_cycle(self):
        with tenant_context(self.tenant.id):
            _entry(self.tenant.id, BedLedgerEntry.Event.ADDED, date(2026, 8, 5))
            _entry(self.tenant.id, BedLedgerEntry.Event.REMOVED, date(2026, 8, 20))
            segments = pricing.bed_segments(self.tenant.id, date(2026, 8, 1), date(2026, 9, 1))
        self.assertEqual(segments, [
            (date(2026, 8, 1), date(2026, 8, 5), 0),
            (date(2026, 8, 5), date(2026, 8, 20), 1),
            (date(2026, 8, 20), date(2026, 9, 1), 0),
        ])


class ProratedChargeTests(SubscriptionAPITestCase):
    def setUp(self):
        self.tenant = self.create_tenant()
        self.plan = self.create_bed_plan(bed_tiers=[(50, '0.00'), (300, '2.00'), (None, '1.50')])

    def test_beds_added_mid_cycle_charged_only_for_remaining_days(self):
        # 31-day August cycle; 1 bed present from day 1, 99 more join on day
        # 16 (100 total) — the 100-bed rate only applies for the 16 days it
        # was actually true, not the whole cycle.
        cycle_start, cycle_end = date(2026, 8, 1), date(2026, 9, 1)
        with tenant_context(self.tenant.id):
            _entry(self.tenant.id, BedLedgerEntry.Event.ADDED, date(2026, 8, 1))
            for _ in range(99):
                _entry(self.tenant.id, BedLedgerEntry.Event.ADDED, date(2026, 8, 16))
            segments = pricing.bed_segments(self.tenant.id, cycle_start, cycle_end)
            breakdown = pricing.prorated_charge(self.plan, segments, cycle_start, cycle_end)

        full_cycle_at_100 = pricing.monthly_charge(self.plan, 100).total  # 50 free + 50 @ ₹2 = ₹100
        self.assertEqual(full_cycle_at_100, Decimal('100.00'))
        # 1 bed for 15 days is within the free allowance (₹0); 100 beds for
        # the remaining 16 days is charged at 16/31 of the full-cycle rate —
        # strictly less than billing the full cycle at 100 beds throughout.
        expected = ((full_cycle_at_100 * Decimal(16)) / Decimal(31)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.assertEqual(breakdown.total, expected)
        self.assertLess(breakdown.total, full_cycle_at_100)

    def test_segment_crossing_tier_boundary_prices_each_slice_separately(self):
        cycle_start, cycle_end = date(2026, 8, 1), date(2026, 9, 1)  # 31 days
        with tenant_context(self.tenant.id):
            for _ in range(290):
                _entry(self.tenant.id, BedLedgerEntry.Event.ADDED, date(2026, 8, 1))
            for _ in range(20):  # crosses 290 -> 310, straddling the 300-bed tier boundary
                _entry(self.tenant.id, BedLedgerEntry.Event.ADDED, date(2026, 8, 16))
            segments = pricing.bed_segments(self.tenant.id, cycle_start, cycle_end)
            breakdown = pricing.prorated_charge(self.plan, segments, cycle_start, cycle_end)

        # Segment-wise (not averaged): monthly(290)*15/31 + monthly(310)*16/31.
        monthly_290 = pricing.monthly_charge(self.plan, 290).total
        monthly_310 = pricing.monthly_charge(self.plan, 310).total
        expected = ((monthly_290 * Decimal(15) + monthly_310 * Decimal(16)) / Decimal(31)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.assertEqual(breakdown.total, expected)
        # An averaged 300 for the whole month would misprice this — assert it's different.
        averaged_wrong = pricing.monthly_charge(self.plan, 300).total
        self.assertNotEqual(breakdown.total, averaged_wrong)

    def test_28_day_february_cycle(self):
        cycle_start, cycle_end = date(2027, 2, 1), date(2027, 3, 1)
        with tenant_context(self.tenant.id):
            for _ in range(100):
                _entry(self.tenant.id, BedLedgerEntry.Event.ADDED, date(2027, 2, 1))
            segments = pricing.bed_segments(self.tenant.id, cycle_start, cycle_end)
            breakdown = pricing.prorated_charge(self.plan, segments, cycle_start, cycle_end)
        # Full cycle, single segment, 100 beds -> same as monthly_charge(100).
        self.assertEqual(breakdown.total, pricing.monthly_charge(self.plan, 100).total)

    def test_rounds_once_on_final_sum(self):
        cycle_start, cycle_end = date(2026, 8, 1), date(2026, 9, 1)
        with tenant_context(self.tenant.id):
            for _ in range(275):
                _entry(self.tenant.id, BedLedgerEntry.Event.ADDED, date(2026, 8, 1))
            segments = pricing.bed_segments(self.tenant.id, cycle_start, cycle_end)
            breakdown = pricing.prorated_charge(self.plan, segments, cycle_start, cycle_end)
        self.assertIsInstance(breakdown.total, Decimal)
        self.assertEqual(breakdown.total, breakdown.total.quantize(Decimal('0.01')))


class BedLedgerSignalTests(SubscriptionAPITestCase):
    """Confirms the `Bed` post_save/post_delete signals actually feed the
    ledger — the piece `BedSegmentsTests` deliberately bypasses."""

    def test_creating_a_bed_writes_an_added_entry(self):
        tenant = self.create_tenant()
        prop = self.create_property(tenant)
        floor = self.create_floor(prop)
        room = self.create_room(floor)
        bed = self.create_bed(room)

        with tenant_context(tenant.id):
            entries = list(BedLedgerEntry.objects.filter(bed_id=bed.id))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].event, BedLedgerEntry.Event.ADDED)

    def test_deleting_a_bed_writes_a_removed_entry(self):
        tenant = self.create_tenant()
        prop = self.create_property(tenant)
        floor = self.create_floor(prop)
        room = self.create_room(floor)
        bed = self.create_bed(room)
        bed_id = bed.id

        with tenant_context(tenant.id):
            bed.delete()
            events = list(
                BedLedgerEntry.objects.filter(bed_id=bed_id).order_by('occurred_at').values_list('event', flat=True)
            )
        self.assertEqual(events, [BedLedgerEntry.Event.ADDED, BedLedgerEntry.Event.REMOVED])
