"""Endpoints for resident app access (Module 26): the staff side (invite, revoke, review link
requests, the property join code) and the person's side (their residencies, join-code lookup,
link requests, accepting an invite). The lifecycle rules live in `access.py`.

Everything the person calls sits under /me/ and uses its own serializers; staff serializers are
never reused for them."""
import django_filters
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Tenant
from apps.core.permissions import IsResidentAccount, IsVerifiedResidentAccount, require_permission
from apps.core.tenancy import tenant_context
from apps.core.throttles import JoinCodeLookupIPThrottle, ScopedRateThrottle
from apps.properties import join_codes
from apps.properties.models import Property
from apps.properties.services import visible_property_ids

from . import access
from .models import Resident, ResidencyLinkRequest, ResidentAccess, ResidentInvite


# --- Staff: one resident's app access ------------------------------------------------------------
class AccessSummarySerializer(serializers.ModelSerializer):
    account_name = serializers.SerializerMethodField()

    class Meta:
        model = ResidentAccess
        fields = [
            'id', 'status', 'origin', 'account_name', 'activated_at', 'exited_at', 'access_expires_at',
            'revoked_at',
        ]
        read_only_fields = fields

    def get_account_name(self, obj) -> str:
        user = obj.user
        return ' '.join(filter(None, [user.first_name, user.last_name]))


class InviteSummarySerializer(serializers.ModelSerializer):
    expired = serializers.SerializerMethodField()

    class Meta:
        model = ResidentInvite
        fields = ['id', 'status', 'email', 'expires_at', 'expired', 'cancel_reason', 'created_at']
        read_only_fields = fields

    def get_expired(self, obj) -> bool:
        return access.invite_is_expired(obj)


def app_access_state(resident):
    """What a staff screen needs to render the 'App access' card for one resident."""
    current = (
        ResidentAccess.objects.select_related('user')
        .filter(resident=resident, status=ResidentAccess.Status.ACTIVE).first()
    )
    # Most recent link of any state, so a revoked/expired one is still visible after the fact.
    last = current or (
        ResidentAccess.objects.select_related('user').filter(resident=resident).order_by('-activated_at').first()
    )
    invite = ResidentInvite.objects.filter(resident=resident).order_by('-created_at').first()
    eligible = resident.status in access.ELIGIBLE_STATUSES
    return {
        'eligible': eligible,
        'email': resident.email or None,
        'can_invite': eligible and bool(resident.email) and current is None,
        'access': AccessSummarySerializer(last).data if last else None,
        'invite': InviteSummarySerializer(invite).data if invite else None,
    }


class _ResidentAccessView(APIView):
    permission_classes = [IsAuthenticated, require_permission('manage_residents')]

    def get_resident(self, request, pk):
        return get_object_or_404(
            Resident.objects.filter(property_id__in=visible_property_ids(request.user)), pk=pk,
        )


class ResidentAppAccessView(_ResidentAccessView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk):
        return Response(app_access_state(self.get_resident(request, pk)))


class ResidentAppInviteView(_ResidentAccessView):
    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def post(self, request, pk):
        resident = self.get_resident(request, pk)
        access.send_invite(resident_id=resident.pk, actor=request.user, request=request)
        return Response(app_access_state(resident), status=status.HTTP_201_CREATED)


class ResidentAppInviteCancelView(_ResidentAccessView):
    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def post(self, request, pk):
        resident = self.get_resident(request, pk)
        access.cancel_invite(resident_id=resident.pk, actor=request.user, request=request)
        return Response(app_access_state(resident))


class ResidentAppAccessRevokeView(_ResidentAccessView):
    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def post(self, request, pk):
        resident = self.get_resident(request, pk)
        access.revoke_access(resident_id=resident.pk, actor=request.user, request=request)
        return Response(app_access_state(resident))


# --- Staff: link requests -------------------------------------------------------------------------
class PossibleMatchSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = Resident
        fields = ['id', 'name', 'status', 'phone']
        read_only_fields = fields

    def get_name(self, obj) -> str:
        return str(obj)


