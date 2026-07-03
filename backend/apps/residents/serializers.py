from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.properties.services import can_view_property

from .models import Resident


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
