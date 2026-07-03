from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated

from apps.audit import log as audit_log
from apps.core.permissions import require_permission
from apps.core.roles import Role

from . import services
from .models import Bed, Floor, Property, PropertyStaffAssignment, Room
from .serializers import (
    BedSerializer,
    FloorSerializer,
    PropertySerializer,
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
    http_method_names = ['get', 'post', 'patch']
    filterset_fields = ['status', 'property_type']

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update'):
            return [IsAuthenticated(), require_permission('manage_properties')()]
        return [CanViewProperties()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Property.objects.none()
        ids = services.visible_property_ids(self.request.user)
        return Property.objects.filter(id__in=ids).order_by('name')

    def perform_create(self, serializer):
        instance = serializer.save(tenant_id=self.request.user.tenant_id)
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


class FloorViewSet(viewsets.ModelViewSet):
    serializer_class = FloorSerializer
    permission_classes = [IsAuthenticated, require_permission('manage_rooms_beds')]
    http_method_names = ['get', 'post', 'patch', 'delete']
    filterset_fields = ['property']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Floor.objects.none()
        ids = services.visible_property_ids(self.request.user)
        return Floor.objects.filter(property_id__in=ids).select_related('property')

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
        return Room.objects.filter(floor__property_id__in=ids).select_related('floor')

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
        return Bed.objects.filter(room__floor__property_id__in=ids).select_related('room')

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
