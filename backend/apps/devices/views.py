from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .authentication import OptionalTenantJWTAuthentication
from .models import DEFAULT_CHECK_INTERVAL_SECONDS
from .policy import get_policy, iso_z
from .serializers import DeviceRegistrationSerializer, VersionPolicyQuerySerializer
from .throttles import DeviceRegisterInstallationThrottle, DeviceRegisterIPThrottle


class PayloadTooLarge(APIException):
    status_code = 413
    default_detail = _('Request body too large.')
    default_code = 'payload_too_large'


class VersionPolicyView(APIView):
    """What the app must do about its build: update (force/soft), or wait out
    maintenance. Public, never 426/503 — maintenance is reported in the body."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(parameters=[VersionPolicyQuerySerializer], responses={200: OpenApiResponse(description='Policy')})
    def get(self, request):
        query = VersionPolicyQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        build = query.validated_data['build']
        policy = get_policy(query.validated_data['platform'], query.validated_data['flavor'])
        now = timezone.now()

        if policy is None:
            body = {
                'update_mode': 'none', 'min_supported_build': None, 'latest_build': None,
                'latest_version': None, 'store_url': None, 'release_notes': {},
                'maintenance': {'enabled': False, 'message': None, 'expires_at': None},
                'check_interval_seconds': DEFAULT_CHECK_INTERVAL_SECONDS,
            }
        else:
            maintenance_on = policy.maintenance_active(now)
            body = {
                'update_mode': policy.update_mode(build),
                'min_supported_build': policy.min_build,
                'latest_build': policy.latest_build,
                'latest_version': policy.latest_version or None,
                'store_url': policy.store_url or None,
                'release_notes': policy.release_notes,
                'maintenance': {
                    'enabled': maintenance_on,
                    'message': (policy.maintenance_message or None) if maintenance_on else None,
                    'expires_at': iso_z(policy.maintenance_expires_at) if maintenance_on else None,
                },
                'check_interval_seconds': policy.check_interval_seconds,
            }
        body['server_time'] = iso_z(now)
        response = Response(body)
        response['Cache-Control'] = 'public, max-age=60'
        return response


class DeviceRegisterView(APIView):
    """Upsert this install's device/app info. Authentication is optional and
    NEVER yields 401 here: the app does not refresh tokens for this call."""

    authentication_classes = [OptionalTenantJWTAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [DeviceRegisterIPThrottle, DeviceRegisterInstallationThrottle]

    def initial(self, request, *args, **kwargs):
        # Cheap guard before anything parses the body (the throttle does).
        limit = settings.DEVICE_REGISTER_MAX_BODY_BYTES
        try:
            declared = int(request.META.get('CONTENT_LENGTH') or 0)
        except ValueError:
            declared = 0
        if declared > limit or len(request._request.body) > limit:
            raise PayloadTooLarge()
        super().initial(request, *args, **kwargs)

    @extend_schema(request=DeviceRegistrationSerializer, responses={200: OpenApiResponse(), 201: OpenApiResponse()})
    def post(self, request):
        serializer = DeviceRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user if request.user and request.user.is_authenticated else None

        result = services.register_installation(
            installation_id=data['installation_id'], sync_seq=data['sync_seq'],
            signed_in=data['signed_in'], fields=serializer.to_installation_fields(), user=user,
        )
        if result.ignored:
            return Response({'registered': True, 'ignored': result.ignored})
        return Response(
            {
                'installation_id': str(data['installation_id']),
                'registered': True,
                'user_linked': user is not None,
                'server_time': iso_z(timezone.now()),
            },
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


class DeviceUnlinkUserView(APIView):
    """Logout: detach the current user from this install. Always 204 so the
    response never reveals whether the install exists or who owns it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: OpenApiResponse()})
    def delete(self, request, installation_id):
        services.unlink_user(installation_id=installation_id, user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
