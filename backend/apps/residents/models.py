import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModelMixin
from apps.properties.models import Bed, Property, Room


def resident_document_path(instance, filename):
    return f'residents/{instance.tenant_id}/{instance.id}/{filename}'


class Resident(TenantModelMixin):
    """A resident/lead profile (PRD Module 5), scoped to the property they
    inquired about or live in. Admission workflow and bed allocation are
    later modules (05/06) — this is just the profile + status lifecycle.
    No linked login (User) account yet; see Decisions."""

    class Gender(models.TextChoices):
        MALE = 'male', _('Male')
        FEMALE = 'female', _('Female')
        OTHER = 'other', _('Other')

    class Status(models.TextChoices):
        INQUIRY = 'inquiry', _('Inquiry')
        RESERVED = 'reserved', _('Reserved')
        ACTIVE = 'active', _('Active')
        NOTICE_PERIOD = 'notice_period', _('Notice Period')
        VACATED = 'vacated', _('Vacated')
        ABSCONDED = 'absconded', _('Absconded')
        BLACKLISTED = 'blacklisted', _('Blacklisted')

    # PRD Module 5 status-lifecycle diagram — exact edges (invariant 8).
    # Inquiry -> Reserved -> Active -> Notice Period -> Vacated
    #                                ↘ Blacklisted (from Notice Period)
    #                      Active -> Absconded -> Blacklisted
    TRANSITIONS = {
        Status.INQUIRY: {Status.RESERVED},
        Status.RESERVED: {Status.ACTIVE},
        Status.ACTIVE: {Status.NOTICE_PERIOD, Status.ABSCONDED},
        Status.NOTICE_PERIOD: {Status.VACATED, Status.BLACKLISTED},
        Status.ABSCONDED: {Status.BLACKLISTED},
        Status.VACATED: set(),
        Status.BLACKLISTED: set(),
    }

    # Only these statuses count toward a tenant's plan resident limit
    # (invariant 8). The cap itself is Module 13's concern — no Plan model
    # exists yet, so nothing enforces it here.
    COUNTS_TOWARD_PLAN_LIMIT = (Status.ACTIVE, Status.NOTICE_PERIOD)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name='residents')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INQUIRY)

    # Personal information
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=10, choices=Gender.choices, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=15)
    email = models.EmailField(blank=True)

    # Address information
    permanent_address = models.TextField(blank=True)
    current_address = models.TextField(blank=True)

    # Emergency contact
    emergency_contact_name = models.CharField(max_length=200, blank=True)
    emergency_contact_relation = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=15, blank=True)

    # Identity documents — Aadhaar/PAN carry both a number and an upload;
    # Passport/Employee ID/Student ID are optional numbers only (PRD Module 5).
    aadhaar_number = models.CharField(max_length=20, blank=True)
    aadhaar_document = models.FileField(upload_to=resident_document_path, null=True, blank=True)
    pan_number = models.CharField(max_length=20, blank=True)
    pan_document = models.FileField(upload_to=resident_document_path, null=True, blank=True)
    passport_number = models.CharField(max_length=30, blank=True)
    employee_id = models.CharField(max_length=50, blank=True)
    student_id = models.CharField(max_length=50, blank=True)

    class Meta:
        db_table = 'residents'

    def __str__(self):
        return f'{self.first_name} {self.last_name}'.strip()

    def can_transition_to(self, new_status):
        return new_status in self.TRANSITIONS.get(self.status, set())


