from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import User
from apps.core.roles import STAFF_ROLES

from . import services
from .models import Bed, Floor, Property, PropertySettings, PropertyStaffAssignment, Room


class PropertySerializer(serializers.ModelSerializer):
    floors_count = serializers.SerializerMethodField()
    rooms_count = serializers.SerializerMethodField()
    beds_count = serializers.SerializerMethodField()

    class Meta:
        model = Property
        fields = [
            'id', 'name', 'property_type', 'address_line', 'city', 'state', 'country',
            'contact_number', 'contact_email', 'status',
            'floors_count', 'rooms_count', 'beds_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_floors_count(self, obj) -> int:
        return obj.floors.count()

    def get_rooms_count(self, obj) -> int:
        return Room.objects.filter(floor__property=obj).count()

    def get_beds_count(self, obj) -> int:
        return Bed.objects.filter(room__floor__property=obj).count()


class FloorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Floor
        fields = ['id', 'property', 'name', 'order', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_property(self, value):
        request = self.context['request']
        if not services.can_view_property(request.user, value.pk):
            raise serializers.ValidationError(
                _('You are not assigned to this property.'), code='property_not_assigned'
            )
        return value


class RoomSerializer(serializers.ModelSerializer):
    current_occupancy = serializers.SerializerMethodField()
    bed_capacity = serializers.SerializerMethodField()

    class Meta:
        model = Room
        fields = [
            'id', 'floor', 'room_number', 'sharing_type', 'category',
            'rack_rate_with_food', 'rack_rate_without_food', 'status',
            'current_occupancy', 'bed_capacity', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_current_occupancy(self, obj) -> int:
        return obj.beds.filter(status=Bed.Status.OCCUPIED).count()

    def get_bed_capacity(self, obj) -> int:
        return obj.sharing_type

    def validate_floor(self, value):
        request = self.context['request']
        if not services.can_view_property(request.user, value.property_id):
            raise serializers.ValidationError(
                _('You are not assigned to this property.'), code='property_not_assigned'
            )
        return value


class BedSerializer(serializers.ModelSerializer):
    effective_rate_with_food = serializers.SerializerMethodField()
    effective_rate_without_food = serializers.SerializerMethodField()

    class Meta:
        model = Bed
        fields = [
            'id', 'room', 'bed_number',
            'rack_rate_with_food_override', 'rack_rate_without_food_override',
            'effective_rate_with_food', 'effective_rate_without_food',
            'status', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_effective_rate_with_food(self, obj) -> str:
        return str(obj.rack_rate(with_food=True))

    def get_effective_rate_without_food(self, obj) -> str:
        return str(obj.rack_rate(with_food=False))

    def validate_room(self, value):
        request = self.context['request']
        if not services.can_view_property(request.user, value.floor.property_id):
            raise serializers.ValidationError(
                _('You are not assigned to this property.'), code='property_not_assigned'
            )
        return value

    def validate(self, attrs):
        room = attrs.get('room') or getattr(self.instance, 'room', None)
        if room is not None and self.instance is None:
            existing = room.beds.count()
            if existing >= room.sharing_type:
                raise serializers.ValidationError(
                    {'room': _('This room already has its full sharing-type capacity of beds.')},
                    code='bed_capacity_exceeded',
                )
        return attrs


class PropertyStaffAssignmentSerializer(serializers.ModelSerializer):
    staff_name = serializers.SerializerMethodField()
    property_name = serializers.CharField(source='property.name', read_only=True)

    class Meta:
        model = PropertyStaffAssignment
        fields = ['id', 'staff', 'staff_name', 'property', 'property_name', 'created_at']
        read_only_fields = ['id', 'created_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is not None and getattr(request.user, 'is_authenticated', False):
            self.fields['staff'].queryset = User.objects.filter(
                tenant_id=request.user.tenant_id, role__in=STAFF_ROLES,
            )
            self.fields['property'].queryset = Property.objects.filter(
                tenant_id=request.user.tenant_id,
            )

    def get_staff_name(self, obj) -> str:
        return f'{obj.staff.first_name} {obj.staff.last_name}'.strip()


class PropertySettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertySettings
        fields = [
            'id', 'room_transfer_rent_timing', 'late_payment_penalty_type',
            'penalty_value', 'penalty_grace_days', 'penalty_applies_to',
            'penalty_compounding', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        penalty_type = attrs.get(
            'late_payment_penalty_type',
            getattr(self.instance, 'late_payment_penalty_type', PropertySettings.PenaltyType.NONE),
        )
        if penalty_type == PropertySettings.PenaltyType.NONE:
            # No penalty configured — any stray value is meaningless, drop it.
            attrs['penalty_value'] = None
            return attrs

        penalty_value = attrs.get('penalty_value', getattr(self.instance, 'penalty_value', None))
        if not penalty_value:
            raise serializers.ValidationError(
                {'penalty_value': _('A penalty value is required when a penalty type is set.')},
                code='penalty_value_required',
            )
        if penalty_type == PropertySettings.PenaltyType.PERCENTAGE and not (0 < penalty_value <= 100):
            raise serializers.ValidationError(
                {'penalty_value': _('A percentage penalty must be between 0 and 100.')},
                code='invalid_percentage',
            )
        return attrs
