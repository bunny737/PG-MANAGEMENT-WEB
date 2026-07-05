from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import User
from apps.core.roles import STAFF_ROLES

from . import services
from .models import Bed, Building, Floor, Property, PropertyImage, PropertySettings, PropertyStaffAssignment, Room


def _ordinal_floor_name(index):
    """0 -> "Ground Floor", 1 -> "1st Floor", 2 -> "2nd Floor", ... — used to
    auto-name floors generated from a Building's `number_of_floors`."""
    if index == 0:
        return 'Ground Floor'
    suffix = 'th' if 10 <= index % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(index % 10, 'th')
    return f'{index}{suffix} Floor'


class PropertyImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyImage
        fields = ['id', 'image', 'order', 'created_at']
        read_only_fields = ['id', 'created_at']


class PropertySerializer(serializers.ModelSerializer):
    buildings_count = serializers.SerializerMethodField()
    floors_count = serializers.SerializerMethodField()
    rooms_count = serializers.SerializerMethodField()
    beds_count = serializers.SerializerMethodField()
    occupancy_percent = serializers.SerializerMethodField()
    images = PropertyImageSerializer(many=True, read_only=True)

    class Meta:
        model = Property
        fields = [
            'id', 'name', 'property_type', 'address_line', 'city', 'state', 'country',
            'contact_number', 'contact_email', 'status',
            'buildings_count', 'floors_count', 'rooms_count', 'beds_count', 'occupancy_percent',
            'images', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_buildings_count(self, obj) -> int:
        return obj.buildings.count()

    def get_floors_count(self, obj) -> int:
        return Floor.objects.filter(building__property=obj).count()

    def get_rooms_count(self, obj) -> int:
        return Room.objects.filter(floor__building__property=obj).count()

    def get_beds_count(self, obj) -> int:
        return Bed.objects.filter(room__floor__building__property=obj).count()

    def get_occupancy_percent(self, obj) -> int:
        total_beds = Bed.objects.filter(room__floor__building__property=obj).count()
        if total_beds == 0:
            return 0
        occupied_beds = Bed.objects.filter(
            room__floor__building__property=obj, status=Bed.Status.OCCUPIED
        ).count()
        return int((occupied_beds / total_beds) * 100)


class BuildingSerializer(serializers.ModelSerializer):
    order = serializers.IntegerField(required=False)
    # Write-only convenience: auto-generates that many Floors (named "Ground
    # Floor", "1st Floor", ...) in the same request, so an owner adding a new
    # block doesn't have to add each floor by hand afterwards.
    number_of_floors = serializers.IntegerField(write_only=True, required=False, default=0, min_value=0, max_value=100)
    floors_count = serializers.SerializerMethodField()
    rooms_count = serializers.SerializerMethodField()
    occupancy_percent = serializers.SerializerMethodField()

    class Meta:
        model = Building
        fields = [
            'id', 'property', 'name', 'order', 'number_of_floors',
            'floors_count', 'rooms_count', 'occupancy_percent', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_property(self, value):
        request = self.context['request']
        if not services.can_view_property(request.user, value.pk):
            raise serializers.ValidationError(
                _('You are not assigned to this property.'), code='property_not_assigned'
            )
        return value

    def to_internal_value(self, data):
        if self.instance is None:
            if 'order' not in data or data.get('order') == '' or data.get('order') is None:
                if hasattr(data, 'copy'):
                    data = data.copy()
                else:
                    data = dict(data)
                prop_id = data.get('property')
                if prop_id:
                    last_building = Building.objects.filter(property_id=prop_id).order_by('-order').first()
                    data['order'] = (last_building.order + 1) if last_building else 0
                else:
                    data['order'] = 0
        return super().to_internal_value(data)

    def create(self, validated_data):
        number_of_floors = validated_data.pop('number_of_floors', 0)
        with transaction.atomic():
            building = super().create(validated_data)
            for i in range(number_of_floors):
                Floor.objects.create(
                    tenant_id=building.tenant_id, building=building,
                    name=_ordinal_floor_name(i), order=i,
                )
        return building

    def get_floors_count(self, obj) -> int:
        return obj.floors.count()

    def get_rooms_count(self, obj) -> int:
        return Room.objects.filter(floor__building=obj).count()

    def get_occupancy_percent(self, obj) -> int:
        total_beds = Bed.objects.filter(room__floor__building=obj).count()
        if total_beds == 0:
            return 0
        occupied_beds = Bed.objects.filter(room__floor__building=obj, status=Bed.Status.OCCUPIED).count()
        return int((occupied_beds / total_beds) * 100)


class FloorSerializer(serializers.ModelSerializer):
    order = serializers.IntegerField(required=False)
    rooms_count = serializers.SerializerMethodField()
    occupancy_percent = serializers.SerializerMethodField()

    class Meta:
        model = Floor
        fields = ['id', 'building', 'name', 'order', 'rooms_count', 'occupancy_percent', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_building(self, value):
        request = self.context['request']
        if not services.can_view_property(request.user, value.property_id):
            raise serializers.ValidationError(
                _('You are not assigned to this property.'), code='property_not_assigned'
            )
        return value

    def to_internal_value(self, data):
        if self.instance is None:
            if 'order' not in data or data.get('order') == '' or data.get('order') is None:
                # Support mutable dict copy
                if hasattr(data, 'copy'):
                    data = data.copy()
                else:
                    data = dict(data)
                building_id = data.get('building')
                if building_id:
                    last_floor = Floor.objects.filter(building_id=building_id).order_by('-order').first()
                    data['order'] = (last_floor.order + 1) if last_floor else 0
                else:
                    data['order'] = 0
        return super().to_internal_value(data)

    def get_rooms_count(self, obj) -> int:
        return obj.rooms.count()

    def get_occupancy_percent(self, obj) -> int:
        total_beds = Bed.objects.filter(room__floor=obj).count()
        if total_beds == 0:
            return 0
        occupied_beds = Bed.objects.filter(room__floor=obj, status=Bed.Status.OCCUPIED).count()
        return int((occupied_beds / total_beds) * 100)


class BedSerializer(serializers.ModelSerializer):
    effective_rate_with_food = serializers.SerializerMethodField()
    effective_rate_without_food = serializers.SerializerMethodField()
    current_occupant = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()

    class Meta:
        model = Bed
        fields = [
            'id', 'room', 'bed_number',
            'rack_rate_with_food_override', 'rack_rate_without_food_override',
            'effective_rate_with_food', 'effective_rate_without_food',
            'status', 'current_occupant', 'history', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_effective_rate_with_food(self, obj) -> str:
        return str(obj.rack_rate(with_food=True))

    def get_effective_rate_without_food(self, obj) -> str:
        return str(obj.rack_rate(with_food=False))

    def get_current_occupant(self, obj):
        from apps.residents.models import Allocation, Resident
        allocation = obj.allocations.select_related('resident__admission').filter(
            resident__status__in=[Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD]
        ).first()
        if allocation and allocation.resident:
            res = allocation.resident
            return {
                'id': str(res.id),
                'first_name': res.first_name,
                'last_name': res.last_name,
                'full_name': f"{res.first_name} {res.last_name}".strip(),
                'email': res.email,
                'phone': res.phone,
                'status': res.status,
                'joining_date': res.admission.joining_date.strftime('%Y-%m-%d') if hasattr(res, 'admission') else None,
                'rent': str(allocation.contracted_rent),
                'initials': f"{res.first_name[0] if res.first_name else ''}{res.last_name[0] if res.last_name else ''}".upper(),
            }
        return None

    def get_history(self, obj):
        from apps.residents.models import Admission
        admissions = obj.admissions.select_related('resident__vacate').order_by('-joining_date')
        history_list = []
        for adm in admissions:
            res = adm.resident
            initials = f"{res.first_name[0] if res.first_name else ''}{res.last_name[0] if res.last_name else ''}".upper()
            
            # Resolve moveOut date/status
            move_out = 'Active'
            if res.status == 'vacated':
                if hasattr(res, 'vacate') and res.vacate.actual_vacate_date:
                    move_out = res.vacate.actual_vacate_date.strftime('%m/%d/%y')
                else:
                    move_out = 'Vacated'
            elif res.status == 'notice_period':
                if hasattr(res, 'vacate'):
                    move_out = f"Notice (Exp: {res.vacate.expected_vacate_date.strftime('%m/%d/%y')})"
                else:
                    move_out = 'Notice Period'
            elif res.status != 'active':
                move_out = res.status.title()

            history_list.append({
                'resident': f"{res.first_name} {res.last_name}".strip(),
                'term': f"Admission - {adm.billing_mode.replace('_', ' ').title()}",
                'moveIn': adm.joining_date.strftime('%m/%d/%y'),
                'moveOut': move_out,
                'rate': f"₹{int(adm.contracted_rent)}",
                'initials': initials,
            })
        return history_list

    def validate_room(self, value):
        request = self.context['request']
        if not services.can_view_property(request.user, value.floor.building.property_id):
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


class RoomSerializer(serializers.ModelSerializer):
    current_occupancy = serializers.SerializerMethodField()
    bed_capacity = serializers.SerializerMethodField()
    beds = BedSerializer(many=True, read_only=True)

    class Meta:
        model = Room
        fields = [
            'id', 'floor', 'room_number', 'sharing_type', 'category',
            'rack_rate_with_food', 'rack_rate_without_food', 'status',
            'current_occupancy', 'bed_capacity', 'beds', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_current_occupancy(self, obj) -> int:
        return obj.beds.filter(status=Bed.Status.OCCUPIED).count()

    def get_bed_capacity(self, obj) -> int:
        return obj.sharing_type

    def validate_floor(self, value):
        request = self.context['request']
        if not services.can_view_property(request.user, value.building.property_id):
            raise serializers.ValidationError(
                _('You are not assigned to this property.'), code='property_not_assigned'
            )
        return value


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