class Admission(TenantModelMixin):
    """The admission event (PRD Module 6): captures the deal terms agreed
    at joining and performs Check-In (bed occupied, resident -> Active).
    One row per resident — re-admission after Vacated/Blacklisted is a new
    Resident record, not a second Admission. Immutable once created: no
    update/delete endpoint, matching invariant 2 (contracted terms are
    snapshotted, never recomputed from the room/bed)."""

    class BillingMode(models.TextChoices):
        MONTHLY = 'monthly', _('Monthly')
        WEEKLY = 'weekly', _('Weekly')
        DAILY = 'daily', _('Daily')

    class FoodPreference(models.TextChoices):
        WITH_FOOD = 'with_food', _('With Food')
        WITHOUT_FOOD = 'without_food', _('Without Food')

    class AdvanceMode(models.TextChoices):
        UPI = 'upi', _('UPI')
        CASH = 'cash', _('Cash')
        BANK_TRANSFER = 'bank_transfer', _('Bank Transfer')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resident = models.OneToOneField(Resident, on_delete=models.PROTECT, related_name='admission')
    bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name='admissions')

    joining_date = models.DateField()
    billing_mode = models.CharField(max_length=10, choices=BillingMode.choices)
    expected_stay_duration = models.CharField(max_length=50, blank=True)  # free text, e.g. "6 months"

    # Snapshotted from bed/room at admission time — invariant 2/3: never
    # recomputed later even if the room's rack rates or category change.
    contracted_sharing_type = models.PositiveSmallIntegerField(choices=Room.SharingType.choices)
    contracted_room_category = models.CharField(max_length=10, choices=Room.Category.choices)
    food_preference = models.CharField(max_length=15, choices=FoodPreference.choices)
    contracted_rent = models.DecimalField(max_digits=12, decimal_places=2)

    advance_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    # Added by Module 10 (Security Deposit & Advance Management) — advance_amount
    # already existed (snapshotted at admission); these two siblings complete the
    # PRD's `advance_amount`/`advance_collected_date`/`advance_mode` trio.
    advance_collected_date = models.DateField(null=True, blank=True)
    advance_mode = models.CharField(max_length=15, choices=AdvanceMode.choices, blank=True)
    # Partial first-month adjustment set manually by management (PRD: "amount
    # set manually") — null means bill the first month at the normal
    # contracted_rent; Module 08 (Billing) is what actually reads this.
    first_month_billing_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    first_month_billing_note = models.TextField(blank=True)

    # Reserved for future per-resident add-on services (diet food, gym, etc.).
    # Mandated empty ([]) in MVP by invariant 6 / PRD Module 9 "Future-Proofing"
    # so add-ons can be populated later without a schema migration; the Module
    # 08 invoice engine already iterates a line-item list, so a future add-on
    # simply becomes another line item.
    addons = models.JSONField(default=list, blank=True)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='admissions_recorded'
    )

    class Meta:
        db_table = 'admissions'

    def __str__(self):
        return f'Admission: {self.resident}'


class Allocation(TenantModelMixin):
    """The resident's CURRENT physical bed placement (PRD Module 7). Created
    at check-in (Module 05) mirroring the admitted bed, then mutated by
    transfers. Distinct from Admission (the immutable original deal): this
    row tracks where the resident physically is *right now* and whether that
    placement is temporary.

    Invariant 2/3: `contracted_rent` is always the billing baseline —
    unchanged by a temporary allocation (resident stays billed at their
    contracted rent regardless of the physical room), updated only by a
    permanent transfer. `actual_*` (the physical room's type/category) is
    derived from the bed, never stored, so it can't drift."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resident = models.OneToOneField(Resident, on_delete=models.PROTECT, related_name='allocation')
    allocated_bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name='allocations')

    # The contracted deal — copied from Admission at check-in, changed only
    # by a permanent transfer. Never auto-recomputed from the room.
    contracted_sharing_type = models.PositiveSmallIntegerField(choices=Room.SharingType.choices)
    contracted_room_category = models.CharField(max_length=10, choices=Room.Category.choices)
    contracted_rent = models.DecimalField(max_digits=12, decimal_places=2)

    is_temporary = models.BooleanField(default=False)
    temporary_since = models.DateField(null=True, blank=True)
    expected_move_date = models.DateField(null=True, blank=True)
    temporary_note = models.TextField(blank=True)

    class Meta:
        db_table = 'allocations'

    def __str__(self):
        return f'Allocation: {self.resident} -> {self.allocated_bed}'

    @property
    def actual_sharing_type(self):
        return self.allocated_bed.room.sharing_type

    @property
    def actual_room_category(self):
        return self.allocated_bed.room.category


class Transfer(TenantModelMixin):
    """Append-only history of a resident moving beds/rooms (PRD Module 7
    'Transfer Management'). Each transfer mutates the resident's Allocation
    and freezes the before/after here, including the `rent_effective_date`
    computed from the property's Module 2B 'Room Transfer Rent Timing'
    setting."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resident = models.ForeignKey(Resident, on_delete=models.PROTECT, related_name='transfers')
    previous_bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name='transfers_from')
    new_bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name='transfers_to')
    # True = temporary placement (contracted_rent unchanged); False = permanent
    # move that becomes the resident's new contracted arrangement.
    is_temporary = models.BooleanField(default=False)
    reason = models.TextField(blank=True)
    transfer_date = models.DateField()
    previous_rent = models.DecimalField(max_digits=12, decimal_places=2)
    new_rent = models.DecimalField(max_digits=12, decimal_places=2)
    rent_effective_date = models.DateField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='transfers_recorded'
    )

    class Meta:
        db_table = 'transfers'
        ordering = ['-transfer_date', '-created_at']

    def __str__(self):
        return f'Transfer: {self.resident} ({self.previous_bed} -> {self.new_bed})'


