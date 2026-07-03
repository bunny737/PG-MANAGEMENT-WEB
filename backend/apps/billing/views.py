from datetime import date

from django.utils.translation import gettext_lazy as _
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit import log as audit_log
from apps.core.permissions import require_permission
from apps.properties.services import visible_property_ids
from apps.residents.models import Resident

from . import services
from .models import Discount, Invoice, InvoiceLineItem
from .serializers import (
    DiscountSerializer,
    InvoiceBulkGenerateSerializer,
    InvoiceGenerateSerializer,
    InvoiceLineItemWriteSerializer,
    InvoiceSerializer,
    InvoiceUpdateSerializer,
)


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


class InvoiceViewSet(viewsets.ModelViewSet):
    """Invoices (PRD Module 9). Generation builds the accommodation + discount
    lines; ad-hoc charges are added as line items while the invoice is a draft.
    `manage_invoices` excludes Receptionist. Drafts are deletable (regenerate);
    once issued an invoice is a financial record and cannot be edited/deleted."""

    permission_classes = [IsAuthenticated, require_permission('manage_invoices')]
    http_method_names = ['get', 'post', 'patch', 'delete']
    filterset_fields = ['resident', 'status', 'billing_mode']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Invoice.objects.none()
        ids = visible_property_ids(self.request.user)
        return (
            Invoice.objects.filter(resident__property_id__in=ids)
            .select_related('resident').prefetch_related('line_items')
        )

    def get_serializer_class(self):
        if self.action == 'create':
            return InvoiceGenerateSerializer
        if self.action == 'partial_update':
            return InvoiceUpdateSerializer
        return InvoiceSerializer

    @staticmethod
    def _require_draft(invoice):
        if invoice.status != Invoice.Status.DRAFT:
            raise ValidationError(
                {'detail': _('Only draft invoices can be modified.')}, code='invoice_not_draft'
            )

    def _fresh_response(self, invoice, http_status=status.HTTP_200_OK):
        # Re-fetch so the prefetched line_items cache reflects the mutation.
        invoice = self.get_queryset().get(pk=invoice.pk)
        return Response(InvoiceSerializer(invoice).data, status=http_status)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice = services.generate_invoice(
            actor=request.user, request=request, **serializer.validated_data
        )
        return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        invoice = self.get_object()
        self._require_draft(invoice)
        serializer = self.get_serializer(invoice, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(InvoiceSerializer(invoice).data)

    def perform_destroy(self, instance):
        self._require_draft(instance)
        audit_log.record(
            action='invoice.deleted', actor=self.request.user, obj=instance,
            before={'resident': str(instance.resident_id), 'period_start': instance.period_start.isoformat()},
            request=self.request,
        )
        instance.delete()

    @action(detail=True, methods=['post'])
    def issue(self, request, pk=None):
        invoice = self.get_object()
        self._require_draft(invoice)
        invoice.status = Invoice.Status.ISSUED
        invoice.issue_date = date.today()
        invoice.save(update_fields=['status', 'issue_date', 'updated_at'])
        audit_log.record(
            action='invoice.issued', actor=request.user, obj=invoice,
            after={'status': invoice.status, 'issue_date': invoice.issue_date.isoformat()},
            request=request,
        )
        return Response(InvoiceSerializer(invoice).data)

    @action(detail=False, methods=['post'], url_path='bulk-generate')
    def bulk_generate(self, request):
        serializer = InvoiceBulkGenerateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        prop = data['property']

        residents = Resident.objects.filter(
            property=prop,
            status__in=(Resident.Status.ACTIVE, Resident.Status.NOTICE_PERIOD),
            allocation__isnull=False,
        )
        created = []
        for resident in residents:
            if services.resident_has_invoice_for_period(resident, data['period_start']):
                continue
            created.append(services.generate_invoice(
                resident=resident, period_start=data['period_start'],
                period_end=data['period_end'], due_date=data['due_date'],
                actor=request.user, request=request,
            ))
        return Response(
            {'created': len(created), 'invoices': InvoiceSerializer(created, many=True).data},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='line-items')
    def add_line_item(self, request, pk=None):
        invoice = self.get_object()
        self._require_draft(invoice)
        serializer = InvoiceLineItemWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        InvoiceLineItem.objects.create(
            tenant_id=invoice.tenant_id, invoice=invoice, **serializer.validated_data
        )
        audit_log.record(
            action='invoice.line_item_added', actor=request.user, obj=invoice,
            after=serializer.data, request=request,
        )
        return self._fresh_response(invoice, status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'], url_path=r'line-items/(?P<line_pk>[0-9a-f-]+)')
    def modify_line_item(self, request, pk=None, line_pk=None):
        invoice = self.get_object()
        self._require_draft(invoice)
        line = invoice.line_items.filter(pk=line_pk).first()
        if line is None:
            raise NotFound(_('Line item not found.'))

        if request.method == 'DELETE':
            audit_log.record(
                action='invoice.line_item_removed', actor=request.user, obj=invoice,
                before={'label': line.label, 'amount': str(line.amount)}, request=request,
            )
            line.delete()
            return self._fresh_response(invoice)

        serializer = InvoiceLineItemWriteSerializer(line, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit_log.record(
            action='invoice.line_item_updated', actor=request.user, obj=invoice,
            after=serializer.data, request=request,
        )
        return self._fresh_response(invoice)
