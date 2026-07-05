import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModelMixin


class Property(TenantModelMixin):
    """Root of the Property -> Building -> Floor -> Room -> Bed hierarchy (PRD Module 2)."""

    class PropertyType(models.TextChoices):
        BOYS_HOSTEL = 'boys_hostel', _('Boys Hostel')
        GIRLS_HOSTEL = 'girls_hostel', _('Girls Hostel')
        PG = 'pg', _('PG')
        CO_LIVING = 'co_living', _('Co-Living Space')

    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        INACTIVE = 'inactive', _('Inactive')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    property_type = models.CharField(max_length=20, choices=PropertyType.choices)
    address_line = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    country = models.CharField(max_length=100, default='India')
    contact_number = models.CharField(max_length=15)
    contact_email = models.EmailField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        db_table = 'properties'

    def __str__(self):
        return self.name


def property_image_path(instance, filename):
    return f'properties/{instance.property.tenant_id}/{instance.property_id}/{filename}'


class PropertyImage(TenantModelMixin):
    """A gallery photo for a Property (PRD Module 2 property listing)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to=property_image_path)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'property_images'
        ordering = ['order', 'created_at']

    def __str__(self):
        return f'{self.property.name} - image {self.order}'


class Building(TenantModelMixin):
    """A building/block within a property (PRD Module 2). Most properties
    have exactly one (auto-created as "Main Building" when the Property is
    created — see PropertyViewSet.perform_create); owners whose PG spans
    multiple physical buildings (e.g. "Block A", "Block B") add more."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='buildings')
    name = models.CharField(max_length=100)  # e.g. "Main Building", "Block A"
    order = models.PositiveSmallIntegerField()  # display/sort order

    class Meta:
        db_table = 'buildings'
        constraints = [
            models.UniqueConstraint(fields=['property', 'order'], name='unique_building_order_per_property'),
        ]
        ordering = ['order']

    def __str__(self):
        return f'{self.property.name} - {self.name}'


class Floor(TenantModelMixin):
    """A floor within a building. Purely structural — no money fields."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='floors')
    name = models.CharField(max_length=100)  # e.g. "Ground Floor", "1st Floor"
    order = models.PositiveSmallIntegerField()  # display/sort order, e.g. 0 for ground

    class Meta:
        db_table = 'floors'
        constraints = [
            models.UniqueConstraint(fields=['building', 'order'], name='unique_floor_order_per_building'),
        ]
        ordering = ['order']

    def __str__(self):
        return f'{self.building.property.name} - {self.building.name} - {self.name}'


class Room(TenantModelMixin):
    """A room on a floor. Rack rates here are the default for its beds
    (invariant 2/3: never the billing baseline — contracted_rent snapshots
    a rack rate at admission time and is never recomputed from this row)."""

    class SharingType(models.IntegerChoices):
        ONE = 1, _('1-sharing')
        TWO = 2, _('2-sharing')
        THREE = 3, _('3-sharing')
        FOUR = 4, _('4-sharing')

    class Category(models.TextChoices):
        AC = 'ac', _('AC')
        NON_AC = 'non_ac', _('Non-AC')

    class Status(models.TextChoices):
        AVAILABLE = 'available', _('Available')
        OCCUPIED = 'occupied', _('Occupied')
        RESERVED = 'reserved', _('Reserved')
        MAINTENANCE = 'maintenance', _('Maintenance')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    floor = models.ForeignKey(Floor, on_delete=models.CASCADE, related_name='rooms')
    room_number = models.CharField(max_length=20)
    sharing_type = models.PositiveSmallIntegerField(choices=SharingType.choices)
    category = models.CharField(max_length=10, choices=Category.choices)
    rack_rate_with_food = models.DecimalField(max_digits=12, decimal_places=2)
    rack_rate_without_food = models.DecimalField(max_digits=12, decimal_places=2)
    # Occupied/Reserved are derived from bed statuses (see sync_status);
    # Maintenance is a manual override that sync_status will not clear.
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.AVAILABLE)

    class Meta:
        db_table = 'rooms'
        constraints = [
            models.UniqueConstraint(fields=['floor', 'room_number'], name='unique_room_number_per_floor'),
        ]
        ordering = ['room_number']

    def __str__(self):
        return f'{self.floor.building.property.name} - {self.room_number}'

    def sync_status(self):
        """Recompute status from child beds (PRD Module 3 room status rules).
        A manually-set Maintenance status is a deliberate override and is left
        alone until management clears it."""
        if self.status == self.Status.MAINTENANCE:
            return
        statuses = list(self.beds.values_list('status', flat=True))
        if not statuses:
            new_status = self.Status.AVAILABLE
        elif all(s == Bed.Status.OCCUPIED for s in statuses):
            new_status = self.Status.OCCUPIED
        elif any(s == Bed.Status.AVAILABLE for s in statuses):
            new_status = self.Status.AVAILABLE
        else:
            new_status = self.Status.RESERVED
        if new_status != self.status:
            self.status = new_status
            self.save(update_fields=['status', 'updated_at'])


class Bed(TenantModelMixin):
    """A bed within a room. Rack rates default to the room's; management can
    override per bed for edge cases (PRD Module 4)."""

    class Status(models.TextChoices):
        AVAILABLE = 'available', _('Available')
        OCCUPIED = 'occupied', _('Occupied')
        RESERVED = 'reserved', _('Reserved')
        MAINTENANCE = 'maintenance', _('Maintenance')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='beds')
    bed_number = models.CharField(max_length=20)  # e.g. "201-A"
    rack_rate_with_food_override = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    rack_rate_without_food_override = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.AVAILABLE)

    class Meta:
        db_table = 'beds'
        constraints = [
            models.UniqueConstraint(fields=['room', 'bed_number'], name='unique_bed_number_per_room'),
        ]
        ordering = ['bed_number']

    def __str__(self):
        return f'{self.room.room_number} - {self.bed_number}'

    def rack_rate(self, with_food):
        if with_food:
            return self.rack_rate_with_food_override or self.room.rack_rate_with_food
        return self.rack_rate_without_food_override or self.room.rack_rate_without_food

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.room.sync_status()

    def delete(self, *args, **kwargs):
        room = self.room
        super().delete(*args, **kwargs)
        room.sync_status()


class PropertyStaffAssignment(TenantModelMixin):
    """Explicit Manager/Receptionist -> Property assignment (PRD §6 'Property
    Assignment Rules'). Owner has implicit access to all tenant properties and
    is never assigned. Removing a row revokes access without deleting the
    staff account."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='property_assignments'
    )
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='staff_assignments')

    class Meta:
        db_table = 'property_staff_assignments'
        constraints = [
            models.UniqueConstraint(fields=['staff', 'property'], name='unique_staff_property_assignment'),
        ]

    def __str__(self):
        return f'{self.staff.email} -> {self.property.name}'


