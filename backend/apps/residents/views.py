from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit import log as audit_log
from apps.core.permissions import require_permission
from apps.properties.services import visible_property_ids

from .models import Resident
from .serializers import ResidentSerializer, ResidentStatusUpdateSerializer


class ResidentViewSet(viewsets.ModelViewSet):
    """Resident profiles (PRD Module 5). Read access follows
    `view_resident_profile` (Super Admin/Owner/Manager/Receptionist);
    profile writes and status transitions follow `manage_residents`
    (excludes Receptionist — front-desk is read-only). No delete —
    vacate/blacklist via the status lifecycle instead."""

    serializer_class = ResidentSerializer
    http_method_names = ['get', 'post', 'patch']
    filterset_fields = ['property', 'status']

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'change_status'):
            return [IsAuthenticated(), require_permission('manage_residents')()]
        return [IsAuthenticated(), require_permission('view_resident_profile')()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Resident.objects.none()
        ids = visible_property_ids(self.request.user)
        return Resident.objects.filter(property_id__in=ids).select_related('property')

    def perform_create(self, serializer):
        instance = serializer.save(tenant_id=self.request.user.tenant_id)
        audit_log.record(
            action='resident.created', actor=self.request.user, obj=instance,
            after={'first_name': instance.first_name, 'last_name': instance.last_name,
                   'status': instance.status, 'property': str(instance.property_id)},
            request=self.request,
        )

    # Named change_status, not "status" — see Module 03's PropertySettings
    # write-up on why a method named after a DRF-internal attribute breaks
    # exception handling for the whole viewset.
    @action(detail=True, methods=['patch'], url_path='status', url_name='status')
    def change_status(self, request, pk=None):
        resident = self.get_object()
        before_status = resident.status
        serializer = ResidentStatusUpdateSerializer(resident, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        audit_log.record(
            action='resident.status_changed', actor=request.user, obj=instance,
            before={'status': before_status}, after={'status': instance.status},
            request=request,
        )
        return Response(ResidentSerializer(instance).data)
