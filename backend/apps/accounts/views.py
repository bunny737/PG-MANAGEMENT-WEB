from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.core.permissions import require_permission
from apps.core.roles import STAFF_ROLES

from .models import User
from .serializers import (
    EmailVerificationSerializer,
    LoginSerializer,
    MeSerializer,
    MeUpdateSerializer,
    OtpRequestSerializer,
    OtpVerifySerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RefreshSerializer,
    ResendVerificationSerializer,
    SignupSerializer,
    StaffCreateSerializer,
    StaffSerializer,
    StaffUpdateSerializer,
    TokenPairSerializer,
)


class _AnonPostView(APIView):
    """Unauthenticated POST endpoint: validate serializer, run save(), reply 200."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    serializer_class = None
    success_message = _('OK')

    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'detail': self.success_message})


class SignupView(_AnonPostView):
    serializer_class = SignupSerializer
    throttle_scope = 'signup'
    success_message = _('Account created. Check your email to verify your address.')

    def post(self, request):
        response = super().post(request)
        response.status_code = status.HTTP_201_CREATED
        return response


class VerifyEmailView(_AnonPostView):
    serializer_class = EmailVerificationSerializer
    throttle_scope = 'verify_email'
    success_message = _('Email verified. You can log in now.')


class ResendVerificationView(_AnonPostView):
    serializer_class = ResendVerificationSerializer
    throttle_scope = 'resend_verification'
    success_message = _('If that email is registered, a verification link has been sent.')


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'


class RefreshView(TokenRefreshView):
    serializer_class = RefreshSerializer


class OtpRequestView(_AnonPostView):
    serializer_class = OtpRequestSerializer
    throttle_scope = 'otp_request'
    success_message = _('If that phone number is registered, a code has been sent.')


class OtpVerifyView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp_verify'

    def get_authenticate_header(self, request):
        # Makes failed OTP logins 401 (like /login/) instead of DRF's 403 fallback.
        return 'Bearer realm="api"'

    @extend_schema(request=OtpVerifySerializer, responses=TokenPairSerializer)
    def post(self, request):
        serializer = OtpVerifySerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data)


class PasswordResetRequestView(_AnonPostView):
    serializer_class = PasswordResetRequestSerializer
    throttle_scope = 'password_reset'
    success_message = _('If that email is registered, a reset link has been sent.')


class PasswordResetConfirmView(_AnonPostView):
    serializer_class = PasswordResetConfirmSerializer
    throttle_scope = 'password_reset'
    success_message = _('Password updated. You can log in now.')


class MeView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch']

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        return MeUpdateSerializer if self.request.method == 'PATCH' else MeSerializer

    def partial_update(self, request, *args, **kwargs):
        super().partial_update(request, *args, **kwargs)
        return Response(MeSerializer(request.user).data)


class StaffViewSet(viewsets.ModelViewSet):
    """Owner-managed Manager/Receptionist accounts (PRD §6). No delete —
    staff are deactivated so history stays intact. Property assignment
    arrives with Module 02."""

    permission_classes = [IsAuthenticated, require_permission('manage_staff_accounts')]
    http_method_names = ['get', 'post', 'patch']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):  # schema generation
            return User.objects.none()
        # App-level tenant scoping: the users table is deliberately outside RLS.
        return (
            User.objects.filter(tenant=self.request.user.tenant, role__in=STAFF_ROLES)
            .order_by('created_at')
        )

    def get_serializer_class(self):
        if self.action == 'create':
            return StaffCreateSerializer
        if self.action == 'partial_update':
            return StaffUpdateSerializer
        return StaffSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(StaffSerializer(user).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(StaffSerializer(instance).data)
