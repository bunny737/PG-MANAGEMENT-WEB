import django_filters
from drf_spectacular.utils import OpenApiParameter, extend_schema
from django.conf import settings
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit import log as audit_log
from apps.core.exceptions import Conflict
from apps.core.idempotency import idempotency_key
from apps.core.periods import local_today, month_end, month_key, month_start, parse_month
from apps.core.permissions import require_permission_by_method
from apps.core.storage import signed_url
from apps.properties.services import scoped_property_ids, visible_property_ids

from . import services
from .models import Expense, ExpenseCategory
from .schema import ExpenseAttachmentResponseSerializer, ExpenseSummaryResponseSerializer
from .serializers import ExpenseCategorySerializer, ExpenseSerializer


class ExpenseFilter(django_filters.FilterSet):
    property = django_filters.UUIDFilter(field_name='property_id')
    category = django_filters.UUIDFilter(field_name='category_id')
    payment_mode = django_filters.ChoiceFilter(choices=Expense.Mode.choices)
    month = django_filters.CharFilter(method='filter_month')
    search = django_filters.CharFilter(method='filter_search')

    class Meta:
        model = Expense
        fields = ['property', 'category', 'payment_mode', 'month', 'search']

    def filter_month(self, queryset, name, value):
        first = parse_month(value)
        return queryset.filter(date__range=(first, month_end(first)))

    def filter_search(self, queryset, name, value):
        value = (value or '').strip()
        if not value:
            return queryset
        return queryset.filter(Q(note__icontains=value) | Q(category__name__icontains=value))


ExpenseFilter.base_filters['from'] = django_filters.DateFilter(field_name='date', lookup_expr='gte')
ExpenseFilter.base_filters['to'] = django_filters.DateFilter(field_name='date', lookup_expr='lte')


