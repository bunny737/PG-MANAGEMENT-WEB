from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Tenant
from apps.core.permissions import IsSuperAdmin, require_permission
from apps.core.roles import Role
from apps.properties.models import Bed, Property

from . import razorpay_client, services
from .models import Plan, Subscription
from .serializers import (
    OverrideLimitsSerializer,
    PlanSerializer,
    SelectPlanSerializer,
    SubscriptionInvoiceSerializer,
    SubscriptionSerializer,
)


class PlanViewSet(viewsets.ModelViewSet):
    """Pricing tiers (PRD §4 'Subscription & Pricing Model'). Any
    `manage_subscription` actor (Super Admin, Owner) can browse the catalog
    to decide on an upgrade; only Super Admin manages it — the catalog
    itself isn't tenant data, unlike a tenant's own Subscription."""

    serializer_class = PlanSerializer
    http_method_names = ['get', 'post', 'patch', 'delete']
    filterset_fields = ['is_active', 'is_trial_plan']

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsAuthenticated(), IsSuperAdmin()]
        return [IsAuthenticated(), require_permission('manage_subscription')()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Plan.objects.none()
        if self.request.user.role == Role.SUPER_ADMIN:
            return Plan.objects.prefetch_related('bed_tiers').all()
        return Plan.objects.prefetch_related('bed_tiers').filter(is_active=True)

    def perform_destroy(self, instance):
        if instance.subscriptions.exists():
            raise ValidationError(
                {'detail': _('Cannot delete a plan that tenants are subscribed to.')},
                code='plan_in_use',
            )
        instance.delete()


class SubscriptionViewSet(viewsets.ReadOnlyModelViewSet):
    """A tenant's own subscription + usage (PRD Module 20 'Current plan and
    usage'). Looked up by tenant id (not the Subscription row's own id) so
    the frontend always reaches it via `/subscriptions/{tenant_id}/` without
    a separate 'my subscription' step. Owner sees only their own tenant;
    Super Admin can look up (and act on) any tenant."""

    serializer_class = SubscriptionSerializer
    permission_classes = [IsAuthenticated, require_permission('manage_subscription')]
    lookup_field = 'tenant_id'
    lookup_url_kwarg = 'tenant_id'

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Subscription.objects.none()

        bed_count_subquery = Bed.objects.filter(
            tenant_id=OuterRef('tenant_id')
        ).values('tenant_id').annotate(cnt=Count('id')).values('cnt')

        property_count_subquery = Property.objects.filter(
            tenant_id=OuterRef('tenant_id')
        ).values('tenant_id').annotate(cnt=Count('id')).values('cnt')

        queryset = (
            Subscription.objects
            .select_related('plan', 'tenant')
            .prefetch_related('plan__bed_tiers')
            .annotate(
                annotated_bed_count=Coalesce(Subquery(bed_count_subquery), 0),
                annotated_properties_used=Coalesce(Subquery(property_count_subquery), 0),
            )
        )
        if self.request.user.role == Role.SUPER_ADMIN:
            return queryset
        return queryset.filter(tenant_id=self.request.user.tenant_id)

    @action(detail=True, methods=['post'], url_path='select-plan', url_name='select-plan')
    def select_plan(self, request, tenant_id=None):
        subscription = self.get_object()
        serializer = SelectPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.select_plan(
            subscription=subscription, plan=serializer.validated_data['plan'],
            actor=request.user, request=request,
        )
        return Response(SubscriptionSerializer(self.get_object()).data)

    @action(detail=True, methods=['get'], url_path='price-preview', url_name='price-preview')
    def price_preview(self, request, tenant_id=None):
        """Live PER_BED_MONTHLY breakdown at the tenant's current bed count
        (PRD §4 pricing preview) — an estimate; the actual invoice is
        computed by `generate_invoice_for_subscription` from the bed-day
        ledger across the whole cycle, not a single snapshot."""
        subscription = self.get_object()
        return Response({
            'bed_count': services.get_total_beds(subscription.tenant_id),
            'current_cycle_estimate': services.estimate_current_cycle(subscription),
        })

    @action(detail=True, methods=['get'])
    def invoices(self, request, tenant_id=None):
        """Platform billing history for PER_BED_MONTHLY subscriptions (PRD
        Module 20 'Billing history and invoices from platform')."""
        subscription = self.get_object()
        queryset = subscription.invoices.prefetch_related('lines')
        return Response(SubscriptionInvoiceSerializer(queryset, many=True).data)

    @action(
        detail=True, methods=['patch'], url_path='override-limits', url_name='override-limits',
        permission_classes=[IsAuthenticated, IsSuperAdmin],
    )
    def override_limits(self, request, tenant_id=None):
        subscription = self.get_object()
        serializer = OverrideLimitsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        services.override_limits(
            subscription=subscription,
            max_properties_override=data.get('max_properties_override', subscription.max_properties_override),
            max_residents_override=data.get('max_residents_override', subscription.max_residents_override),
            actor=request.user, request=request,
        )
        return Response(SubscriptionSerializer(self.get_object()).data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsSuperAdmin])
    def suspend(self, request, tenant_id=None):
        subscription = self.get_object()
        tenant = subscription.tenant
        if tenant.status == Tenant.Status.SUSPENDED:
            raise ValidationError(
                {'detail': _('This tenant is already suspended.')}, code='already_suspended'
            )
        services.suspend_tenant(tenant=tenant, actor=request.user, request=request)
        return Response(SubscriptionSerializer(self.get_object()).data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsSuperAdmin])
    def reactivate(self, request, tenant_id=None):
        subscription = self.get_object()
        tenant = subscription.tenant
        if tenant.status not in (Tenant.Status.SUSPENDED, Tenant.Status.PAYMENT_FAILED):
            raise ValidationError(
                {'detail': _('This tenant is not suspended.')}, code='tenant_not_suspended'
            )
        services.reactivate_tenant(tenant=tenant, actor=request.user, request=request)
        return Response(SubscriptionSerializer(self.get_object()).data)


class RazorpayWebhookView(APIView):
    """Razorpay webhook receiver (PRD Module 20 'Razorpay webhook handling
    for payment success/failure'). Public and unauthenticated by nature —
    trust comes from the HMAC signature, not a user session, so JWT
    authentication (and the tenant context it sets) is deliberately skipped."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        signature = request.headers.get('X-Razorpay-Signature', '')
        if not razorpay_client.verify_webhook_signature(request.body.decode('utf-8'), signature):
            return Response({'detail': 'Invalid signature.'}, status=status.HTTP_400_BAD_REQUEST)
        services.handle_webhook_event(request.data)
        return Response({'status': 'ok'})
