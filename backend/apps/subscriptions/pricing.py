"""Pure pricing calculations for PER_BED_MONTHLY plans (PRD §4, Google-
Workspace-style per-bed billing). Deliberately separate from `services.py`:
no DB writes, no Razorpay calls — every function here takes plain values in
and returns plain values out, so the whole engine is unit-testable without a
database.

Money is always `Decimal` (invariant 5); a single `ROUND_HALF_UP` to 2dp is
applied once, at the very end of a calculation — never per intermediate step,
which would compound rounding error across tiers/segments.
"""
import calendar
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal


@dataclass
class TierLine:
    up_to_beds: int | None
    rate_per_bed: Decimal
    beds_in_tier: int
    subtotal: Decimal


@dataclass
class PriceBreakdown:
    """Full-cycle (unprorated) charge for a single bed count."""
    bed_count: int
    tier_lines: list[TierLine] = field(default_factory=list)
    total: Decimal = Decimal('0.00')


@dataclass
class SegmentCharge:
    """A constant-bed-count slice of a billing cycle, priced at that bed
    count's full tier breakdown, then scaled by the fraction of the cycle
    it covers. `tier_lines`/`unprorated_total` are the full-month amounts —
    keeping them alongside the prorated `amount` is what lets the invoice
    generator show "300 beds @ ₹2 for 15/31 days" rather than a single
    opaque number."""
    start: object
    end: object
    bed_count: int
    tier_lines: list[TierLine]
    unprorated_total: Decimal
    amount: Decimal


@dataclass
class ProratedBreakdown:
    segments: list[SegmentCharge] = field(default_factory=list)
    total: Decimal = Decimal('0.00')


def _quantize(amount):
    return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def next_cycle_end(cycle_start):
    """Calendar-month-out from `cycle_start` (28/29/30/31-day aware), not a
    hardcoded `timedelta(days=30)` — a bed held the whole of February must
    only be charged for February's days, not 30."""
    month = cycle_start.month + 1
    year = cycle_start.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(cycle_start.day, calendar.monthrange(year, month)[1])
    return cycle_start.replace(year=year, month=month, day=day)


def monthly_charge(plan, bed_count):
    """Full-cycle charge for `bed_count` beds against `plan`'s bed-tier
    ladder, applied marginally (every bed is charged at the rate of the
    tier it falls into, like income tax slabs — not "which bracket are you
    in"). `plan.bed_tiers` must be ordered ascending with exactly one
    open-ended (`up_to_beds=None`) top tier — see `PlanBedTier`."""
    if bed_count < 0:
        raise ValueError('bed_count cannot be negative')

    tiers = list(plan.bed_tiers.all())
    lines = []
    total = Decimal('0')
    floor = 0
    remaining = bed_count

    for tier in tiers:
        if remaining <= 0:
            break
        ceiling = tier.up_to_beds
        tier_capacity = (ceiling - floor) if ceiling is not None else remaining
        beds_in_tier = min(remaining, tier_capacity)
        if beds_in_tier > 0:
            subtotal = tier.rate_per_bed * beds_in_tier
            lines.append(TierLine(
                up_to_beds=ceiling, rate_per_bed=tier.rate_per_bed,
                beds_in_tier=beds_in_tier, subtotal=subtotal,
            ))
            total += subtotal
            remaining -= beds_in_tier
        floor = ceiling if ceiling is not None else floor

    return PriceBreakdown(bed_count=bed_count, tier_lines=lines, total=_quantize(total))


def bed_segments(tenant_id, start, end):
    """Replays `BedLedgerEntry` rows into `[(from_date, to_date, bed_count)]`
    constant-count segments covering `[start, end)`. Deferred import keeps
    this otherwise-pure module free of an ORM/DB dependency at import time."""
    from .models import BedLedgerEntry

    entries = list(
        BedLedgerEntry.objects.filter(
            tenant_id=tenant_id, occurred_at__date__lt=end,
        ).order_by('occurred_at')
    )

    # Bed count at the moment `start` opens: every ADDED before start, minus
    # every REMOVED before start.
    count = 0
    for entry in entries:
        if entry.occurred_at.date() >= start:
            break
        count += 1 if entry.event == BedLedgerEntry.Event.ADDED else -1

    segments = []
    cursor = start
    running = count
    for entry in entries:
        entry_date = entry.occurred_at.date()
        if entry_date < start:
            continue
        if entry_date >= end:
            break
        if entry_date > cursor:
            segments.append((cursor, entry_date, running))
            cursor = entry_date
        running += 1 if entry.event == BedLedgerEntry.Event.ADDED else -1

    if cursor < end:
        segments.append((cursor, end, running))

    return segments


def prorated_charge(plan, segments, cycle_start, cycle_end):
    """Prorated charge for a billing cycle made of constant-bed-count
    `segments` (from `bed_segments`). Each segment is priced at its own bed
    count's full-cycle tier breakdown, then scaled by the fraction of the
    cycle it covers — the correct interaction with tiers: a cycle with 290
    beds for half the month and 310 for the other half is
    `monthly(290)*0.5 + monthly(310)*0.5`, which an averaged 300 would
    misprice.

    Rounds once, on the final sum — never per segment, so rounding error
    can't compound across a month with many bed changes."""
    cycle_days = (cycle_end - cycle_start).days
    if cycle_days <= 0:
        raise ValueError('cycle_end must be after cycle_start')

    segment_charges = []
    raw_total = Decimal('0')

    for seg_start, seg_end, bed_count in segments:
        seg_days = (seg_end - seg_start).days
        if seg_days <= 0:
            continue
        breakdown = monthly_charge(plan, bed_count)
        seg_amount = breakdown.total * seg_days / cycle_days
        raw_total += seg_amount
        segment_charges.append(SegmentCharge(
            start=seg_start, end=seg_end, bed_count=bed_count,
            tier_lines=breakdown.tier_lines, unprorated_total=breakdown.total,
            amount=seg_amount,
        ))

    return ProratedBreakdown(segments=segment_charges, total=_quantize(raw_total))
