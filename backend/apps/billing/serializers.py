from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.properties.services import can_view_property

from .models import Discount


def _windows_overlap(from1, until1, from2, until2):
    """Do two [from, until] date windows overlap? `until=None` means open-ended
    (indefinite). Boundaries are inclusive — sharing a single day counts."""
    start = max(from1, from2)
    ends = [u for u in (until1, until2) if u is not None]
    end = min(ends) if ends else None
    return end is None or start <= end


class DiscountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discount
        fields = [
            'id', 'resident', 'discount_type', 'discount_value', 'reason',
            'note', 'valid_from', 'valid_until', 'approved_by',
            'created_at', 'updated_at',
        ]
        # approved_by is stamped from the request user server-side.
        read_only_fields = ['id', 'approved_by', 'created_at', 'updated_at']

    def validate_resident(self, value):
        request = self.context['request']
        if not can_view_property(request.user, value.property_id):
            raise serializers.ValidationError(
                _('You are not assigned to this property.'), code='property_not_assigned'
            )
        return value

    def validate(self, attrs):
        instance = self.instance

        def resolved(field):
            return attrs.get(field, getattr(instance, field, None))

        discount_type = resolved('discount_type')
        discount_value = resolved('discount_value')
        valid_from = resolved('valid_from')
        valid_until = resolved('valid_until')
        resident = resolved('resident')

        if discount_value is None or discount_value <= 0:
            raise serializers.ValidationError(
                {'discount_value': _('Discount value must be greater than zero.')},
                code='invalid_discount_value',
            )
        if discount_type == Discount.DiscountType.PERCENTAGE and discount_value > 100:
            raise serializers.ValidationError(
                {'discount_value': _('A percentage discount cannot exceed 100.')},
                code='invalid_percentage',
            )
        if valid_until is not None and valid_until < valid_from:
            raise serializers.ValidationError(
                {'valid_until': _('valid_until cannot be before valid_from.')},
                code='invalid_date_range',
            )

        # At most one active discount per resident at a time — reject a window
        # overlapping any of the resident's other discounts (invariant 4: a
        # single discount line, no silent stacking).
        others = Discount.objects.filter(resident=resident)
        if instance is not None:
            others = others.exclude(pk=instance.pk)
        for other in others:
            if _windows_overlap(valid_from, valid_until, other.valid_from, other.valid_until):
                raise serializers.ValidationError(
                    {'valid_from': _('This resident already has a discount active in this period.')},
                    code='overlapping_discount',
                )
        return attrs