class LinkRequestStaffSerializer(serializers.ModelSerializer):
    """What staff see. Deliberately the person's name and what they typed about themselves, not
    their account details; `possible_matches` is display-only help and nothing is auto-matched."""

    property_name = serializers.CharField(source='property.name', read_only=True)
    requester_name = serializers.SerializerMethodField()
    possible_matches = serializers.SerializerMethodField()

    class Meta:
        model = ResidencyLinkRequest
        fields = [
            'id', 'status', 'property', 'property_name', 'requester_name', 'message', 'claimed_name',
            'claimed_phone', 'claimed_room', 'resolution_note', 'resolved_resident', 'resolved_at',
            'created_at', 'possible_matches',
        ]
        read_only_fields = fields

    def get_requester_name(self, obj) -> str:
        user = obj.requester
        return ' '.join(filter(None, [user.first_name, user.last_name]))

    def get_possible_matches(self, obj) -> list:
        if obj.status != ResidencyLinkRequest.Status.PENDING:
            return []
        match = Q()
        if obj.claimed_phone:
            match |= Q(phone=obj.claimed_phone)
        if obj.requester.email:
            match |= Q(email__iexact=obj.requester.email)
        if obj.claimed_name:
            first, _sep, last = obj.claimed_name.strip().partition(' ')
            match |= Q(first_name__iexact=first, last_name__iexact=last.strip())
        if not match:
            return []
        rows = (
            Resident.objects.filter(property_id=obj.property_id, status__in=access.ELIGIBLE_STATUSES)
            .filter(match).order_by('first_name')[:5]
        )
        return PossibleMatchSerializer(rows, many=True).data


class LinkRequestFilter(django_filters.FilterSet):
    property = django_filters.UUIDFilter(field_name='property_id')

    class Meta:
        model = ResidencyLinkRequest
        fields = ['status', 'property']


class LinkRequestApproveSerializer(serializers.Serializer):
    resident_id = serializers.UUIDField()


class LinkRequestRejectSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')


class ResidencyLinkRequestViewSet(viewsets.ReadOnlyModelViewSet):
    """Staff review of 'link me to this PG' requests. Scoped to the properties the caller can see."""

    permission_classes = [IsAuthenticated, require_permission('manage_residents')]
    serializer_class = LinkRequestStaffSerializer
    filterset_class = LinkRequestFilter

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return ResidencyLinkRequest.objects.none()
        return (
            ResidencyLinkRequest.objects.filter(property_id__in=visible_property_ids(self.request.user))
            .select_related('requester', 'property').order_by('-created_at')
        )

    @extend_schema(request=LinkRequestApproveSerializer, responses={200: LinkRequestStaffSerializer})
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        link_request = self.get_object()
        body = LinkRequestApproveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        # The chosen record must be one the caller can see, and (checked again under the lock in
        # approve_link_request) must belong to the request's property.
        resident = get_object_or_404(
            Resident.objects.filter(property_id__in=visible_property_ids(request.user)),
            pk=body.validated_data['resident_id'],
        )
        access.approve_link_request(
            link_request_id=link_request.pk, resident_id=resident.pk, actor=request.user, request=request,
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=link_request.pk)).data)

    @extend_schema(request=LinkRequestRejectSerializer, responses={200: LinkRequestStaffSerializer})
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        link_request = self.get_object()
        body = LinkRequestRejectSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        access.reject_link_request(
            link_request_id=link_request.pk, actor=request.user, note=body.validated_data['note'],
            request=request,
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=link_request.pk)).data)


# --- Staff: the property join code ----------------------------------------------------------------
class PropertyJoinCodeView(APIView):
    """The code residents use to ask to be linked to this PG. GET shows it; POST (rotate) replaces
    it, and the old one stops working at once. Pending requests already made stay valid."""

    permission_classes = [IsAuthenticated, require_permission('edit_properties')]

    def get_property(self, request, pk):
        return get_object_or_404(Property.objects.filter(id__in=visible_property_ids(request.user)), pk=pk)

    @staticmethod
    def payload(prop):
        return {'join_code': prop.join_code, 'rotated_at': prop.join_code_rotated_at}

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk):
        return Response(self.payload(self.get_property(request, pk)))


class PropertyJoinCodeRotateView(PropertyJoinCodeView):
    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def post(self, request, pk):
        prop = join_codes.rotate_join_code(self.get_property(request, pk).pk, actor=request.user, request=request)
        return Response(self.payload(prop))


# --- The person: their residencies ----------------------------------------------------------------
class MyResidenciesView(APIView):
    """Every link this signed-in person holds, with what each currently lets them see. No
    X-Residency-Id needed: this is how the app learns which ids to send."""

    permission_classes = [IsResidentAccount]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        links = list(ResidentAccess.objects.filter(user_id=request.user.pk).order_by('-activated_at'))
        tenants = {t.pk: t for t in Tenant.objects.filter(pk__in={link.tenant_id for link in links})}
        by_tenant = {}
        for link in links:
            by_tenant.setdefault(link.tenant_id, []).append(link)

        now = timezone.now()
        rows = []
        for tenant_id, tenant_links in by_tenant.items():
            tenant = tenants.get(tenant_id)
            # Enter each PG's tenant to read the resident and property behind the link.
            with tenant_context(tenant_id):
                residents = {
                    r.pk: r for r in Resident.objects.select_related('property')
                    .filter(pk__in=[link.resident_id for link in tenant_links])
                }
            for link in tenant_links:
                resident = residents.get(link.resident_id)
                if resident is None or tenant is None:
                    continue
                rows.append({
                    'id': link.pk,
                    'status': link.status,
                    'origin': link.origin,
                    'scope': access.residency_scope(link, resident, tenant.status, now),
                    'business_name': tenant.name,
                    'property_id': resident.property_id,
                    'property_name': resident.property.name,
                    'resident_status': resident.status,
                    'first_name': resident.first_name,
                    'activated_at': link.activated_at,
                    'exited_at': link.exited_at,
                    'access_expires_at': link.access_expires_at,
                })
        rows.sort(key=lambda row: row['activated_at'], reverse=True)
        return Response(rows)


