from django.utils.translation import gettext_lazy as _
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit import log as audit_log
from apps.core.permissions import require_permission
from apps.properties.services import visible_property_ids

from .models import Complaint, ComplaintComment, Visitor
from .serializers import (
    ComplaintAssignSerializer,
    ComplaintCommentSerializer,
    ComplaintCommentWriteSerializer,
    ComplaintSerializer,
    ComplaintStatusUpdateSerializer,
    ComplaintUpdateSerializer,
    VisitorCheckOutSerializer,
    VisitorSerializer,
)


class ComplaintViewSet(viewsets.ModelViewSet):
    """Complaints (PRD Module 12). `manage_complaints` excludes Receptionist
    and Resident — see the Module 11 spec's Decisions for why true resident
    self-service ('raise_complaint') isn't wired up yet (no resident login
    exists; Module 04 already deferred that). Workflow is an exact linear
    graph: Open -> Assigned -> In Progress -> Resolved -> Closed."""

    permission_classes = [IsAuthenticated, require_permission('manage_complaints')]
    http_method_names = ['get', 'post', 'patch']
    filterset_fields = ['resident', 'status', 'priority', 'category', 'assigned_to']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Complaint.objects.none()
        ids = visible_property_ids(self.request.user)
        return (
            Complaint.objects.filter(resident__property_id__in=ids)
            .select_related('resident', 'assigned_to', 'raised_by')
            .prefetch_related('comments')
        )

    def get_serializer_class(self):
        if self.action == 'partial_update':
            return ComplaintUpdateSerializer
        return ComplaintSerializer

    @staticmethod
    def _require_open(complaint):
        if complaint.status != Complaint.Status.OPEN:
            raise ValidationError(
                {'detail': _('Only an open complaint can be edited or assigned.')}, code='complaint_not_open'
            )

    def perform_create(self, serializer):
        instance = serializer.save(tenant_id=self.request.user.tenant_id, raised_by=self.request.user)
        audit_log.record(
            action='complaint.created', actor=self.request.user, obj=instance,
            after={'resident': str(instance.resident_id), 'category': instance.category,
                   'priority': instance.priority},
            request=self.request,
        )

    def partial_update(self, request, *args, **kwargs):
        complaint = self.get_object()
        self._require_open(complaint)
        before = {
            'category': complaint.category, 'priority': complaint.priority,
            'description': complaint.description,
        }
        serializer = self.get_serializer(complaint, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit_log.record(
            action='complaint.updated', actor=request.user, obj=complaint,
            before=before, after={
                'category': complaint.category, 'priority': complaint.priority,
                'description': complaint.description,
            },
            request=request,
        )
        return Response(ComplaintSerializer(complaint).data)

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        complaint = self.get_object()
        self._require_open(complaint)
        serializer = ComplaintAssignSerializer(data=request.data, context={'complaint': complaint})
        serializer.is_valid(raise_exception=True)

        complaint.assigned_to = serializer.validated_data['assigned_to']
        complaint.status = Complaint.Status.ASSIGNED
        complaint.save(update_fields=['assigned_to', 'status', 'updated_at'])

        audit_log.record(
            action='complaint.assigned', actor=request.user, obj=complaint,
            after={'assigned_to': str(complaint.assigned_to_id), 'status': complaint.status},
            request=request,
        )
        return Response(ComplaintSerializer(complaint).data)

    # Named change_status, not "status" — see Module 03's PropertySettings
    # write-up on why a method named after a DRF-internal attribute breaks
    # exception handling for the whole viewset.
    @action(detail=True, methods=['patch'], url_path='status', url_name='status')
    def change_status(self, request, pk=None):
        complaint = self.get_object()
        before_status = complaint.status
        serializer = ComplaintStatusUpdateSerializer(complaint, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        audit_log.record(
            action='complaint.status_changed', actor=request.user, obj=instance,
            before={'status': before_status}, after={'status': instance.status},
            request=request,
        )
        return Response(ComplaintSerializer(instance).data)

    @action(detail=True, methods=['get', 'post'], url_path='comments', url_name='comments')
    def comments_thread(self, request, pk=None):
        complaint = self.get_object()
        if request.method == 'GET':
            return Response(ComplaintCommentSerializer(complaint.comments.all(), many=True).data)

        serializer = ComplaintCommentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = ComplaintComment.objects.create(
            tenant_id=complaint.tenant_id, complaint=complaint, author=request.user,
            **serializer.validated_data,
        )
        audit_log.record(
            action='complaint.comment_added', actor=request.user, obj=complaint,
            after={'body': comment.body}, request=request,
        )
        return Response(ComplaintCommentSerializer(comment).data, status=status.HTTP_201_CREATED)


class VisitorViewSet(viewsets.ModelViewSet):
    """Visitor entry/exit log (PRD Module 13). `manage_visitors` is the one
    permission in the whole matrix that includes Receptionist — front desk
    logging visitor entry/exit is their primary job. No PATCH/DELETE — a
    logged entry is corrected via the dedicated `check-out`/`confirm`
    actions, not raw edits."""

    serializer_class = VisitorSerializer
    permission_classes = [IsAuthenticated, require_permission('manage_visitors')]
    http_method_names = ['get', 'post']
    filterset_fields = ['resident', 'mobile_number']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Visitor.objects.none()
        ids = visible_property_ids(self.request.user)
        return (
            Visitor.objects.filter(resident__property_id__in=ids)
            .select_related('resident', 'logged_by', 'checked_out_by', 'approved_by')
        )

    def perform_create(self, serializer):
        instance = serializer.save(tenant_id=self.request.user.tenant_id, logged_by=self.request.user)
        audit_log.record(
            action='visitor.logged', actor=self.request.user, obj=instance,
            after={'resident': str(instance.resident_id), 'visitor_name': instance.visitor_name,
                   'entry_time': instance.entry_time.isoformat()},
            request=self.request,
        )

    @action(detail=True, methods=['post'], url_path='check-out', url_name='check-out')
    def check_out(self, request, pk=None):
        visitor = self.get_object()
        if not visitor.is_checked_in:
            raise ValidationError(
                {'detail': _('This visitor has already checked out.')}, code='already_checked_out'
            )
        serializer = VisitorCheckOutSerializer(data=request.data, context={'visitor': visitor})
        serializer.is_valid(raise_exception=True)

        visitor.exit_time = serializer.validated_data['exit_time']
        visitor.checked_out_by = request.user
        visitor.save(update_fields=['exit_time', 'checked_out_by', 'updated_at'])

        audit_log.record(
            action='visitor.checked_out', actor=request.user, obj=visitor,
            after={'exit_time': visitor.exit_time.isoformat()}, request=request,
        )
        return Response(VisitorSerializer(visitor).data)

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Optional Owner/Manager confirmation layered on top of the front
        desk's own entry (PRD: 'with Owner/Manager confirmation if
        required') — see the Module 12 spec's Decisions for why this is an
        advisory stamp, not a hard gate blocking entry."""
        visitor = self.get_object()
        if visitor.approved_by_id is not None:
            raise ValidationError(
                {'detail': _('This visitor has already been confirmed.')}, code='already_confirmed'
            )
        visitor.approved_by = request.user
        visitor.save(update_fields=['approved_by', 'updated_at'])

        audit_log.record(
            action='visitor.confirmed', actor=request.user, obj=visitor,
            after={'approved_by': str(request.user.id)}, request=request,
        )
        return Response(VisitorSerializer(visitor).data)
