from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.properties.models import Bed
from apps.properties.services import can_view_property

from .models import (
    AbscondedRecord,
    Admission,
    Allocation,
    BlacklistEntry,
    Resident,
    Transfer,
    Vacate,
)


class ResidentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resident
        fields = [
            'id', 'property', 'status',
            'first_name', 'last_name', 'gender', 'date_of_birth', 'phone', 'email',
            'permanent_address', 'current_address',
            'emergency_contact_name', 'emergency_contact_relation', 'emergency_contact_phone',
            'aadhaar_number', 'aadhaar_document', 'pan_number', 'pan_document',
            'passport_number', 'employee_id', 'student_id',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'status', 'created_at', 'updated_at']

    def validate_property(self, value):
        request = self.context['request']
        if not can_view_property(request.user, value.pk):
            raise serializers.ValidationError(
                _('You are not assigned to this property.'), code='property_not_assigned'
            )
        return value


class ResidentStatusUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resident
        fields = ['status']

    def validate_status(self, value):
        if not self.instance.can_transition_to(value):
            raise serializers.ValidationError(
                _('Cannot move a resident from %(current)s to %(new)s.') % {
                    'current': self.instance.get_status_display(),
                    'new': value,
                },
                code='invalid_status_transition',
            )
        return value


class AdmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Admission
        fields = [
            'id', 'resident', 'bed', 'joining_date', 'billing_mode', 'expected_stay_duration',
            'contracted_sharing_type', 'contracted_room_category', 'food_preference', 'contracted_rent',
            'advance_amount', 'advance_collected_date', 'advance_mode',
            'first_month_billing_amount', 'first_month_billing_note',
            'recorded_by', 'created_at', 'updated_at',
        ]
        # contracted_* fields are snapshotted server-side in the view
        # (invariant 2/3) — never accepted as client input.
        read_only_fields = [
            'id', 'contracted_sharing_type', 'contracted_room_category', 'contracted_rent',
            'recorded_by', 'created_at', 'updated_at',
        ]

    def validate(self, attrs):
        resident = attrs['resident']
        bed = attrs['bed']

        if not resident.can_transition_to(Resident.Status.ACTIVE):
            raise serializers.ValidationError(
                {'resident': _(
                    'This resident is not ready for check-in — they must be Reserved first.'
                )},
                code='resident_not_ready_for_checkin',
            )
        if bed.room.floor.property_id != resident.property_id:
            raise serializers.ValidationError(
                {'bed': _('This bed is not in the same property as the resident.')},
                code='bed_property_mismatch',
            )
        if bed.status != Bed.Status.AVAILABLE:
            raise serializers.ValidationError(
                {'bed': _('This bed is not available.')},
                code='bed_not_available',
            )

        request = self.context['request']
        if not can_view_property(request.user, resident.property_id):
            raise serializers.ValidationError(
                {'resident': _('You are not assigned to this property.')},
                code='property_not_assigned',
            )
        return attrs


class AllocationSerializer(serializers.ModelSerializer):
    # Derived from the current bed's room (never stored — can't drift).
    actual_sharing_type = serializers.IntegerField(read_only=True)
    actual_room_category = serializers.CharField(read_only=True)

    class Meta:
        model = Allocation
        fields = [
            'id', 'resident', 'allocated_bed',
            'contracted_sharing_type', 'contracted_room_category', 'contracted_rent',
            'actual_sharing_type', 'actual_room_category',
            'is_temporary', 'temporary_since', 'expected_move_date', 'temporary_note',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields


class TransferSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transfer
        fields = [
            'id', 'resident', 'previous_bed', 'new_bed', 'is_temporary', 'reason',
            'transfer_date', 'previous_rent', 'new_rent', 'rent_effective_date',
            'recorded_by', 'created_at',
        ]
        read_only_fields = fields


class TransferCreateSerializer(serializers.Serializer):
    """Performs a transfer (PRD Module 7). `new_rent` applies only to a
    permanent transfer (`is_temporary=False`) and defaults to the new bed's
    rack rate; a temporary transfer keeps the contracted rent untouched."""

    resident = serializers.PrimaryKeyRelatedField(queryset=Resident.objects.all())
    new_bed = serializers.PrimaryKeyRelatedField(queryset=Bed.objects.all())
    transfer_date = serializers.DateField()
    is_temporary = serializers.BooleanField(default=False)
    reason = serializers.CharField(required=False, allow_blank=True, default='')
    new_rent = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, default=None
    )
    expected_move_date = serializers.DateField(required=False, allow_null=True, default=None)
    temporary_note = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        request = self.context['request']
        resident = attrs['resident']
        new_bed = attrs['new_bed']

        if not can_view_property(request.user, resident.property_id):
            raise serializers.ValidationError(
                {'resident': _('You are not assigned to this property.')},
                code='property_not_assigned',
            )

        allocation = Allocation.objects.filter(resident=resident).first()
        if allocation is None:
            raise serializers.ValidationError(
                {'resident': _('This resident is not currently allocated to a bed.')},
                code='resident_not_allocated',
            )
        if resident.status not in (Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD):
            raise serializers.ValidationError(
                {'resident': _('Only active residents can be transferred.')},
                code='resident_not_transferable',
            )
        if new_bed.room.floor.property_id != resident.property_id:
            raise serializers.ValidationError(
                {'new_bed': _('This bed is not in the same property as the resident.')},
                code='bed_property_mismatch',
            )
        if new_bed.id == allocation.allocated_bed_id:
            raise serializers.ValidationError(
                {'new_bed': _('The resident is already in this bed.')},
                code='same_bed',
            )
        if new_bed.status != Bed.Status.AVAILABLE:
            raise serializers.ValidationError(
                {'new_bed': _('This bed is not available.')},
                code='bed_not_available',
            )

        attrs['allocation'] = allocation
        return attrs


