"""Schema-only response shape for drf-spectacular (UX roadmap web-client
follow-up, S0b). `layout.build_layout()` builds a plain nested dict by
hand (see layout.py's module docstring) — this class is never instantiated
to serialize a real response. It exists only so `@extend_schema(responses=...)`
gives a real type instead of an untyped `{}`. Keep it in sync with layout.py;
see apps/reporting/tests/test_schema.py for the completeness check."""
from rest_framework import serializers

MONEY_KWARGS = {'max_digits': 12, 'decimal_places': 2}


class BedCountsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    occupied = serializers.IntegerField()
    reserved = serializers.IntegerField()
    maintenance = serializers.IntegerField()
    available = serializers.IntegerField()
    occupancy_rate = serializers.FloatField(allow_null=True)


class LayoutFinanceSerializer(serializers.Serializer):
    outstanding_total = serializers.DecimalField(**MONEY_KWARGS)
    overdue_total = serializers.DecimalField(**MONEY_KWARGS)
    open_invoice_count = serializers.IntegerField()
    residents_with_balance_count = serializers.IntegerField()
    occupied_beds_with_balance_count = serializers.IntegerField()


class LayoutResidentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    phone = serializers.CharField()
    status = serializers.CharField()
    on_notice = serializers.BooleanField()
    notice_date = serializers.DateField(allow_null=True)
    expected_vacate_date = serializers.DateField(allow_null=True)
    is_temporary = serializers.BooleanField()


class LayoutPaymentSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['paid', 'upcoming', 'due', 'overdue', 'no_invoice'])
    period_balance = serializers.DecimalField(**MONEY_KWARGS)
    overdue_balance = serializers.DecimalField(**MONEY_KWARGS)


class LayoutReservedForSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField(allow_null=True)


class LayoutBedSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    bed_number = serializers.CharField()
    availability = serializers.ChoiceField(choices=['available', 'occupied', 'reserved', 'maintenance'])
    allowed_transitions = serializers.ListField(child=serializers.CharField())
    reserved_for = LayoutReservedForSerializer(allow_null=True)
    reserved_until = serializers.DateField(allow_null=True)
    rack_rate_with_food = serializers.DecimalField(**MONEY_KWARGS)
    rack_rate_without_food = serializers.DecimalField(**MONEY_KWARGS)
    resident = LayoutResidentSerializer(allow_null=True)
    payment = LayoutPaymentSerializer(allow_null=True)


class LayoutRoomSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    room_number = serializers.CharField()
    sharing_type = serializers.IntegerField()
    category = serializers.CharField()
    status = serializers.CharField()
    rack_rate_with_food = serializers.DecimalField(**MONEY_KWARGS)
    rack_rate_without_food = serializers.DecimalField(**MONEY_KWARGS)
    counts = BedCountsSerializer()
    beds = LayoutBedSerializer(many=True)


class LayoutFloorSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    order = serializers.IntegerField()
    counts = BedCountsSerializer()
    rooms = LayoutRoomSerializer(many=True)


class LayoutBuildingSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    order = serializers.IntegerField()
    counts = BedCountsSerializer()
    floors = LayoutFloorSerializer(many=True)


class LayoutPropertyRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class PropertyLayoutResponseSerializer(serializers.Serializer):
    property = LayoutPropertyRefSerializer()
    period = serializers.CharField()
    as_of = serializers.DateField()
    due_soon_days = serializers.IntegerField()
    counts = BedCountsSerializer()
    finance = LayoutFinanceSerializer(allow_null=True)
    buildings = LayoutBuildingSerializer(many=True)
    redacted = serializers.ListField(child=serializers.CharField())
