from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit import log as audit_log
from apps.core.permissions import require_permission
from apps.properties.models import Bed
from apps.properties.services import visible_property_ids
from apps.subscriptions.services import check_resident_limit

from . import services
from .models import AbscondedRecord, Admission, Allocation, BlacklistEntry, Resident, Transfer, Vacate
from .serializers import (
    AbscondedRecordCreateSerializer,
    AbscondedRecordSerializer,
    AdmissionSerializer,
    AllocationSerializer,
    BlacklistConfirmSerializer,
    BlacklistEntrySerializer,
    DuesWriteOffSerializer,
    ResidentSerializer,
    ResidentStatusUpdateSerializer,
    TransferCreateSerializer,
    TransferSerializer,
    VacateFinalizeSerializer,
    VacateGiveNoticeSerializer,
    VacateSerializer,
)


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
        new_status = serializer.validated_data['status']
        # Plan limit (Module 13) — only re-check when this transition is what
        # would newly count the resident (e.g. Reserved -> Active bypassing
        # Admission's own check); Active <-> Notice Period never changes the count.
        if (new_status in Resident.COUNTS_TOWARD_PLAN_LIMIT
                and before_status not in Resident.COUNTS_TOWARD_PLAN_LIMIT):
            check_resident_limit(resident.property)
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

    @transaction.atomic
    def perform_create(self, serializer):
        bed = serializer.validated_data['bed']
        resident = serializer.validated_data['resident']
        with_food = serializer.validated_data['food_preference'] == Admission.FoodPreference.WITH_FOOD

        # Plan limit (PRD §4: checked per property) — Module 13's concern;
        # fail-open when no plan is configured. Checked before any side
        # effect so a blocked check-in leaves the bed/resident untouched.
        check_resident_limit(bed.room.floor.property)

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

        # Check-in creates the resident's initial Allocation (Module 06).
        services.create_initial_allocation(instance)

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


class AllocationViewSet(viewsets.ReadOnlyModelViewSet):
    """Current bed placements (PRD Module 7). Read-only — allocations are
    mutated only through admission (check-in) and transfers, never edited
    directly. Filter `?is_temporary=true` for the temporary-allocation
    dashboard list."""

    serializer_class = AllocationSerializer
    permission_classes = [IsAuthenticated, require_permission('manage_allocations')]
    filterset_fields = ['resident', 'is_temporary']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Allocation.objects.none()
        ids = visible_property_ids(self.request.user)
        return Allocation.objects.filter(
            allocated_bed__room__floor__property_id__in=ids
        ).select_related('resident', 'allocated_bed__room')


class TransferViewSet(viewsets.ModelViewSet):
    """Transfer history + performing a transfer (PRD Module 7). Creating a
    transfer moves the resident's Allocation to the new bed and records the
    before/after here. No update/delete — the history is append-only."""

    permission_classes = [IsAuthenticated, require_permission('manage_allocations')]
    http_method_names = ['get', 'post']
    filterset_fields = ['resident', 'is_temporary']

    def get_serializer_class(self):
        return TransferCreateSerializer if self.action == 'create' else TransferSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Transfer.objects.none()
        ids = visible_property_ids(self.request.user)
        return Transfer.objects.filter(
            new_bed__room__floor__property_id__in=ids
        ).select_related('resident', 'previous_bed', 'new_bed')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        transfer = services.perform_transfer(
            allocation=data['allocation'],
            new_bed=data['new_bed'],
            transfer_date=data['transfer_date'],
            is_temporary=data['is_temporary'],
            reason=data['reason'],
            new_rent=data['new_rent'],
            expected_move_date=data['expected_move_date'],
            temporary_note=data['temporary_note'],
            actor=request.user,
            request=request,
        )
        return Response(TransferSerializer(transfer).data, status=status.HTTP_201_CREATED)


