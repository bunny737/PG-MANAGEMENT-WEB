"""Schema-only response shapes for drf-spectacular (UX roadmap web-client
follow-up, S0b). `finance.resident_finance()` builds a plain dict by hand,
and `ResidentViewSet.retrieve()` adds `finance`/`redacted` to the serialized
resident outside any serializer — these classes exist only so
`@extend_schema(responses=...)` gives a real type for the detail response
instead of an untyped `{}`. Keep them in sync with finance.py/views.py; see
apps/reporting/tests/test_schema.py for the completeness check."""
from rest_framework import serializers

from .serializers import ResidentSerializer

MONEY_KWARGS = {'max_digits': 12, 'decimal_places': 2}


class CurrentPeriodInvoiceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    total = serializers.DecimalField(**MONEY_KWARGS)
    paid = serializers.DecimalField(**MONEY_KWARGS)
    balance = serializers.DecimalField(**MONEY_KWARGS)
    due_date = serializers.DateField()
    status = serializers.CharField()
    is_overdue = serializers.BooleanField()


class CurrentPeriodSerializer(serializers.Serializer):
    period = serializers.CharField()
    invoices = CurrentPeriodInvoiceSerializer(many=True)
    total = serializers.DecimalField(**MONEY_KWARGS)
    paid = serializers.DecimalField(**MONEY_KWARGS)
    balance = serializers.DecimalField(**MONEY_KWARGS)
    status = serializers.ChoiceField(
        choices=['no_invoice', 'paid', 'partially_paid', 'unpaid', 'overdue'],
    )
    has_draft = serializers.BooleanField()


class ResidentFinanceSerializer(serializers.Serializer):
    current_period = CurrentPeriodSerializer()
    outstanding_total = serializers.DecimalField(**MONEY_KWARGS)
    overdue_total = serializers.DecimalField(**MONEY_KWARGS)
    prior_outstanding = serializers.DecimalField(**MONEY_KWARGS)
    last_payment_date = serializers.DateField(allow_null=True)


class ResidentDetailResponseSerializer(ResidentSerializer):
    """ResidentSerializer's own fields, plus the two the detail view adds."""

    finance = ResidentFinanceSerializer(allow_null=True)
    redacted = serializers.ListField(child=serializers.CharField())

    class Meta(ResidentSerializer.Meta):
        fields = ResidentSerializer.Meta.fields + ['finance', 'redacted']
