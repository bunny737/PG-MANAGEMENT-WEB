from rest_framework import serializers

from apps.properties.models import Property
from apps.residents.models import Resident

from .models import Plan, Subscription


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            'id', 'name', 'max_properties', 'max_residents_per_property',
            'price_per_month', 'is_trial_plan', 'is_active', 'created_at', 'updated_at',
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

    class Meta:
        model = Subscription
        fields = [
            'id', 'tenant', 'plan', 'tenant_status', 'trial_ends_at',
            'razorpay_subscription_id', 'current_period_start', 'current_period_end',
            'payment_failed_at', 'max_properties_override', 'max_residents_override',
            'properties_used', 'max_properties', 'max_residents_per_property', 'property_usage',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_properties_used(self, obj) -> int:
        return Property.objects.filter(tenant_id=obj.tenant_id).count()

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
