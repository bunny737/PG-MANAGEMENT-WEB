from datetime import date

from drf_spectacular.utils import OpenApiParameter, extend_schema
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.fields import SkipField, empty
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import log as audit_log
from apps.core.idempotency import idempotency_key, key_reused
from apps.core.periods import local_today, month_end, month_start, parse_date, parse_month
from apps.core.permissions import require_permission, require_permission_by_method
from apps.notifications.tasks import send_invoice_issued_email_task
from apps.properties.services import scoped_property_ids, visible_property_ids
from apps.residents.models import Resident

from . import receipts, selectors, services
from .filters import DiscountFilter, InvoiceFilter, PaymentFilter
from .models import Discount, Invoice, InvoiceLineItem, Payment
from .schema import CashMovementsResponseSerializer, ReceiptResponseSerializer
from .serializers import (
    DiscountSerializer,
    InvoiceBulkGenerateSerializer,
    InvoiceGenerateSerializer,
    InvoiceLineItemWriteSerializer,
    InvoiceSerializer,
    InvoiceUpdateSerializer,
    PaymentSerializer,
    PaymentWriteSerializer,
)


class DiscountViewSet(viewsets.ModelViewSet):
    """Per-resident discounts (PRD Module 8). `manage_discounts` excludes
    Receptionist. No hard delete — end a discount by setting `valid_until`
    (consistent with the rest of the platform's financial-record handling)."""

    serializer_class = DiscountSerializer
    permission_classes = [IsAuthenticated, require_permission_by_method('view_finance', 'manage_discounts')]
    http_method_names = ['get', 'post', 'patch']
    filterset_class = DiscountFilter

    @staticmethod
    def _lock_resident(resident_id):
        # Serialize all discount writes for one resident: the serializer's
        # "no overlapping window" check (invariant 4 — a single discount line,
        # no silent stacking) is a read-then-write that races without this.
        if resident_id:
            list(Resident.objects.select_for_update().filter(pk=resident_id))

    def create(self, request, *args, **kwargs):
        with transaction.atomic():
            self._lock_resident(request.data.get('resident'))
            return super().create(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        with transaction.atomic():
            self._lock_resident(self.get_object().resident_id)
            return super().partial_update(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Discount.objects.none()
        ids = visible_property_ids(self.request.user)
        return (
            Discount.objects.filter(resident__property_id__in=ids)
            .select_related('resident__property', 'resident__allocation__allocated_bed__room', 'approved_by')
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

    permission_classes = [IsAuthenticated, require_permission_by_method('view_finance', 'manage_invoices')]
    http_method_names = ['get', 'post', 'patch', 'delete']
    filterset_class = InvoiceFilter

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Invoice.objects.none()
        ids = visible_property_ids(self.request.user)
        return (
            Invoice.objects.filter(resident__property_id__in=ids)
            .select_related('resident__property', 'resident__allocation__allocated_bed__room')
            .prefetch_related('line_items', 'payments')
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
    @transaction.atomic
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
        # The advance (rent paid upfront at admission) settles the first invoice.
        services.apply_advance_to_first_invoice(invoice=invoice, actor=request.user, request=request)
        invoice.refresh_from_db()  # the payment may have changed its status
        # Module 14: "Invoice generated notification to resident" (PRD).
        # Issuing (not the draft) is when it becomes a real obligation the
        # resident should be told about — see the Module 14 spec's Decisions.
        transaction.on_commit(lambda: send_invoice_issued_email_task.delay(str(invoice.id)))
        return Response(InvoiceSerializer(invoice).data)

    @action(detail=False, methods=['get'])
    def outstanding(self, request):
        """Invoices with money still owed (PRD Module 10 "Outstanding dues view
        across all residents"). Fully-paid invoices are `paid` and drop out;
        drafts are excluded (not yet owed)."""
        # Same definition as ?status=outstanding and the analytics
        # outstanding_total (apps/billing/selectors.py); also honours the
        # list filters (?property=, ?resident=, ...).
        invoices = selectors.outstanding(self.filter_queryset(self.get_queryset()))
        return Response(InvoiceSerializer(invoices, many=True).data)

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
            try:
                created.append(services.generate_invoice(
                    resident=resident, period_start=data['period_start'],
                    period_end=data['period_end'], due_date=data['due_date'],
                    actor=request.user, request=request,
                ))
            except ValidationError:
                # A concurrent run (or single-generate) already invoiced this
                # resident for the period — unique_invoice_per_resident_period
                # caught it. Skip, don't abort the batch.
                continue
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


class PaymentViewSet(viewsets.ModelViewSet):
    """Manually-recorded payments against invoices (PRD Module 10). Razorpay is
    never used here — resident payments are always recorded by hand. A payment
    is a financial record: correct a mistake by deleting and re-recording,
    there is no edit (`patch`)."""

    permission_classes = [IsAuthenticated, require_permission_by_method('view_finance', 'manage_payments')]
    http_method_names = ['get', 'post', 'delete']
    filterset_class = PaymentFilter

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Payment.objects.none()
        ids = visible_property_ids(self.request.user)
        return (
            Payment.objects.filter(invoice__resident__property_id__in=ids)
            .select_related(
                'invoice__resident__property', 'invoice__resident__allocation__allocated_bed__room',
                'recorded_by',
            )
        )

    def get_serializer_class(self):
        if self.action == 'create':
            return PaymentWriteSerializer
        return PaymentSerializer

    @extend_schema(
        parameters=[OpenApiParameter(
            'Idempotency-Key', str, OpenApiParameter.HEADER, required=False,
            description='<= 100 chars; one per user intent. A retry with the same key and body '
                        'returns 200 with `Idempotent-Replayed: true` and the original payment.',
        )],
    )
    def create(self, request, *args, **kwargs):
        key = idempotency_key(request)
        if key:
            # A retry of a request that already succeeded: answer with the
            # original payment *before* validation, which would otherwise
            # reject it (the invoice may now be fully paid).
            replay = self._replay(request, key)
            if replay is not None:
                return replay
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        payment = services.record_payment(
            actor=request.user, request=request, idempotency_key=key, **serializer.validated_data
        )
        return self._payment_response(payment, replayed=payment.replayed)

    def _replay(self, request, key):
        existing = self.get_queryset().filter(idempotency_key=key).first()
        if existing is None:
            return None
        # Parse with the serializer's own fields (so "5000" == "5000.00" and
        # date formats match) but skip its business rules — a replay must
        # not be re-judged against the invoice's current balance.
        fields = PaymentWriteSerializer().fields
        inputs = {}
        try:
            for name in ('amount', 'payment_date', 'payment_mode'):
                inputs[name] = fields[name].run_validation(fields[name].get_value(request.data))
            reference = fields['reference'].get_value(request.data)
            inputs['reference'] = '' if reference is empty else fields['reference'].run_validation(reference)
        except (ValidationError, SkipField):
            raise key_reused()
        if not services.payment_matches(existing, invoice_id=request.data.get('invoice'), **inputs):
            raise key_reused()
        return self._payment_response(existing, replayed=True)

    def _payment_response(self, payment, *, replayed):
        payment = self.get_queryset().get(pk=payment.pk)
        response = Response(
            PaymentSerializer(payment).data,
            status=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        )
        if replayed:
            response['Idempotent-Replayed'] = 'true'
        return response

    def perform_destroy(self, instance):
        services.delete_payment(payment=instance, actor=self.request.user, request=self.request)

    @extend_schema(
        parameters=[OpenApiParameter('filetype', str, description='"pdf" for the printable receipt; default JSON.')],
        responses=ReceiptResponseSerializer,
    )
    @action(detail=True, methods=['get'])
    def receipt(self, request, pk=None):
        """Receipt for one payment (PRD Module 10, D4). JSON by default (the
        original contract); `?filetype=pdf` renders the printable receipt
        for the share sheet."""
        payment = self.get_object()
        data = receipts.receipt_data(payment)
        if request.query_params.get('filetype', '').lower() == 'pdf':
            return receipts.receipt_pdf_response(payment, data)
        return Response(receipts.receipt_json(data))


class CashMovementView(APIView):
    """Cash movements for a date range (D3) — the drill-down behind the
    analytics `cash_collected` figure, which this list always sums to.
    Payments are (+). Rent refunds would be (−), but v1 has none (owner
    decision 2026-10-16), so refunds_paid is always 0 here."""

    permission_classes = [IsAuthenticated, require_permission('view_finance')]

    @extend_schema(
        parameters=[
            OpenApiParameter('property', str, description='Property UUID; default is every assigned property.'),
            OpenApiParameter('month', str, description='YYYY-MM; default is the current month.'),
            OpenApiParameter('from', str, description='YYYY-MM-DD; overrides the month start.'),
            OpenApiParameter('to', str, description='YYYY-MM-DD; overrides the month end.'),
        ],
        responses=CashMovementsResponseSerializer,
    )
    def get(self, request):
        params = request.query_params
        first = parse_month(params.get('month'), default=month_start(local_today()))
        start = parse_date(params.get('from'), param='from') or first
        end = parse_date(params.get('to'), param='to') or month_end(first)
        if end < start:
            raise ValidationError({'to': [_('"to" cannot be before "from".')]}, code='invalid_date_range')

        property_ids = scoped_property_ids(request.user, params.get('property'))
        payments = (
            Payment.objects.filter(
                invoice__resident__property_id__in=property_ids, payment_date__range=(start, end),
            )
            .select_related('invoice__resident__property')
            .order_by('-payment_date', '-created_at')
        )
        results = [
            {
                'type': 'payment',
                'id': str(p.id),
                'date': p.payment_date,
                'amount': str(p.amount),
                'receipt_number': p.receipt_number,
                'payment_mode': p.payment_mode,
                'invoice': str(p.invoice_id),
                'resident': str(p.invoice.resident_id),
                'resident_name': str(p.invoice.resident),
                'property': str(p.invoice.resident.property_id),
                'property_name': p.invoice.resident.property.name,
            }
            for p in payments
        ]
        gross = sum((p.amount for p in payments), selectors.ZERO)
        refunds = selectors.ZERO
        return Response({
            'from': start, 'to': end,
            'gross_receipts': str(gross), 'refunds_paid': str(refunds),
            'total': str(gross - refunds),
            'count': len(results),
            'results': results,
        })
