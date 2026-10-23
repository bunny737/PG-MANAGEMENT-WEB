"""Schema-only response shapes for drf-spectacular (UX roadmap web-client
follow-up, S0b). `services.summary()` and the attachment GET build plain
dicts by hand — these classes are never instantiated to serialize a real
response. They exist only so `@extend_schema(responses=...)` gives a real
type instead of an untyped `{}`. Keep them in sync with views.py/services.py;
see apps/reporting/tests/test_schema.py for the completeness check."""
from rest_framework import serializers


class ExpenseCategoryTotalSerializer(serializers.Serializer):
    category = serializers.UUIDField()
    name = serializers.CharField()
    code = serializers.CharField(allow_null=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    count = serializers.IntegerField()


class ExpenseSummaryResponseSerializer(serializers.Serializer):
    month = serializers.CharField()
    property = serializers.UUIDField(allow_null=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    count = serializers.IntegerField()
    by_category = ExpenseCategoryTotalSerializer(many=True)


class ExpenseAttachmentResponseSerializer(serializers.Serializer):
    url = serializers.URLField()
    content_type = serializers.CharField()
    expires_in = serializers.IntegerField()
