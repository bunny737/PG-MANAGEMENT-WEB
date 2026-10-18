from rest_framework import serializers


class SupportContactSerializer(serializers.Serializer):
    """Response shape of GET /support/ (schema only; the view builds the dict).
    Every field is null when that channel isn't configured."""

    email = serializers.EmailField(allow_null=True)
    phone = serializers.CharField(allow_null=True)
    whatsapp = serializers.CharField(allow_null=True)
    whatsapp_url = serializers.URLField(allow_null=True)
    website = serializers.URLField(allow_null=True)
    hours = serializers.CharField(allow_null=True)
