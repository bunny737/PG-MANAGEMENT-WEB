import django_filters
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.periods import local_today
from apps.core.permissions import require_permission, require_permission_by_method
from apps.core.roles import permissions_for_user
from apps.properties.services import visible_property_ids

from . import credits, services
from .models import Announcement, FoodHoliday, FoodHolidayCredit
from .serializers import AnnouncementSerializer, FoodHolidayCreditSerializer, FoodHolidaySerializer


class AnnouncementFilter(django_filters.FilterSet):
    property = django_filters.UUIDFilter(field_name='property_id')
    category = django_filters.ChoiceFilter(choices=Announcement.Category.choices)
    active = django_filters.BooleanFilter(method='filter_active')

    class Meta:
        model = Announcement
        fields = ['property', 'category', 'active']

    def filter_active(self, queryset, name, value):
        live = Q(expires_on__isnull=True) | Q(expires_on__gte=local_today())
        return queryset.filter(live) if value else queryset.exclude(live)


class AnnouncementViewSet(viewsets.ModelViewSet):
    """The notice board (Module 24). Reads need `view_notices`, writes
    `manage_notices`; scoped to the caller's properties. Pinned first, then
    newest. ?active=true hides expired notices."""

    serializer_class = AnnouncementSerializer
    permission_classes = [IsAuthenticated, require_permission_by_method('view_notices', 'manage_notices')]
    http_method_names = ['get', 'post', 'patch', 'delete']
    filterset_class = AnnouncementFilter

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Announcement.objects.none()
        return (
            Announcement.objects.filter(property_id__in=visible_property_ids(self.request.user))
            .select_related('property', 'created_by', 'food_holiday')
        )

    def perform_create(self, serializer):
        serializer.instance = services.create_announcement(
            data=serializer.validated_data, actor=self.request.user, request=self.request,
        )

    def perform_update(self, serializer):
        serializer.instance = services.update_announcement(
            announcement=serializer.instance, data=serializer.validated_data, actor=self.request.user,
            request=self.request,
        )

    def perform_destroy(self, instance):
        services.delete_announcement(announcement=instance, actor=self.request.user, request=self.request)

    @action(detail=True, methods=['post'], url_path='mark-current')
    def mark_current(self, request, pk=None):
        """Keep a customised holiday notice as it is after its holiday changed
        (clears `notice_outdated`)."""
        announcement = services.mark_current(announcement=self.get_object(), actor=request.user, request=request)
        return Response(self.get_serializer(announcement).data)


class FoodHolidayFilter(django_filters.FilterSet):
    property = django_filters.UUIDFilter(field_name='property_id')

    class Meta:
        model = FoodHoliday
        fields = ['property']


