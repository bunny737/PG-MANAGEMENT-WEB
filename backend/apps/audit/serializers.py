from rest_framework import serializers

from .models import AuditLog


class AuditLogActorSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    role = serializers.CharField()


class AuditLogSerializer(serializers.ModelSerializer):
    actor = AuditLogActorSerializer(read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            'id', 'tenant_id', 'actor', 'action', 'object_type', 'object_id',
            'before', 'after', 'ip_address', 'created_at',
        ]
        read_only_fields = fields
