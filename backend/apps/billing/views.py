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
from apps.notices import credits as food_credits
from apps.properties.services import scoped_property_ids, visible_property_ids
from apps.residents.models import Resident

from . import receipts, selectors, services
from .filters import DiscountFilter, InvoiceFilter, PaymentFilter
from .models import Discount, Invoice, InvoiceLineItem, Payment
from .schema import (
    CashMovementsResponseSerializer,
    InvoiceBulkIssueResponseSerializer,
    ReceiptResponseSerializer,
)
from .serializers import (
    DiscountSerializer,
    InvoiceBulkGenerateSerializer,
    InvoiceBulkIssueSerializer,
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
        services.require_draft(invoice)

    def _locked_draft(self):
        """The scoped invoice, row-locked and re-checked as a draft. Callers
        run in a transaction, so an edit can't interleave with an issue (manual
        or by the automatic-billing sweep). Settings is locked first (the
        global billing order), which also serializes the draft's food-holiday
        credits (Module 24) with every other credit change in the property."""
        invoice = self.get_object()
        services.lock_property_settings(invoice.resident.property_id, invoice.tenant_id)
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        self._require_draft(invoice)
        return invoice

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

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        invoice = self._locked_draft()
        serializer = self.get_serializer(invoice, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        extra = {}
        if 'due_date' in serializer.validated_data:
            # A due date the owner typed is kept as-is on issue, never
            # recomputed from the issue date.
            extra['due_date_policy'] = Invoice.DueDatePolicy.MANUAL
        serializer.save(**extra)
        return self._fresh_response(invoice)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        instance = self._locked_draft()
        audit_log.record(
            action='invoice.deleted', actor=self.request.user, obj=instance,
            before={'resident': str(instance.resident_id), 'period_start': instance.period_start.isoformat()},
            request=self.request,
        )
        # Its food-holiday credits go back to pending first (their lines are
        # PROTECTed), then are offered to the resident's other drafts.
        food_credits.release_invoice(instance, actor=request.user, request=request)
        resident = instance.resident
        instance.delete()
        food_credits.allocate_pending(resident, actor=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def issue(self, request, pk=None):
        invoice = self.get_object()
        services.issue_invoice(invoice_id=invoice.pk, actor=request.user, request=request)
        return self._fresh_response(invoice)

    @extend_schema(request=InvoiceBulkIssueSerializer, responses=InvoiceBulkIssueResponseSerializer)
    @action(detail=False, methods=['post'], url_path='bulk-issue')
    def bulk_issue(self, request):
        """Confirm (issue) many drafts at once — e.g. everything in the Needs
        review list. Each invoice is issued in its own transaction; one that
        fails doesn't stop the rest, and the response says what happened to
        each id."""
        serializer = InvoiceBulkIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        visible = set(self.get_queryset().filter(pk__in=serializer.validated_data['ids']).values_list('pk', flat=True))
        results = []
        for invoice_id in serializer.validated_data['ids']:
            if invoice_id not in visible:
                results.append({'id': str(invoice_id), 'result': 'not_found'})
                continue
            try:
                services.issue_invoice(invoice_id=invoice_id, actor=request.user, request=request)
            except ValidationError as exc:
                code = exc.get_codes()
                if isinstance(code, dict):
                    code = code.get('detail', 'invalid')
                if isinstance(code, list):
                    code = code[0] if code else 'invalid'
                results.append({'id': str(invoice_id), 'result': str(code)})
                continue
            results.append({'id': str(invoice_id), 'result': 'issued'})
        return Response({
            'issued': sum(1 for row in results if row['result'] == 'issued'),
            'results': results,
        })

    @action(detail=True, methods=['post'], url_path='hold-auto-issue')
    def hold_auto_issue(self, request, pk=None):
        invoice = self.get_object()
        services.hold_auto_issue(invoice_id=invoice.pk, actor=request.user, request=request)
        return self._fresh_response(invoice)

    @action(detail=True, methods=['post'], url_path='resume-auto-issue')
    def resume_auto_issue(self, request, pk=None):
        invoice = self.get_object()
        services.resume_auto_issue(invoice_id=invoice.pk, actor=request.user, request=request)
        return self._fresh_response(invoice)

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
        overlapping = 0
        for resident in residents:
            if services.resident_has_invoice_for_period(resident, data['period_start']):
                continue
            try:
                created.append(services.generate_invoice(
                    resident=resident, period_start=data['period_start'],
                    period_end=data['period_end'], due_date=data['due_date'],
                    actor=request.user, request=request,
                ))
            except services.InvoiceConflict as exc:
                # Already invoiced for (part of) this period — by a concurrent
                # run, a single generate, or automatic billing. Skip, don't
                # abort the batch.
                if 'overlapping_invoice' in str(exc.get_codes()):
                    overlapping += 1
                continue
        return Response(
            {'created': len(created), 'skipped_overlapping': overlapping,
             'invoices': InvoiceSerializer(created, many=True).data},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='line-items')
    @transaction.atomic
    def add_line_item(self, request, pk=None):
        invoice = self._locked_draft()
        serializer = InvoiceLineItemWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        InvoiceLineItem.objects.create(
            tenant_id=invoice.tenant_id, invoice=invoice, **serializer.validated_data
        )
        audit_log.record(
            action='invoice.line_item_added', actor=request.user, obj=invoice,
            after=serializer.data, request=request,
        )
        self._rebalance_credits(invoice)
        return self._fresh_response(invoice, status.HTTP_201_CREATED)

    def _rebalance_credits(self, invoice):
        """After an owner line change: keep the draft's total above zero, then
        offer pending food-holiday credits again (the total may have grown)."""
        food_credits.rebalance(invoice, actor=self.request.user, request=self.request)
        food_credits.allocate_pending(invoice.resident, actor=self.request.user, request=self.request)

    @action(detail=True, methods=['patch', 'delete'], url_path=r'line-items/(?P<line_pk>[0-9a-f-]+)')
    @transaction.atomic
    def modify_line_item(self, request, pk=None, line_pk=None):
        invoice = self._locked_draft()
        line = invoice.line_items.filter(pk=line_pk).first()
        if line is None:
            raise NotFound(_('Line item not found.'))

        if line.line_type == InvoiceLineItem.LineType.FOOD_HOLIDAY:
            # System-owned (Module 24): deleting it is the per-resident
            # waiver; it is never edited by hand.
            if request.method != 'DELETE':
                raise ValidationError(
                    {'detail': _('A food holiday credit cannot be edited. Remove it to waive it.')},
                    code='line_locked',
                )
            food_credits.waive(line.food_holiday_credit, actor=request.user, request=request)
            return self._fresh_response(invoice)

        if request.method == 'DELETE':
            audit_log.record(
                action='invoice.line_item_removed', actor=request.user, obj=invoice,
                before={'label': line.label, 'amount': str(line.amount)}, request=request,
            )
            line.delete()
            self._rebalance_credits(invoice)
            return self._fresh_response(invoice)

        serializer = InvoiceLineItemWriteSerializer(line, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit_log.record(
            action='invoice.line_item_updated', actor=request.user, obj=invoice,
            after=serializer.data, request=request,
        )
        self._rebalance_credits(invoice)
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
