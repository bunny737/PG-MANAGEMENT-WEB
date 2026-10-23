"""Schema-only response shapes (UX roadmap web-client follow-up, S0b).

`analytics.summary()`/`trend()` build plain dicts by hand (see analytics.py's
docstring) — nothing here is ever instantiated to serialize a real response.
These classes exist only so `@extend_schema(responses=...)` gives
drf-spectacular (and therefore `openapi-typescript` on the web client) a real
type instead of an untyped `{}`. Keep them in sync with analytics.py; a
schema-completeness test (apps/reporting/tests/test_schema.py) catches a
response that drifts back to untyped.
"""
from rest_framework import serializers

MONEY_KWARGS = {'max_digits': 12, 'decimal_places': 2}


class YtdWindowSerializer(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()


class AnalyticsFinanceSerializer(serializers.Serializer):
    gross_receipts = serializers.DecimalField(**MONEY_KWARGS)
    refunds_paid = serializers.DecimalField(**MONEY_KWARGS)
    cash_collected = serializers.DecimalField(**MONEY_KWARGS)
    period_invoiced = serializers.DecimalField(**MONEY_KWARGS)
    period_collected = serializers.DecimalField(**MONEY_KWARGS)
    collection_rate = serializers.FloatField(allow_null=True)
    outstanding_total = serializers.DecimalField(**MONEY_KWARGS)
    period_outstanding = serializers.DecimalField(**MONEY_KWARGS)
    overdue_total = serializers.DecimalField(**MONEY_KWARGS)
    open_invoice_count = serializers.IntegerField()
    residents_with_balance_count = serializers.IntegerField()
    occupied_beds_with_balance_count = serializers.IntegerField()
    deposits_held = serializers.DecimalField(**MONEY_KWARGS)
    ytd_cash_collected = serializers.DecimalField(**MONEY_KWARGS)


class AnalyticsExpensesSerializer(serializers.Serializer):
    expenses_paid = serializers.DecimalField(**MONEY_KWARGS)
    ytd_expenses_paid = serializers.DecimalField(**MONEY_KWARGS)


class AnalyticsCashFlowSerializer(serializers.Serializer):
    net_cash_flow = serializers.DecimalField(**MONEY_KWARGS)
    ytd_net_cash_flow = serializers.DecimalField(**MONEY_KWARGS)


class OccupancySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    occupied = serializers.IntegerField()
    reserved = serializers.IntegerField()
    maintenance = serializers.IntegerField()
    available = serializers.IntegerField()
    occupancy_rate = serializers.FloatField(allow_null=True)


class AnalyticsSummarySerializer(serializers.Serializer):
    month = serializers.CharField()
    property = serializers.UUIDField(allow_null=True)
    timezones = serializers.ListField(child=serializers.CharField())
    balances_as_of = serializers.DateTimeField()
    ytd = YtdWindowSerializer()
    occupancy = OccupancySerializer()
    finance = AnalyticsFinanceSerializer(allow_null=True)
    expenses = AnalyticsExpensesSerializer(allow_null=True)
    cash_flow = AnalyticsCashFlowSerializer(allow_null=True)
    redacted = serializers.ListField(child=serializers.CharField())


class TrendFinanceSerializer(serializers.Serializer):
    gross_receipts = serializers.DecimalField(**MONEY_KWARGS)
    refunds_paid = serializers.DecimalField(**MONEY_KWARGS)
    cash_collected = serializers.DecimalField(**MONEY_KWARGS)
    period_invoiced = serializers.DecimalField(**MONEY_KWARGS)
    period_collected = serializers.DecimalField(**MONEY_KWARGS)
    collection_rate = serializers.FloatField(allow_null=True)


class TrendExpensesSerializer(serializers.Serializer):
    expenses_paid = serializers.DecimalField(**MONEY_KWARGS)


class TrendCashFlowSerializer(serializers.Serializer):
    net_cash_flow = serializers.DecimalField(**MONEY_KWARGS)


class TrendPointSerializer(serializers.Serializer):
    month = serializers.CharField()
    finance = TrendFinanceSerializer(allow_null=True)
    expenses = TrendExpensesSerializer(allow_null=True)
    cash_flow = TrendCashFlowSerializer(allow_null=True)


class AnalyticsTrendSerializer(serializers.Serializer):
    end = serializers.CharField()
    months = serializers.IntegerField()
    property = serializers.UUIDField(allow_null=True)
    timezones = serializers.ListField(child=serializers.CharField())
    series = TrendPointSerializer(many=True)
    redacted = serializers.ListField(child=serializers.CharField())
