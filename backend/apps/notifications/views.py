from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import require_permission

from .models import NotificationLog, NotificationPreference, PushSubscription
from .registry import NOTIFICATION_TYPES
from .serializers import (
    NotificationLogSerializer,
    NotificationPreferenceItemSerializer,
    NotificationPreferenceUpdateSerializer,
    PushSubscriptionSerializer,
)


class NotificationHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """The current user's own notification history (Module 14 V2 — the
    original MVP had no API at all; NotificationLog stays admin-only for the
    full, cross-recipient view). Self-scoped via `recipient_user`, so this
    only surfaces logs whose recipient was a real login account — matches
    the same "no resident login yet" limitation as raise_complaint/
    request_visitor (see apps.operations.views.ComplaintViewSet)."""

    serializer_class = NotificationLogSerializer
    permission_classes = [IsAuthenticated, require_permission('view_own_notifications')]
    filterset_fields = ['notification_type', 'channel', 'status']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return NotificationLog.objects.none()
        return NotificationLog.objects.filter(recipient_user=self.request.user)


class NotificationPreferenceViewSet(viewsets.ViewSet):
    """GET returns the effective opt-in state for every (notification_type,
    channel) pair the registry marks `optional=True` — an absent
    NotificationPreference row means "enabled" (opt-out model), so a user
    who has never touched this sees everything they get today. POST upserts
    one or more rows (no single-resource pk exists — a preference is keyed
    by the (notification_type, channel) pair, not an id — so this is a
    collection-level upsert rather than a per-object PATCH)."""

    permission_classes = [IsAuthenticated, require_permission('manage_notification_preferences')]

    def _optional_pairs(self):
        for notification_type, meta in NOTIFICATION_TYPES.items():
            if not meta['optional']:
                continue
            for channel in meta['channels']:
                yield notification_type, channel

    def list(self, request):
        disabled = set(
            NotificationPreference.objects.filter(user=request.user, enabled=False)
            .values_list('notification_type', 'channel')
        )
        items = [
            {'notification_type': nt, 'channel': ch, 'enabled': (nt, ch) not in disabled}
            for nt, ch in self._optional_pairs()
        ]
        return Response(NotificationPreferenceItemSerializer(items, many=True).data)

    def create(self, request):
        payload = request.data if isinstance(request.data, list) else [request.data]
        return self._upsert(request, payload)

    def _upsert(self, request, payload):
        serializer = NotificationPreferenceUpdateSerializer(data=payload, many=True)
        serializer.is_valid(raise_exception=True)
        for item in serializer.validated_data:
            NotificationPreference.objects.update_or_create(
                tenant_id=request.user.tenant_id, user=request.user,
                notification_type=item['notification_type'], channel=item['channel'],
                defaults={'enabled': item['enabled']},
            )
        return self.list(request)


class PushSubscriptionViewSet(viewsets.ModelViewSet):
    """Register/unregister an FCM device token for the current user (web via
    the Serwist service worker, or the Flutter app on Android/iOS — see
    docs/push-notifications-integration.md). No special permission beyond
    authentication — registering a device is a per-user action, not a
    business permission, same as editing your own profile."""

    serializer_class = PushSubscriptionSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'delete']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return PushSubscription.objects.none()
        return PushSubscription.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        # A device re-registering (app reinstall, token refresh) upserts
        # rather than erroring on the unique fcm_token constraint.
        token = request.data.get('fcm_token')
        existing = PushSubscription.objects.filter(fcm_token=token).first() if token else None
        if existing is not None:
            serializer = self.get_serializer(existing, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save(user=request.user, tenant_id=request.user.tenant_id)
            return Response(serializer.data, status=status.HTTP_200_OK)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user, tenant_id=request.user.tenant_id)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