class ExpenseViewSet(viewsets.ModelViewSet):
    """PG expenses (UX roadmap D5, Module 20). Reads need `view_expenses`,
    writes `manage_expenses`; both are scoped to the caller's properties.
    DELETE is a soft delete. POST accepts an Idempotency-Key header."""

    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated, require_permission_by_method('view_expenses', 'manage_expenses')]
    http_method_names = ['get', 'post', 'patch', 'put', 'delete']
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filterset_class = ExpenseFilter

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Expense.objects.none()
        ids = visible_property_ids(self.request.user)
        return (
            services.live_expenses().filter(property_id__in=ids)
            .select_related('property', 'category', 'created_by')
        )

    def update(self, request, *args, **kwargs):
        if not kwargs.get('partial'):
            raise MethodNotAllowed(request.method)  # PUT is only for the attachment
        return super().update(request, *args, **kwargs)

    @extend_schema(
        parameters=[OpenApiParameter(
            'Idempotency-Key', str, OpenApiParameter.HEADER, required=False,
            description='<= 100 chars; one per user intent. A retry with the same key, fields and '
                        'attachment returns 200 with `Idempotent-Replayed: true` and the original expense.',
        )],
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        attachment = data.pop('attachment', None)
        expense = services.create_expense(
            data=data, attachment=attachment, actor=request.user, request=request,
            idempotency_key=idempotency_key(request),
        )
        response = Response(
            self.get_serializer(self.get_queryset().get(pk=expense.pk)).data,
            status=status.HTTP_200_OK if expense.replayed else status.HTTP_201_CREATED,
        )
        if expense.replayed:
            response['Idempotent-Replayed'] = 'true'
        return response

    def perform_update(self, serializer):
        data = dict(serializer.validated_data)
        if 'attachment' in data:
            raise ValidationError(
                {'attachment': [_('Use PUT /expenses/{id}/attachment/ to replace the file.')]},
                code='use_attachment_endpoint',
            )
        services.update_expense(expense=serializer.instance, data=data, actor=self.request.user,
                                request=self.request)

    def perform_destroy(self, instance):
        services.delete_expense(expense=instance, actor=self.request.user, request=self.request)

    @extend_schema(
        parameters=[
            OpenApiParameter('property', str, description='Property UUID; default is every assigned property.'),
            OpenApiParameter('month', str, description='YYYY-MM; default is the current month.'),
        ],
        responses=ExpenseSummaryResponseSerializer,
    )
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """{total, count, by_category[]} for ?property=&month= (default this
        month). Same rows as the list with the same filters, so it reconciles."""
        first = parse_month(request.query_params.get('month'), default=month_start(local_today()))
        ids = scoped_property_ids(request.user, request.query_params.get('property'))
        queryset = self.get_queryset().filter(property_id__in=ids, date__range=(first, month_end(first)))
        return Response({'month': month_key(first), 'property': request.query_params.get('property') or None,
                         **services.summary(queryset)})

    @extend_schema(methods=['GET'], responses=ExpenseAttachmentResponseSerializer)
    @extend_schema(methods=['PUT', 'DELETE'], responses=ExpenseSerializer)
    @action(detail=True, methods=['get', 'put', 'delete'], parser_classes=[MultiPartParser, FormParser])
    def attachment(self, request, pk=None):
        """GET a short-lived signed URL; PUT (multipart `attachment`) replaces
        the file; DELETE removes it. JPEG/PNG/WebP/PDF up to the configured size."""
        expense = self.get_object()
        if request.method == 'GET':
            if not expense.attachment:
                raise NotFound(_('This expense has no attachment.'))
            ttl = settings.EXPENSE_ATTACHMENT_URL_TTL_SECONDS
            url = signed_url(expense.attachment, ttl_seconds=ttl)
            return Response({
                'url': request.build_absolute_uri(url),
                'content_type': expense.attachment_content_type,
                'expires_in': ttl,
            })
        if request.method == 'PUT':
            upload = request.FILES.get('attachment')
            if upload is None:
                raise ValidationError({'attachment': [_('A file is required.')]}, code='required')
            services.replace_attachment(expense=expense, upload=upload, actor=request.user, request=request)
        else:
            services.remove_attachment(expense=expense, actor=request.user, request=request)
        return Response(self.get_serializer(expense).data)


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    """Expense categories with stable ids. Built-in ones are seeded on first
    read and are immutable; custom ones can be renamed, archived, or deleted
    while no expense uses them. ?include_archived=true lists archived too."""

    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAuthenticated, require_permission_by_method('view_expenses', 'manage_expenses')]
    http_method_names = ['get', 'post', 'patch', 'delete']
    pagination_class = None

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return ExpenseCategory.objects.none()
        queryset = ExpenseCategory.objects.filter(tenant_id=self.request.user.tenant_id)
        if self.action == 'list' and self.request.query_params.get('include_archived') != 'true':
            queryset = queryset.filter(is_archived=False)
        return queryset

    def list(self, request, *args, **kwargs):
        services.ensure_system_categories(request.user.tenant_id)
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        instance = serializer.save(tenant_id=self.request.user.tenant_id, is_system=False, code='')
        audit_log.record(
            action='expense_category.created', actor=self.request.user, obj=instance,
            after={'name': instance.name}, request=self.request,
        )

    def perform_update(self, serializer):
        before = {'name': serializer.instance.name, 'is_archived': serializer.instance.is_archived}
        instance = serializer.save()
        after = {'name': instance.name, 'is_archived': instance.is_archived}
        if before != after:
            audit_log.record(
                action='expense_category.updated', actor=self.request.user, obj=instance,
                before=before, after=after, request=self.request,
            )

    def perform_destroy(self, instance):
        if instance.is_system:
            raise Conflict(_('Built-in categories cannot be deleted.'), code='system_category')
        # Soft-deleted expenses still reference it (PROTECT), so they count.
        if instance.expenses.exists():
            raise Conflict(
                _('This category is used by expenses. Archive it instead.'), code='category_in_use',
            )
        audit_log.record(
            action='expense_category.deleted', actor=self.request.user, obj=instance,
            before={'name': instance.name}, request=self.request,
        )
        instance.delete()
