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
    # Partial first-month adjustment set manually by management (PRD: "amount
    # set manually") — null means bill the first month at the normal
    # contracted_rent; Module 08 (Billing) is what actually reads this.
    first_month_billing_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    first_month_billing_note = models.TextField(blank=True)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='admissions_recorded'
    )

    class Meta:
        db_table = 'admissions'

    def __str__(self):
        return f'Admission: {self.resident}'
