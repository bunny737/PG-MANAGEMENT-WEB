from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit import log as audit_log
from apps.core.permissions import require_permission
from apps.properties.models import Bed
from apps.properties.services import visible_property_ids

from .models import Admission, Resident
from .serializers import AdmissionSerializer, ResidentSerializer, ResidentStatusUpdateSerializer


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


class AdmissionViewSet(viewsets.ModelViewSet):
    """Admission = Check-In (PRD Module 6): create-and-read only, no update/
    delete — contracted terms are snapshotted once and never change.
    `manage_admissions` excludes Receptionist (front-desk has no billing/
    allocation access)."""

    serializer_class = AdmissionSerializer
    permission_classes = [IsAuthenticated, require_permission('manage_admissions')]
    http_method_names = ['get', 'post']
    filterset_fields = ['resident', 'bed']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Admission.objects.none()
        ids = visible_property_ids(self.request.user)
        return Admission.objects.filter(
            bed__room__floor__property_id__in=ids
        ).select_related('resident', 'bed')

    def perform_create(self, serializer):
        bed = serializer.validated_data['bed']
        resident = serializer.validated_data['resident']
        with_food = serializer.validated_data['food_preference'] == Admission.FoodPreference.WITH_FOOD

        instance = serializer.save(
            tenant_id=self.request.user.tenant_id,
            contracted_sharing_type=bed.room.sharing_type,
            contracted_room_category=bed.room.category,
            contracted_rent=bed.rack_rate(with_food=with_food),
            recorded_by=self.request.user,
        )

        bed.status = Bed.Status.OCCUPIED
        bed.save()  # also syncs the room's status (Module 02)

        before_status = resident.status
        resident.status = Resident.Status.ACTIVE
        resident.save(update_fields=['status', 'updated_at'])

        audit_log.record(
            action='admission.created', actor=self.request.user, obj=instance,
            after={'resident': str(resident.id), 'bed': str(bed.id),
                   'contracted_rent': str(instance.contracted_rent)},
            request=self.request,
        )
        audit_log.record(
            action='resident.status_changed', actor=self.request.user, obj=resident,
            before={'status': before_status}, after={'status': resident.status},
            request=self.request,
        )
