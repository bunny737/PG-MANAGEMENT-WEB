from rest_framework import serializers

from apps.devices.models import AppInstallation

from .models import NotificationLog, PushSubscription
from .registry import NOTIFICATION_TYPES, is_optional


class NotificationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationLog
        fields = [
            'id', 'notification_type', 'channel', 'subject', 'status',
            'reference', 'note', 'sent_at', 'created_at',
        ]
        read_only_fields = fields


class NotificationPreferenceItemSerializer(serializers.Serializer):
    """One (notification_type, channel) row — as returned by GET, this is
    the effective state (explicit NotificationPreference row if one exists,
    else the registry default of "enabled"), not a raw model instance."""

    notification_type = serializers.CharField()
    channel = serializers.CharField()
    enabled = serializers.BooleanField()


class NotificationPreferenceUpdateSerializer(serializers.Serializer):
    notification_type = serializers.CharField()
    channel = serializers.CharField()
    enabled = serializers.BooleanField()

    def validate_notification_type(self, value):
        if value not in NOTIFICATION_TYPES:
            raise serializers.ValidationError('Unknown notification_type.')
        if not is_optional(value):
            raise serializers.ValidationError('This notification type cannot be disabled.')
        return value

    def validate(self, attrs):
        if attrs['channel'] not in NOTIFICATION_TYPES[attrs['notification_type']]['channels']:
            raise serializers.ValidationError(
                {'channel': 'This channel is not used by the given notification_type.'}
            )
        return attrs


class PushSubscriptionSerializer(serializers.ModelSerializer):
    # Declared explicitly so DRF adds no UniqueValidator: re-registering a
    # known token is an upsert (apps.notifications.subscriptions), not a 400.
    fcm_token = serializers.CharField(max_length=255)
    # Optional: the mobile app's install UUID (apps.devices). Links the
    # subscription to that install when it exists; an unknown id is ignored.
    installation_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    # Optional: the caller's previous subscription id. On web token rotation
    # it is deleted in the same transaction as the new token's upsert.
    replaces = serializers.UUIDField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = PushSubscription
        fields = ['id', 'fcm_token', 'device_type', 'installation_id', 'replaces', 'last_seen_at']
        read_only_fields = ['id', 'last_seen_at']

    def validate(self, attrs):
        # `installation_id` is also the FK attname on the model (an int pk),
        # so it must be swapped for the resolved instance before save().
        # Only an install already linked to the caller is accepted: linking
        # replaces the install's existing subscription (as super admin, across
        # tenants), so trusting a bare UUID would let anyone who learns
        # another device's installation_id unsubscribe it. Anything else is
        # ignored, same as an unknown id.
        install_uuid = attrs.pop('installation_id', None)
        request = self.context.get('request')
        if install_uuid and request is not None:
            installation = AppInstallation.objects.filter(
                installation_id=install_uuid, user_id=request.user.id,
            ).first()
            if installation is not None:
                attrs['installation'] = installation
        return attrs
