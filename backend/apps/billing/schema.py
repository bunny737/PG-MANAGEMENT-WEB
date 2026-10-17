"""Schema-only response shapes for drf-spectacular (UX roadmap web-client
follow-up, S0b). `CashMovementView.get()` and `receipts.receipt_json()` build
plain dicts by hand — these classes are never instantiated to serialize a
real response. They exist only so `@extend_schema(responses=...)` gives a
real type instead of an untyped `{}`. Keep them in sync; see
apps/reporting/tests/test_schema.py for the completeness check."""
from rest_framework import serializers

MONEY_KWARGS = {'max_digits': 12, 'decimal_places': 2}


class CashMovementRowSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=['payment'])
    id = serializers.UUIDField()
    date = serializers.DateField()
    amount = serializers.DecimalField(**MONEY_KWARGS)
    receipt_number = serializers.CharField(allow_null=True)
    payment_mode = serializers.CharField()
    invoice = serializers.UUIDField()
    resident = serializers.UUIDField()
    resident_name = serializers.CharField()
    property = serializers.UUIDField()
    property_name = serializers.CharField()


class CashMovementsResponseSerializer(serializers.Serializer):
    from_ = serializers.DateField(source='from')
    to = serializers.DateField()
    gross_receipts = serializers.DecimalField(**MONEY_KWARGS)
    refunds_paid = serializers.DecimalField(**MONEY_KWARGS)
    total = serializers.DecimalField(**MONEY_KWARGS)
    count = serializers.IntegerField()
    results = CashMovementRowSerializer(many=True)


class ReceiptResponseSerializer(serializers.Serializer):
    receipt_for = serializers.UUIDField()
    receipt_number = serializers.CharField(allow_null=True)
    resident = serializers.CharField()
    resident_id = serializers.UUIDField()
    property = serializers.UUIDField()
    property_name = serializers.CharField()
    room_number = serializers.CharField(allow_null=True)
    bed_number = serializers.CharField(allow_null=True)
    invoice = serializers.UUIDField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    amount = serializers.DecimalField(**MONEY_KWARGS)
    payment_date = serializers.DateField()
    payment_mode = serializers.CharField()
    reference = serializers.CharField(allow_blank=True)
    recorded_by = serializers.CharField(allow_null=True)
    recorded_by_name = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
    invoice_total = serializers.DecimalField(**MONEY_KWARGS)
    invoice_paid = serializers.DecimalField(**MONEY_KWARGS)
    invoice_balance_due = serializers.DecimalField(**MONEY_KWARGS)
    invoice_status = serializers.CharField()
