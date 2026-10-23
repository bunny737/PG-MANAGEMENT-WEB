from django.utils.translation import gettext_lazy as _
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import require_permission

from . import subscriptions
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
        # rather than erroring on the unique fcm_token constraint; ownership
        # rules (latest login owns a token, even across tenants) live in
        # apps.notifications.subscriptions.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        subscription, created = subscriptions.upsert_subscription(
            user=request.user, token=data['fcm_token'], device_type=data['device_type'],
            installation=data.get('installation'), replaces=data.get('replaces'),
        )
        return Response(
            self.get_serializer(subscription).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def destroy(self, request, *args, **kwargs):
        """Optional `?if_last_seen_at=<value from the POST/GET response>` makes the delete
        conditional: 412 (and nothing deleted) if the row has been re-registered since. Clients that
        don't send it (the mobile app) get the plain delete."""
        instance = self.get_object()
        expected = None
        raw = request.query_params.get('if_last_seen_at')
        if raw is not None:
            try:
                expected = serializers.DateTimeField().to_internal_value(raw)
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({'if_last_seen_at': exc.detail})
        deleted = subscriptions.remove_subscription(
            user=request.user, subscription_id=instance.pk, if_last_seen_at=expected,
        )
        if expected is not None and not deleted:
            return Response(
                {'detail': _('This subscription was registered again since you last saw it; not deleted.')},
                status=status.HTTP_412_PRECONDITION_FAILED,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