class PropertySettings(TenantModelMixin):
    """Per-property billing/transfer behaviour (PRD Module 2B). Exactly one
    row per property, lazily created with PRD defaults on first access
    (see PropertyViewSet.settings). 'Shared Invoices' (PRD Setting 2) has no
    field here — it's a fixed rule (always one invoice per resident),
    enforced by Module 08's design rather than a toggle."""

    class RentChangeTiming(models.TextChoices):
        IMMEDIATE = 'immediate', _('Immediately')
        NEXT_BILLING_CYCLE = 'next_billing_cycle', _('Next Billing Cycle')

    class PenaltyType(models.TextChoices):
        NONE = 'none', _('No Penalty')
        FIXED = 'fixed', _('Fixed Amount')
        PERCENTAGE = 'percentage', _('Percentage')

    class PenaltyAppliesTo(models.TextChoices):
        FULL_INVOICE = 'full_invoice', _('Full Invoice Amount')
        OUTSTANDING_BALANCE = 'outstanding_balance', _('Outstanding Balance Only')

    class PenaltyCompounding(models.TextChoices):
        ONE_TIME = 'one_time', _('One-time')
        MONTHLY = 'monthly', _('Monthly')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.OneToOneField(Property, on_delete=models.CASCADE, related_name='settings')
    room_transfer_rent_timing = models.CharField(
        max_length=20, choices=RentChangeTiming.choices, default=RentChangeTiming.NEXT_BILLING_CYCLE
    )
    late_payment_penalty_type = models.CharField(
        max_length=10, choices=PenaltyType.choices, default=PenaltyType.NONE
    )
    # Fixed ₹ amount or % value depending on late_payment_penalty_type; null
    # when penalty type is NONE.
    penalty_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    penalty_grace_days = models.PositiveSmallIntegerField(
        default=5, validators=[MaxValueValidator(30)]
    )
    penalty_applies_to = models.CharField(
        max_length=20, choices=PenaltyAppliesTo.choices, default=PenaltyAppliesTo.FULL_INVOICE
    )
    penalty_compounding = models.CharField(
        max_length=10, choices=PenaltyCompounding.choices, default=PenaltyCompounding.ONE_TIME
    )

    class Meta:
        db_table = 'property_settings'

    def __str__(self):
        return f'Settings for {self.property.name}'
