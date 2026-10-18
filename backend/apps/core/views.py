from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PlatformConfig
from .serializers import SupportContactSerializer

SUPPORT_CACHE_MAX_AGE_SECONDS = 300


class SupportContactView(APIView):
    """Platform support contacts (email, phone, WhatsApp, ...) set by a Super
    Admin. Public: the app needs them on the login screen, before any session
    exists. Channels that aren't configured come back as null."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(responses=SupportContactSerializer)
    def get(self, request):
        # filter().first(), not PlatformConfig.get(): a public GET must not write.
        config = PlatformConfig.objects.filter(pk=1).first() or PlatformConfig()
        response = Response({
            'email': config.support_email or None,
            'phone': config.support_phone or None,
            'whatsapp': config.support_whatsapp or None,
            'whatsapp_url': f'https://wa.me/{config.support_whatsapp}' if config.support_whatsapp else None,
            'website': config.support_website or None,
            'hours': config.support_hours or None,
        })
        response['Cache-Control'] = f'public, max-age={SUPPORT_CACHE_MAX_AGE_SECONDS}'
        return response
