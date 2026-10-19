from django.utils.translation import gettext_lazy as _
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


class ContactMessageSerializer(serializers.Serializer):
    """Body of POST /public/contact/. Kept as a plain Serializer (not a
    ModelSerializer) so the public input contract is explicit: nothing the
    sender posts can reach `status`, `ip_address` or any other model field."""

    name = serializers.CharField(min_length=2, max_length=100)
    email = serializers.EmailField(max_length=254)
    phone = serializers.RegexField(
        r'^\+?[0-9 ]{7,20}$', required=False, allow_blank=True, max_length=20,
        error_messages={'invalid': _('Enter a valid phone number.')},
    )
    message = serializers.CharField(min_length=10, max_length=2000)
    # Honeypot: hidden in the form, so a human never fills it. A bot that does is
    # answered with the same 201 but nothing is stored (see ContactMessageView).
    website = serializers.CharField(required=False, allow_blank=True, write_only=True, max_length=200)

    def validate_phone(self, value):
        digits = value.replace(' ', '').lstrip('+')
        if value and not 7 <= len(digits) <= 15:
            raise serializers.ValidationError(_('Enter a valid phone number.'))
        return value


class ContactReceivedSerializer(serializers.Serializer):
    """Response shape of POST /public/contact/ (schema only)."""

    status = serializers.CharField()