class VacateViewSet(viewsets.ModelViewSet):
    """Notice-to-vacate + move-out settlement (PRD Module 11 'Vacating
    Workflow'). `create` = give notice (Active -> Notice Period); `finalize`
    = the move-out settlement (Notice Period -> Vacated, bed freed, refund
    computed). `manage_deposits` excludes Receptionist."""

    permission_classes = [IsAuthenticated, require_permission('manage_deposits')]
    http_method_names = ['get', 'post']
    filterset_fields = ['resident']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Vacate.objects.none()
        ids = visible_property_ids(self.request.user)
        return Vacate.objects.filter(resident__property_id__in=ids).select_related('resident', 'settled_by')

    def get_serializer_class(self):
        if self.action == 'create':
            return VacateGiveNoticeSerializer
        return VacateSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        vacate = services.give_notice(actor=request.user, request=request, **serializer.validated_data)
        return Response(VacateSerializer(vacate).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def finalize(self, request, pk=None):
        vacate = self.get_object()
        if vacate.is_settled:
            raise ValidationError(
                {'detail': _('This vacate has already been settled.')}, code='already_settled'
            )
        serializer = VacateFinalizeSerializer(data=request.data, context={'vacate': vacate})
        serializer.is_valid(raise_exception=True)
        vacate = services.finalize_vacate(
            vacate=vacate, actor=request.user, request=request, **serializer.validated_data
        )
        return Response(VacateSerializer(vacate).data)


class AbscondedRecordViewSet(viewsets.ModelViewSet):
    """Marking a resident absconded + dues write-off (PRD Module 11
    'Absconded Resident Workflow'). `manage_deposits` excludes Receptionist."""

    permission_classes = [IsAuthenticated, require_permission('manage_deposits')]
    http_method_names = ['get', 'post']
    filterset_fields = ['resident', 'dues_recovery_status']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return AbscondedRecord.objects.none()
        ids = visible_property_ids(self.request.user)
        return AbscondedRecord.objects.filter(
            resident__property_id__in=ids
        ).select_related('resident', 'marked_by', 'dues_written_off_by')

    def get_serializer_class(self):
        if self.action == 'create':
            return AbscondedRecordCreateSerializer
        return AbscondedRecordSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        record = services.mark_absconded(actor=request.user, request=request, **serializer.validated_data)
        return Response(AbscondedRecordSerializer(record).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='write-off')
    def write_off(self, request, pk=None):
        record = self.get_object()
        if record.dues_recovery_status == AbscondedRecord.DuesRecoveryStatus.WRITTEN_OFF:
            raise ValidationError(
                {'detail': _('Dues have already been written off.')}, code='already_written_off'
            )
        serializer = DuesWriteOffSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = services.write_off_dues(
            absconded_record=record, note=serializer.validated_data['note'],
            actor=request.user, request=request,
        )
        return Response(AbscondedRecordSerializer(record).data)


class BlacklistEntryViewSet(viewsets.ModelViewSet):
    """Tenant-wide blacklist (PRD Module 11 'Blacklisting') — deliberately NOT
    property-scoped: visible across every property under the tenant so a
    Manager elsewhere in the tenant is warned. `create` = confirm blacklist
    (never automatic). `manage_deposits` excludes Receptionist."""

    permission_classes = [IsAuthenticated, require_permission('manage_deposits')]
    http_method_names = ['get', 'post']
    filterset_fields = ['resident', 'phone']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return BlacklistEntry.objects.none()
        return BlacklistEntry.objects.select_related('resident', 'confirmed_by')

    def get_serializer_class(self):
        if self.action == 'create':
            return BlacklistConfirmSerializer
        return BlacklistEntrySerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        entry = services.confirm_blacklist(actor=request.user, request=request, **serializer.validated_data)
        return Response(BlacklistEntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def check(self, request):
        """Tenant-wide lookup used before registering a new resident (PRD:
        'system shows a warning' — informational, does not block creation)."""
        phone = request.query_params.get('phone', '').strip()
        aadhaar_number = request.query_params.get('aadhaar_number', '').strip()
        if not phone and not aadhaar_number:
            return Response([])

        query = Q()
        if phone:
            query |= Q(phone=phone)
        if aadhaar_number:
            query |= Q(aadhaar_number=aadhaar_number)
        entries = self.get_queryset().filter(query)
        return Response(BlacklistEntrySerializer(entries, many=True).data)
