from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.properties.models import Bed
from apps.properties.services import can_view_property

from .models import Admission, Resident


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
            'advance_amount', 'first_month_billing_amount', 'first_month_billing_note',
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
