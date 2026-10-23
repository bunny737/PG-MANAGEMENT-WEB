import ipaddress

from django.conf import settings
from django.utils.translation import get_language
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.log import client_ip

from .exceptions import PayloadTooLarge
from .models import ContactMessage, PlatformConfig
from .serializers import ContactMessageSerializer, ContactReceivedSerializer, SupportContactSerializer
from .throttles import ContactEmailThrottle, ContactIPThrottle

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


class ContactMessageView(APIView):
    """The website contact form: stores a ContactMessage for a Super Admin to read in
    the Django admin. Public and write-only (no GET: a visitor can never read messages).

    Abuse controls, in order: a body-size cap before anything parses the request,
    a per-IP and a per-email throttle, field validation, and a honeypot — a bot that
    fills the hidden `website` field gets the same 201 as a human but nothing is saved,
    so it learns nothing about being filtered."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ContactIPThrottle, ContactEmailThrottle]

    def initial(self, request, *args, **kwargs):
        limit = settings.CONTACT_MAX_BODY_BYTES
        try:
            declared = int(request.META.get('CONTENT_LENGTH') or 0)
        except ValueError:
            declared = 0
        if declared > limit or len(request._request.body) > limit:
            raise PayloadTooLarge()
        super().initial(request, *args, **kwargs)

    @extend_schema(request=ContactMessageSerializer, responses={201: ContactReceivedSerializer})
    def post(self, request):
        serializer = ContactMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if not data.get('website'):
            ContactMessage.objects.create(
                name=data['name'],
                email=data['email'].lower(),
                phone=data.get('phone', ''),
                message=data['message'],
                language=(get_language() or '')[:8],
                ip_address=_valid_ip(client_ip(request)),
            )
        return Response({'status': 'received'}, status=status.HTTP_201_CREATED)


def _valid_ip(value):
    """X-Forwarded-For is client-controlled; never let garbage reach the IP column."""
    try:
        return str(ipaddress.ip_address((value or '').strip()))
    except ValueError:
        return None
