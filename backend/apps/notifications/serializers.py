from rest_framework import serializers

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
    class Meta:
        model = PushSubscription
        fields = ['id', 'fcm_token', 'device_type', 'last_seen_at']
        read_only_fields = ['id', 'last_seen_at']
