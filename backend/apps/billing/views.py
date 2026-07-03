from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.audit import log as audit_log
from apps.core.permissions import require_permission
from apps.properties.services import visible_property_ids

from .models import Discount
from .serializers import DiscountSerializer


class DiscountViewSet(viewsets.ModelViewSet):
    """Per-resident discounts (PRD Module 8). `manage_discounts` excludes
    Receptionist. No hard delete — end a discount by setting `valid_until`
    (consistent with the rest of the platform's financial-record handling)."""

    serializer_class = DiscountSerializer
    permission_classes = [IsAuthenticated, require_permission('manage_discounts')]
    http_method_names = ['get', 'post', 'patch']
    filterset_fields = ['resident', 'reason', 'discount_type']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Discount.objects.none()
        ids = visible_property_ids(self.request.user)
        return (
            Discount.objects.filter(resident__property_id__in=ids)
            .select_related('resident', 'approved_by')
        )

    def perform_create(self, serializer):
        instance = serializer.save(
            tenant_id=self.request.user.tenant_id, approved_by=self.request.user
        )
        audit_log.record(
            action='discount.created', actor=self.request.user, obj=instance,
            after={'resident': str(instance.resident_id), 'type': instance.discount_type,
                   'value': str(instance.discount_value), 'reason': instance.reason},
            request=self.request,
        )

    def perform_update(self, serializer):
        instance = serializer.instance
        before = {
            'type': instance.discount_type, 'value': str(instance.discount_value),
            'valid_until': instance.valid_until.isoformat() if instance.valid_until else None,
        }
        instance = serializer.save()
        after = {
            'type': instance.discount_type, 'value': str(instance.discount_value),
            'valid_until': instance.valid_until.isoformat() if instance.valid_until else None,
        }
        if before != after:
            audit_log.record(
                action='discount.updated', actor=self.request.user, obj=instance,
                before=before, after=after, request=self.request,
            )
