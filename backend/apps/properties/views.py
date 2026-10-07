from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response

from apps.audit import log as audit_log
from apps.core.permissions import require_permission
from apps.core.roles import Role
from apps.subscriptions.services import check_property_limit

from . import feature_services, services
from .models import (
    Bed,
    Building,
    FeatureCatalog,
    Floor,
    Property,
    PropertyImage,
    PropertySettings,
    PropertyStaffAssignment,
    Room,
    TenantFeature,
)
from .serializers import (
    BedSerializer,
    BuildingSerializer,
    FeatureCatalogSerializer,
    FloorSerializer,
    PropertyFeatureSerializer,
    PropertyFeaturesWriteSerializer,
    PropertyImageSerializer,
    PropertySerializer,
    PropertySettingsSerializer,
    PropertyStaffAssignmentSerializer,
    RoomSerializer,
    TenantFeatureSerializer,
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


def _features_permission(request):
    """Module 18: read is wider than write (a Receptionist answers "do you
    have parking?" but doesn't decide what the PG offers)."""
    return require_permission(
        'view_property_features' if request.method in SAFE_METHODS else 'manage_property_features'
    )


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
        if self.action == 'property_features':
            return [IsAuthenticated(), _features_permission(self.request)()]
        return [CanViewProperties()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Property.objects.none()
        ids = services.visible_property_ids(self.request.user)
        return Property.objects.filter(id__in=ids).order_by('name')

    @transaction.atomic
    def perform_create(self, serializer):
        # Plan limit (PRD §4: "Hard block when either limit is reached") —
        # Module 13's concern; fail-open when no plan is configured. Inside the
        # transaction so check_property_limit can row-lock the subscription and
        # two concurrent creates can't both slip past the cap.
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

    @action(detail=True, methods=['get', 'post'], url_path='features', url_name='features')
    def property_features(self, request, pk=None):
        """Module 18 — what this PG offers. GET returns every row of the PG,
        or with ?building=<id> the effective set for that building. POST
        replaces the whole set at one scope (PUT semantics; this app doesn't
        route PUT)."""
        prop = self.get_object()
        if request.method == 'GET':
            building = feature_services.get_building(prop, request.query_params.get('building'))
        else:
            payload = PropertyFeaturesWriteSerializer(data=request.data)
            payload.is_valid(raise_exception=True)
            building = feature_services.replace_features(
                prop=prop,
                building_id=payload.validated_data.get('building'),
                items=payload.validated_data.get('items', []),
                excluded=payload.validated_data.get('excluded', []),
                actor=request.user, request=request,
            )
        items, excluded, derived = feature_services.feature_state(prop, building)
        return Response({
            'property': str(prop.id),
            'building': str(building.id) if building else None,
            'items': PropertyFeatureSerializer(items, many=True).data,
            'excluded': PropertyFeatureSerializer(excluded, many=True).data,
            'derived': derived,
        })


class FeatureCatalogViewSet(viewsets.ReadOnlyModelViewSet):
    """The platform's list of features a PG can offer. Not tenant data —
    managed through Django admin and seed migrations only."""

    serializer_class = FeatureCatalogSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None
    filterset_fields = ['category', 'is_active']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return FeatureCatalog.objects.none()
        if self.request.user.role == Role.SUPER_ADMIN:
            return FeatureCatalog.objects.all()
        return FeatureCatalog.objects.filter(is_active=True)


class TenantFeatureViewSet(viewsets.ModelViewSet):
    """Features the owner added themselves, reusable across all of the
    tenant's properties."""

    serializer_class = TenantFeatureSerializer
    http_method_names = ['get', 'post', 'patch', 'delete']
    pagination_class = None

    def get_permissions(self):
        return [IsAuthenticated(), _features_permission(self.request)()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return TenantFeature.objects.none()
        return TenantFeature.objects.filter(tenant_id=self.request.user.tenant_id)

    def create(self, request, *args, **kwargs):
        # 200 (not 201) when the feature already existed: type-to-add is
        # idempotent so a double-click or stale list can't create a duplicate.
        feature, created = feature_services.create_tenant_feature(
            tenant_id=request.user.tenant_id, label=request.data.get('label'),
            actor=request.user, request=request,
        )
        return Response(self.get_serializer(feature).data, status=201 if created else 200)

    def partial_update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        feature = feature_services.update_tenant_feature(
            serializer.instance,
            label=serializer.validated_data.get('label'),
            is_active=serializer.validated_data.get('is_active'),
            actor=request.user, request=request,
        )
        return Response(self.get_serializer(feature).data)

    def perform_destroy(self, instance):
        feature_services.delete_tenant_feature(instance, actor=self.request.user, request=self.request)


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