class FoodHolidayViewSet(viewsets.ModelViewSet):
    """Food holidays (Module 24). Reads need `view_notices`, writes
    `manage_notices`; a holiday that adjusts bills — now or after the
    request — also needs `manage_invoices`. Rates and credits need
    `view_finance` to be seen."""

    serializer_class = FoodHolidaySerializer
    permission_classes = [IsAuthenticated, require_permission_by_method('view_notices', 'manage_notices')]
    http_method_names = ['get', 'post', 'patch', 'delete']
    filterset_class = FoodHolidayFilter

    def get_permissions(self):
        if self.action == 'holiday_credits':
            return [IsAuthenticated(), require_permission('view_notices')(), require_permission('view_finance')()]
        if self.action == 'restore_credit':
            return [IsAuthenticated(), require_permission('manage_notices')(),
                    require_permission('manage_invoices')()]
        return super().get_permissions()

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return FoodHoliday.objects.none()
        return (
            FoodHoliday.objects.filter(property_id__in=visible_property_ids(self.request.user))
            .select_related('property', 'announcement')
        )

    def _can_manage_invoices(self):
        return 'manage_invoices' in set(permissions_for_user(self.request.user))

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        post_notice = data.pop('post_notice', True)
        if data.get('adjust_in_bill') and not self._can_manage_invoices():
            raise PermissionDenied(_('Adjusting bills needs permission to manage invoices.'))
        serializer.instance = services.create_holiday(
            data=data, post_notice=post_notice, actor=self.request.user, request=self.request,
        )

    # Update / delete: the service checks manage_invoices against the locked
    # holiday, not the copy read here (the adjustment may change in between).
    def perform_update(self, serializer):
        data = dict(serializer.validated_data)
        data.pop('post_notice', None)
        data.pop('property', None)  # immutable (validated in the serializer)
        serializer.instance = services.update_holiday(
            holiday=serializer.instance, data=data, actor=self.request.user, request=self.request,
            can_manage_invoices=self._can_manage_invoices(),
        )

    def perform_destroy(self, instance):
        services.delete_holiday(holiday=instance, actor=self.request.user, request=self.request,
                                can_manage_invoices=self._can_manage_invoices())

    @extend_schema(responses=FoodHolidayCreditSerializer(many=True))
    @action(detail=True, methods=['get'], url_path='credits', url_name='credits')
    def holiday_credits(self, request, pk=None):
        """Per-resident credits: stored rows, plus "estimated" rows for
        residents who qualify now but have no credit yet (e.g. the holiday
        hasn't ended). Read-only."""
        holiday = self.get_object()
        rows = []
        stored = (
            FoodHolidayCredit.objects.filter(holiday=holiday)
            .select_related('resident', 'line_item__invoice').order_by('resident__first_name', 'resident__last_name')
        )
        have = set()
        for credit in stored:
            have.add(credit.resident_id)
            invoice = credit.line_item.invoice if credit.line_item_id else None
            rows.append({
                'id': credit.pk, 'resident': credit.resident_id, 'resident_name': str(credit.resident),
                'status': credit.status, 'days': credit.days, 'rate': credit.rate, 'amount': credit.amount,
                'invoice': invoice.pk if invoice else None, 'invoice_status': invoice.status if invoice else None,
                'clawback_amount': credit.clawback_amount,
            })
        for resident, days in credits.estimate_holiday(holiday, exclude=have):
            rows.append({
                'id': None, 'resident': resident.pk, 'resident_name': str(resident), 'status': 'estimated',
                'days': days, 'rate': holiday.rate_per_day,
                'amount': credits.credit_amount(holiday.rate_per_day, days),
                'invoice': None, 'invoice_status': None, 'clawback_amount': '0.00',
            })
        return Response(FoodHolidayCreditSerializer(rows, many=True).data)

    @extend_schema(request=None, responses=FoodHolidayCreditSerializer)
    @action(detail=True, methods=['post'], url_path=r'credits/(?P<credit_pk>[0-9a-f-]+)/restore',
            url_name='restore-credit')
    def restore_credit(self, request, pk=None, credit_pk=None):
        """Undo a waiver: the credit is owed again and goes on the next draft
        (once the holiday has ended)."""
        holiday = self.get_object()
        credit = FoodHolidayCredit.objects.filter(holiday=holiday, pk=credit_pk).first()
        if credit is None:
            raise NotFound(_('Credit not found.'))
        with transaction.atomic():
            services.lock_holiday_property(holiday)
            credit = credits.restore(credit, actor=request.user, request=request)
        credit.refresh_from_db()
        invoice = credit.line_item.invoice if credit.line_item_id else None
        return Response(FoodHolidayCreditSerializer({
            'id': credit.pk, 'resident': credit.resident_id, 'resident_name': str(credit.resident),
            'status': credit.status, 'days': credit.days, 'rate': credit.rate, 'amount': credit.amount,
            'invoice': invoice.pk if invoice else None, 'invoice_status': invoice.status if invoice else None,
            'clawback_amount': credit.clawback_amount,
        }).data, status=status.HTTP_200_OK)
