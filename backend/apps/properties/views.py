from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from apps.audit import log as audit_log
from apps.core.permissions import require_permission
from apps.core.roles import Role
from apps.subscriptions.services import check_property_limit

from . import services
from .models import Bed, Building, Floor, Property, PropertyImage, PropertySettings, PropertyStaffAssignment, Room
from .serializers import (
    BedSerializer,
    BuildingSerializer,
    FloorSerializer,
    PropertyImageSerializer,
    PropertySerializer,
    PropertySettingsSerializer,
    PropertyStaffAssignmentSerializer,
    RoomSerializer,
)

# manage_properties (PRD §6) only covers Owner/Super Admin, but Manager and
# Receptionist must still be able to *view* the properties they're assigned
# to (property switcher). Read access is gated by role here; queryset
# scoping (services.visible_property_ids) enforces the assignment itself.
_PROPERTY_VIEW_ROLES = (Role.SUPER_ADMIN, Role.OWNER, Role.MANAGER, Role.RECEPTIONIST)


class CanViewProperties(BasePermission):
    message = _('You do not have access to properties.')

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role in _PROPERTY_VIEW_ROLES)


class PropertyViewSet(viewsets.ModelViewSet):
    """Owner/Super Admin manage all tenant properties; Manager/Receptionist
    see only properties they're assigned to (PRD §6). No hard delete —
    deactivate via `status`."""

    serializer_class = PropertySerializer
    # 'delete' is needed for the nested image sub-resource below; Property
    # itself still has no hard-delete (see destroy() override) — the
    # sub-resource route lives under the same http_method_names because DRF's
    # dispatch() checks this list before routing to any action, custom or not.
    http_method_names = ['get', 'post', 'patch', 'delete']
    filterset_fields = ['status', 'property_type']

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'upload_image', 'delete_image'):
            return [IsAuthenticated(), require_permission('manage_properties')()]
        if self.action == 'property_settings':
            return [IsAuthenticated(), require_permission('manage_property_settings')()]
        return [CanViewProperties()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Property.objects.none()
        ids = services.visible_property_ids(self.request.user)
        return Property.objects.filter(id__in=ids).order_by('name')

    def perform_create(self, serializer):
        # Plan limit (PRD §4: "Hard block when either limit is reached") —
        # Module 13's concern; fail-open when no plan is configured.
        check_property_limit(self.request.user.tenant_id)
        instance = serializer.save(tenant_id=self.request.user.tenant_id)
        # Every Property always has at least one Building (see docs/modules/
        # 02-property-hierarchy.md Decisions, 2026-07-05) — auto-provisioned
        # so single-building owners never have to think about the concept.
        Building.objects.create(
            tenant_id=instance.tenant_id, property=instance, name='Main Building', order=0,
        )
        audit_log.record(
            action='property.created', actor=self.request.user, obj=instance,
            after={'name': instance.name, 'status': instance.status},
            request=self.request,
        )

    def perform_update(self, serializer):
        before = {'name': serializer.instance.name, 'status': serializer.instance.status}
        instance = serializer.save()
        after = {'name': instance.name, 'status': instance.status}
        if before != after:
            audit_log.record(
                action='property.updated', actor=self.request.user, obj=instance,
                before=before, after=after, request=self.request,
            )

    def destroy(self, request, *args, **kwargs):
        # No hard delete (deactivate via status instead) — explicit so the
        # 'delete' method name added above for the image sub-resource doesn't
        # accidentally reopen this.
        raise MethodNotAllowed(request.method)

    @action(detail=True, methods=['post'], url_path='images', parser_classes=[MultiPartParser, FormParser])
    def upload_image(self, request, pk=None):
        prop = self.get_object()
        image_file = request.FILES.get('image')
        if not image_file:
            raise ValidationError({'image': _('An image file is required.')})
        instance = PropertyImage.objects.create(
            tenant_id=prop.tenant_id, property=prop, image=image_file, order=prop.images.count(),
        )
        return Response(
            PropertyImageSerializer(instance, context=self.get_serializer_context()).data, status=201,
        )

    @action(detail=True, methods=['delete'], url_path=r'images/(?P<image_id>[^/.]+)')
    def delete_image(self, request, pk=None, image_id=None):
        prop = self.get_object()
        image = get_object_or_404(prop.images, pk=image_id)
        image.image.delete(save=False)
        image.delete()
        return Response(status=204)

    # Named property_settings, not "settings" — a method called `settings`
    # shadows APIView.settings (the api_settings instance DRF relies on
    # internally), which breaks exception handling for the whole viewset.
    @action(detail=True, methods=['get', 'patch'], url_path='settings', url_name='settings')
    def property_settings(self, request, pk=None):
        """PRD Module 2B — per-property billing/transfer settings. Lazily
        created with PRD defaults on first access; there's exactly one row
        per property so there's no separate create endpoint."""
        prop = self.get_object()
        instance, _created = PropertySettings.objects.get_or_create(
            property=prop, defaults={'tenant_id': prop.tenant_id}
        )
        if request.method == 'GET':
            return Response(PropertySettingsSerializer(instance).data)

        before = PropertySettingsSerializer(instance).data
        serializer = PropertySettingsSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        after = PropertySettingsSerializer(instance).data
        if before != after:
            audit_log.record(
                action='property_settings.updated', actor=request.user, obj=instance,
                before=before, after=after, request=request,
            )
        return Response(after)


class BuildingViewSet(viewsets.ModelViewSet):
    serializer_class = BuildingSerializer
    permission_classes = [IsAuthenticated, require_permission('manage_rooms_beds')]
    http_method_names = ['get', 'post', 'patch', 'delete']
    filterset_fields = ['property']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Building.objects.none()
        ids = services.visible_property_ids(self.request.user)
        return Building.objects.filter(property_id__in=ids).select_related('property')

    def perform_create(self, serializer):
        instance = serializer.save(tenant_id=self.request.user.tenant_id)
        audit_log.record(
            action='building.created', actor=self.request.user, obj=instance,
            after={'name': instance.name, 'property': instance.property.name},
            request=self.request,
        )

    def perform_destroy(self, instance):
        if instance.floors.exists():
            raise ValidationError(
                {'detail': _('Cannot delete a building that still has floors.')},
                code='building_not_empty',
            )
        instance.delete()


class FloorViewSet(viewsets.ModelViewSet):
    serializer_class = FloorSerializer
    permission_classes = [IsAuthenticated, require_permission('manage_rooms_beds')]
    http_method_names = ['get', 'post', 'patch', 'delete']
    filterset_fields = ['building']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Floor.objects.none()
        ids = services.visible_property_ids(self.request.user)
        return Floor.objects.filter(building__property_id__in=ids).select_related('building__property')

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.user.tenant_id)

    def perform_destroy(self, instance):
        if instance.rooms.exists():
            raise ValidationError(
                {'detail': _('Cannot delete a floor that still has rooms.')},
                code='floor_not_empty',
            )
        instance.delete()