class VacateSerializer(serializers.ModelSerializer):
    refund_amount = serializers.SerializerMethodField()
    is_settled = serializers.BooleanField(read_only=True)

    class Meta:
        model = Vacate
        fields = [
            'id', 'resident', 'notice_given_date', 'expected_vacate_date', 'actual_vacate_date',
            'maintenance_deduction', 'maintenance_deduction_note',
            'refund_date', 'refund_mode', 'refund_note', 'refund_amount', 'is_settled',
            'settled_by', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_refund_amount(self, obj) -> str | None:
        amount = obj.refund_amount
        return str(amount) if amount is not None else None


class VacateGiveNoticeSerializer(serializers.Serializer):
    """Step 1 of the vacating workflow (PRD Module 11): resident gives notice."""

    resident = serializers.PrimaryKeyRelatedField(queryset=Resident.objects.all())
    notice_given_date = serializers.DateField()

    def validate(self, attrs):
        request = self.context['request']
        resident = attrs['resident']
        if not can_view_property(request.user, resident.property_id):
            raise serializers.ValidationError(
                {'resident': _('You are not assigned to this property.')}, code='property_not_assigned',
            )
        if not resident.can_transition_to(Resident.Status.NOTICE_PERIOD):
            raise serializers.ValidationError(
                {'resident': _('Only an active resident can give notice to vacate.')},
                code='resident_not_active',
            )
        if Vacate.objects.filter(resident=resident).exists():
            raise serializers.ValidationError(
                {'resident': _('This resident already has a vacate record.')},
                code='vacate_already_exists',
            )
        return attrs


class VacateFinalizeSerializer(serializers.Serializer):
    """Step 2 of the vacating workflow (PRD Module 11): the move-out
    settlement — maintenance deduction and advance refund."""

    actual_vacate_date = serializers.DateField()
    maintenance_deduction = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )
    maintenance_deduction_note = serializers.CharField(required=False, allow_blank=True, default='')
    refund_date = serializers.DateField(required=False, allow_null=True, default=None)
    refund_mode = serializers.ChoiceField(
        choices=Vacate.RefundMode.choices, required=False, allow_blank=True, default=''
    )
    refund_note = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_maintenance_deduction(self, value):
        if value < 0:
            raise serializers.ValidationError(_('Deduction cannot be negative.'), code='invalid_deduction')
        return value

    def validate(self, attrs):
        vacate = self.context['vacate']
        advance = vacate.resident.admission.advance_amount
        if attrs['maintenance_deduction'] > advance:
            raise serializers.ValidationError(
                {'maintenance_deduction': _(
                    'Deduction cannot exceed the advance amount of %(advance)s.'
                ) % {'advance': advance}},
                code='deduction_exceeds_advance',
            )
        return attrs


class AbscondedRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AbscondedRecord
        fields = [
            'id', 'resident', 'absconded_date', 'last_seen_date', 'absconded_note',
            'advance_forfeited', 'advance_applied_to_dues', 'remaining_dues',
            'dues_recovery_status', 'dues_written_off_by', 'dues_written_off_note',
            'marked_by', 'created_at', 'updated_at',
        ]
        read_only_fields = fields


class AbscondedRecordCreateSerializer(serializers.Serializer):
    """Marks a resident absconded (PRD Module 11 'Absconded Resident
    Workflow'). Advance forfeiture and outstanding-dues calc happen
    server-side in the service, not here."""

    resident = serializers.PrimaryKeyRelatedField(queryset=Resident.objects.all())
    absconded_date = serializers.DateField()
    last_seen_date = serializers.DateField(required=False, allow_null=True, default=None)
    absconded_note = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        request = self.context['request']
        resident = attrs['resident']
        if not can_view_property(request.user, resident.property_id):
            raise serializers.ValidationError(
                {'resident': _('You are not assigned to this property.')}, code='property_not_assigned',
            )
        if not resident.can_transition_to(Resident.Status.ABSCONDED):
            raise serializers.ValidationError(
                {'resident': _('Only an active resident can be marked absconded.')},
                code='resident_not_active',
            )
        return attrs


class DuesWriteOffSerializer(serializers.Serializer):
    """Write off remaining absconded dues as irrecoverable — mandatory note
    (PRD: 'owner can write off with mandatory note')."""

    note = serializers.CharField()

    def validate_note(self, value):
        if not value.strip():
            raise serializers.ValidationError(_('A note is required to write off dues.'), code='note_required')
        return value


class BlacklistEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = BlacklistEntry
        fields = ['id', 'resident', 'phone', 'aadhaar_number', 'reason', 'confirmed_by', 'created_at']
        read_only_fields = fields


class BlacklistConfirmSerializer(serializers.Serializer):
    """Owner/Manager confirms blacklisting (PRD: flagged automatically after
    Absconded, but blacklisting itself is never automatic)."""

    resident = serializers.PrimaryKeyRelatedField(queryset=Resident.objects.all())
    reason = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        request = self.context['request']
        resident = attrs['resident']
        if not can_view_property(request.user, resident.property_id):
            raise serializers.ValidationError(
                {'resident': _('You are not assigned to this property.')}, code='property_not_assigned',
            )
        if not resident.can_transition_to(Resident.Status.BLACKLISTED):
            raise serializers.ValidationError(
                {'resident': _('This resident cannot be blacklisted from their current status.')},
                code='invalid_status_transition',
            )
        return attrs