class Vacate(TenantModelMixin):
    """Notice-to-vacate + move-out settlement (PRD Module 11 'Vacating
    Workflow'). One row per resident: created when notice is given
    (Active -> Notice Period), then completed at move-out
    (Notice Period -> Vacated) with the maintenance deduction and advance
    refund. `refund_amount` is computed from the admission's advance_amount,
    never stored, so it can't drift if the deduction is corrected before
    settlement."""

    class RefundMode(models.TextChoices):
        UPI = 'upi', _('UPI')
        CASH = 'cash', _('Cash')
        BANK_TRANSFER = 'bank_transfer', _('Bank Transfer')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resident = models.OneToOneField(Resident, on_delete=models.PROTECT, related_name='vacate')

    notice_given_date = models.DateField()
    # notice_given_date + 1 month (PRD 'Standard notice period: 1 month').
    expected_vacate_date = models.DateField()
    actual_vacate_date = models.DateField(null=True, blank=True)  # set when settlement is finalized

    maintenance_deduction = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    maintenance_deduction_note = models.TextField(blank=True)

    refund_date = models.DateField(null=True, blank=True)
    refund_mode = models.CharField(max_length=15, choices=RefundMode.choices, blank=True)
    refund_note = models.TextField(blank=True)

    settled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='vacates_settled'
    )

    class Meta:
        db_table = 'vacates'

    def __str__(self):
        return f'Vacate: {self.resident}'

    @property
    def is_settled(self):
        return self.actual_vacate_date is not None

    @property
    def refund_amount(self):
        if self.maintenance_deduction is None:
            return None
        return self.resident.admission.advance_amount - self.maintenance_deduction


class AbscondedRecord(TenantModelMixin):
    """A resident who left without notice, without settling dues, and without
    returning access (PRD Module 11 'Absconded Resident Workflow') — distinct
    from a normal vacate. The bed is freed immediately on marking (not on a
    future vacate date), and the advance is forfeited and applied against
    outstanding dues rather than refunded. `advance_applied_to_dues` and
    `remaining_dues` are snapshotted at marking time — a settled financial
    event, not recomputed later even if the resident's invoices change."""

    class DuesRecoveryStatus(models.TextChoices):
        OUTSTANDING = 'outstanding', _('Outstanding')
        PARTIALLY_RECOVERED = 'partially_recovered', _('Partially Recovered')
        WRITTEN_OFF = 'written_off', _('Written Off')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resident = models.OneToOneField(Resident, on_delete=models.PROTECT, related_name='absconded_record')

    absconded_date = models.DateField()
    last_seen_date = models.DateField(null=True, blank=True)
    absconded_note = models.TextField(blank=True)

    # The advance is always forfeited per the PRD workflow (no partial-forfeit
    # option is described) — the field is kept for parity with the PRD's
    # explicit field list and to make the outcome an explicit, queryable fact.
    advance_forfeited = models.BooleanField(default=True)
    advance_applied_to_dues = models.DecimalField(max_digits=12, decimal_places=2)
    remaining_dues = models.DecimalField(max_digits=12, decimal_places=2)

    dues_recovery_status = models.CharField(
        max_length=20, choices=DuesRecoveryStatus.choices, default=DuesRecoveryStatus.OUTSTANDING
    )
    dues_written_off_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='dues_written_off'
    )
    dues_written_off_note = models.TextField(blank=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='absconded_records_marked'
    )

    class Meta:
        db_table = 'absconded_records'

    def __str__(self):
        return f'Absconded: {self.resident}'


class BlacklistEntry(TenantModelMixin):
    """Tenant-wide blacklist (PRD Module 11 'Blacklisting') — visible across
    every property under the tenant, not just the property the resident lived
    in, so a Manager registering a new resident anywhere in the tenant is
    warned. Phone/Aadhaar are snapshotted at blacklisting time so the check
    still works even if the resident's profile is edited later."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resident = models.OneToOneField(Resident, on_delete=models.PROTECT, related_name='blacklist_entry')
    phone = models.CharField(max_length=15)
    aadhaar_number = models.CharField(max_length=20, blank=True)
    reason = models.TextField(blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='blacklist_entries_confirmed'
    )

    class Meta:
        db_table = 'blacklist_entries'

    def __str__(self):
        return f'Blacklisted: {self.phone}'