# --- The person: join code and link requests ------------------------------------------------------
class JoinCodeLookupView(APIView):
    """Confirm which PG a join code is for before asking to be linked. Returns the property's name
    and city only; an unknown code and a blocked PG look the same."""

    permission_classes = [IsVerifiedResidentAccount]
    throttle_classes = [ScopedRateThrottle, JoinCodeLookupIPThrottle]
    throttle_scope = 'resident_join_code_lookup'

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, code):
        found = access.lookup_join_code(code)
        return Response({'name': found['name'], 'city': found['city']})


def property_names(link_requests):
    """{property_id: name} for the given link requests. A resident-pool person has no tenant, and
    `properties` is under RLS, so a join from their own row would silently drop it; read each
    PG's names inside that PG's tenant context instead."""
    wanted = {}
    for link_request in link_requests:
        wanted.setdefault(link_request.tenant_id, set()).add(link_request.property_id)
    names = {}
    for tenant_id, property_ids in wanted.items():
        with tenant_context(tenant_id):
            names.update(Property.objects.filter(pk__in=property_ids).values_list("pk", "name"))
    return names


class MyLinkRequestSerializer(serializers.ModelSerializer):
    property_name = serializers.SerializerMethodField()

    def get_property_name(self, obj) -> str:
        return self.context.get("property_names", {}).get(obj.property_id, "")

    class Meta:
        model = ResidencyLinkRequest
        fields = [
            'id', 'status', 'property_name', 'message', 'claimed_name', 'claimed_phone', 'claimed_room',
            'resolution_note', 'created_at', 'resolved_at',
        ]
        read_only_fields = fields


class LinkRequestCreateSerializer(serializers.Serializer):
    join_code = serializers.CharField(max_length=20)
    message = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    claimed_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    claimed_phone = serializers.CharField(max_length=15, required=False, allow_blank=True, default='')
    claimed_room = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')


class MyLinkRequestsView(APIView):
    permission_classes = [IsVerifiedResidentAccount]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'resident_link_request'

    def get_throttles(self):
        # Only creating a request costs staff attention; reading your own is free.
        return super().get_throttles() if self.request.method == 'POST' else []

    @extend_schema(responses={200: MyLinkRequestSerializer(many=True)})
    def get(self, request):
        # No select_related('property'): that INNER JOIN would drop every row, since this person has
        # no tenant and RLS hides the property. Names are read per PG instead.
        rows = list(ResidencyLinkRequest.objects.filter(requester_id=request.user.pk).order_by("-created_at"))
        context = {"property_names": property_names(rows)}
        return Response(MyLinkRequestSerializer(rows, many=True, context=context).data)

    @extend_schema(request=LinkRequestCreateSerializer, responses={201: MyLinkRequestSerializer})
    def post(self, request):
        body = LinkRequestCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        found = access.lookup_join_code(data['join_code'])
        link_request, created = access.request_residency_link(
            user=request.user, property_id=found['property_id'], tenant_id=found['tenant_id'],
            message=data['message'], claimed_name=data['claimed_name'],
            claimed_phone=data['claimed_phone'], claimed_room=data['claimed_room'], request=request,
        )
        payload = MyLinkRequestSerializer(
            link_request, context={"property_names": property_names([link_request])},
        ).data
        return Response(payload, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class MyLinkRequestCancelView(APIView):
    permission_classes = [IsVerifiedResidentAccount]

    @extend_schema(request=None, responses={200: MyLinkRequestSerializer})
    def post(self, request, pk):
        link_request = access.cancel_link_request(user=request.user, link_request_id=pk, request=request)
        context = {"property_names": property_names([link_request])}
        return Response(MyLinkRequestSerializer(link_request, context=context).data)


# --- The person: accept a staff invite ------------------------------------------------------------
class InviteAcceptSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=1000)


class InviteAcceptView(APIView):
    """Accept a staff invite with the token from the emailed link. Always authenticated: the
    person signs up (or in) first, so accepting is always an act of the account's owner."""

    permission_classes = [IsResidentAccount]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'resident_invite_accept'

    @extend_schema(request=InviteAcceptSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        body = InviteAcceptSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        link, created = access.accept_invite(
            user=request.user, token=body.validated_data['token'], request=request,
        )
        return Response(
            {'residency_id': link.pk, 'status': link.status},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
