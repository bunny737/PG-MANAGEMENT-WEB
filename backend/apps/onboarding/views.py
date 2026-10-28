from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.audit import log as audit_log
from apps.core.permissions import IsTenantStaff

from .checklist import build_checklist
from .models import TutorialVideo
from .schema import ChecklistSerializer, TutorialVideoListSerializer, TutorialVideoSerializer

FALLBACK_LANGUAGE = 'en'
VIDEOS_CACHE_MAX_AGE_SECONDS = 300


class ChecklistView(APIView):
    """The Getting started checklist for ?property= (default: the visible
    property the caller can best act on now). See apps/onboarding/checklist.py."""

    permission_classes = [IsAuthenticated, IsTenantStaff]

    @extend_schema(
        parameters=[OpenApiParameter('property', str, description='Property UUID; default picks one.')],
        responses=ChecklistSerializer,
    )
    def get(self, request):
        return Response(build_checklist(request.user, request.query_params.get('property')))


class ChecklistDismissView(APIView):
    """POST hides the checklist for this user, DELETE shows it again. Both are
    idempotent: a repeat POST keeps the first timestamp, and only a real change
    is audit-logged."""

    permission_classes = [IsAuthenticated, IsTenantStaff]

    def _set(self, request, *, dismissed):
        user = request.user
        users = User.objects.filter(pk=user.pk)
        # A conditional UPDATE, so two racing requests can't both count as the change.
        if dismissed:
            now = timezone.now()
            changed = users.filter(onboarding_dismissed_at__isnull=True).update(onboarding_dismissed_at=now)
            before, after = None, now.isoformat()
        else:
            previous = user.onboarding_dismissed_at
            changed = users.filter(onboarding_dismissed_at__isnull=False).update(onboarding_dismissed_at=None)
            before, after = (previous.isoformat() if previous else None), None
        if changed:
            audit_log.record(
                action='onboarding.dismissed' if dismissed else 'onboarding.restored',
                actor=user, obj=user,
                before={'onboarding_dismissed_at': before}, after={'onboarding_dismissed_at': after},
                request=request,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        return self._set(request, dismissed=True)

    @extend_schema(request=None, responses={204: None})
    def delete(self, request):
        return self._set(request, dismissed=False)


class TutorialVideoListView(APIView):
    """Active tutorial videos the caller's role may see, one per topic, in
    ?language= (default: the user's language), falling back to English only.
    Role filtering happens before the fallback, so a video the caller can't see
    never hides an English one they can."""

    permission_classes = [IsAuthenticated, IsTenantStaff]

    @extend_schema(
        parameters=[OpenApiParameter('language', str, description='Language code; default is the user’s.')],
        responses=TutorialVideoListSerializer,
    )
    def get(self, request):
        language = request.query_params.get('language') or request.user.language_code
        if language not in dict(settings.LANGUAGES):
            raise ValidationError(
                {'language': _('language must be one of: %(codes)s.') % {
                    'codes': ', '.join(code for code, _name in settings.LANGUAGES)}},
                code='invalid_language',
            )
        visible = TutorialVideo.objects.filter(
            is_active=True, audience__contains=[request.user.role],
            language__in={language, FALLBACK_LANGUAGE},
        )
        chosen = {}
        for video in visible:
            if video.topic not in chosen or video.language == language:
                chosen[video.topic] = video
        videos = sorted(chosen.values(), key=lambda v: (v.sort_order, v.topic))
        response = Response({
            'requested_language': language,
            'videos': TutorialVideoSerializer(videos, many=True).data,
        })
        response['Cache-Control'] = f'private, max-age={VIDEOS_CACHE_MAX_AGE_SECONDS}'
        return response