class RoomViewSet(viewsets.ModelViewSet):
    serializer_class = RoomSerializer
    permission_classes = [IsAuthenticated, require_permission('manage_rooms_beds')]
    http_method_names = ['get', 'post', 'patch', 'delete']
    filterset_fields = ['floor', 'category', 'status']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Room.objects.none()
        ids = services.visible_property_ids(self.request.user)
        return Room.objects.filter(floor__building__property_id__in=ids).select_related('floor')

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.user.tenant_id)

    def perform_destroy(self, instance):
        if instance.beds.exists():
            raise ValidationError(
                {'detail': _('Cannot delete a room that still has beds.')},
                code='room_not_empty',
            )
        instance.delete()


class BedViewSet(viewsets.ModelViewSet):
    serializer_class = BedSerializer
    permission_classes = [IsAuthenticated, require_permission('manage_rooms_beds')]
    http_method_names = ['get', 'post', 'patch', 'delete']
    filterset_fields = ['room', 'status']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Bed.objects.none()
        ids = services.visible_property_ids(self.request.user)
        return Bed.objects.filter(room__floor__building__property_id__in=ids).select_related('room')

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.user.tenant_id)

    def perform_destroy(self, instance):
        if instance.status in (Bed.Status.OCCUPIED, Bed.Status.RESERVED):
            raise ValidationError(
                {'detail': _('Cannot delete a bed that is occupied or reserved.')},
                code='bed_not_vacant',
            )
        instance.delete()


class PropertyStaffAssignmentViewSet(viewsets.ModelViewSet):
    """Owner-only: assign/unassign Manager or Receptionist accounts to
    properties (PRD §6 'Property Assignment Rules')."""

    serializer_class = PropertyStaffAssignmentSerializer
    permission_classes = [IsAuthenticated, require_permission('assign_staff_to_properties')]
    http_method_names = ['get', 'post', 'delete']
    filterset_fields = ['staff', 'property']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return PropertyStaffAssignment.objects.none()
        return (
            PropertyStaffAssignment.objects.filter(tenant_id=self.request.user.tenant_id)
            .select_related('staff', 'property')
            .order_by('-created_at')
        )

    def perform_create(self, serializer):
        instance = serializer.save(tenant_id=self.request.user.tenant_id)
        audit_log.record(
            action='property_staff_assignment.created', actor=self.request.user, obj=instance,
            after={'staff': instance.staff.email, 'property': instance.property.name},
            request=self.request,
        )

    def perform_destroy(self, instance):
        audit_log.record(
            action='property_staff_assignment.removed', actor=self.request.user, obj=instance,
            before={'staff': instance.staff.email, 'property': instance.property.name},
            request=self.request,
        )
        instance.delete()
