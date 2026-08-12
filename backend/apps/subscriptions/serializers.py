from rest_framework import serializers

from apps.properties.models import Property
from apps.residents.models import Resident

from . import services
from .models import Plan, PlanBedTier, Subscription, SubscriptionInvoice, SubscriptionInvoiceLine


class PlanBedTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanBedTier
        fields = ['id', 'up_to_beds', 'rate_per_bed']
        read_only_fields = ['id']


class PlanSerializer(serializers.ModelSerializer):
    bed_tiers = PlanBedTierSerializer(many=True, read_only=True)

    class Meta:
        model = Plan
        fields = [
            'id', 'name', 'pricing_type', 'max_properties', 'max_residents_per_property',
            'price_per_month', 'bed_tiers', 'is_trial_plan', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class SubscriptionSerializer(serializers.ModelSerializer):
    """A tenant's plan + usage (PRD Module 20 'Current plan and usage
    (properties used vs. allowed)'). `property_usage` breaks usage down per
    property since that's how the resident limit is actually enforced
    (PRD §4: 'checked per property, not across all properties combined')."""

    plan = PlanSerializer(read_only=True)
    tenant_status = serializers.CharField(source='tenant.status', read_only=True)
    trial_ends_at = serializers.DateTimeField(source='tenant.trial_ends_at', read_only=True)
    properties_used = serializers.SerializerMethodField()
    max_properties = serializers.SerializerMethodField()
    max_residents_per_property = serializers.SerializerMethodField()
    property_usage = serializers.SerializerMethodField()
    bed_count = serializers.SerializerMethodField()
    current_cycle_estimate = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            'id', 'tenant', 'plan', 'tenant_status', 'trial_ends_at',
            'razorpay_subscription_id', 'current_period_start', 'current_period_end',
            'payment_failed_at', 'max_properties_override', 'max_residents_override',
            'properties_used', 'max_properties', 'max_residents_per_property', 'property_usage',
            'bed_count', 'current_cycle_estimate', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_properties_used(self, obj) -> int:
        return Property.objects.filter(tenant_id=obj.tenant_id).count()

    def get_bed_count(self, obj) -> int:
        return services.get_total_beds(obj.tenant_id)

    def get_current_cycle_estimate(self, obj):
        return services.estimate_current_cycle(obj)

    def get_max_properties(self, obj):
        return obj.effective_max_properties()

    def get_max_residents_per_property(self, obj):
        return obj.effective_max_residents_per_property()

    def get_property_usage(self, obj):
        max_residents = obj.effective_max_residents_per_property()
        return [
            {
                'property': str(prop.id),
                'name': prop.name,
                'residents_used': Resident.objects.filter(
                    property=prop, status__in=Resident.COUNTS_TOWARD_PLAN_LIMIT
                ).count(),
                'max_residents': max_residents,
            }
            for prop in Property.objects.filter(tenant_id=obj.tenant_id)
        ]


class SelectPlanSerializer(serializers.Serializer):
    plan = serializers.PrimaryKeyRelatedField(queryset=Plan.objects.filter(is_active=True))


class OverrideLimitsSerializer(serializers.Serializer):
    """Super Admin manual override (PRD §4: 'for a specific tenant if
    needed... grace period, enterprise negotiation'). Both fields are
    optional/partial — omit one to leave it unchanged."""

    max_properties_override = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    max_residents_override = serializers.IntegerField(required=False, allow_null=True, min_value=0)


class SubscriptionInvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionInvoiceLine
        fields = ['id', 'description', 'quantity', 'unit_rate', 'amount', 'addons']
        read_only_fields = fields


class SubscriptionInvoiceSerializer(serializers.ModelSerializer):
    """Platform billing history for PER_BED_MONTHLY subscriptions (PRD
    Module 20 'Billing history and invoices from platform')."""

    lines = SubscriptionInvoiceLineSerializer(many=True, read_only=True)

    class Meta:
        model = SubscriptionInvoice
        fields = [
            'id', 'period_start', 'period_end', 'status', 'total_amount',
            'billed_bed_count_start', 'billed_bed_count_end', 'lines',
            'issued_at', 'paid_at', 'created_at',
        ]
        read_only_fields = fields
