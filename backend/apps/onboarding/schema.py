"""Schema-only response shapes for the checklist and video endpoints, which
build plain dicts (checklist.py, views.py). Nothing here serializes a real
response; the classes give drf-spectacular — and so the web client's generated
types — a real shape. Keep them in sync with checklist.py."""
from django.conf import settings
from rest_framework import serializers

from . import checklist
from .models import TutorialVideo

STEP_KEYS = checklist.REQUIRED_STEPS + (checklist.RECORD_EXPENSE,)


class ChecklistTargetPropertySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class ChecklistProgressSerializer(serializers.Serializer):
    done = serializers.IntegerField()
    total = serializers.IntegerField()


class ChecklistStepParamsSerializer(serializers.Serializer):
    property_id = serializers.UUIDField(required=False)
    building_id = serializers.UUIDField(required=False)
    floor_id = serializers.UUIDField(required=False)


class ChecklistStepSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=STEP_KEYS)
    required = serializers.BooleanField()
    done = serializers.BooleanField()
    permitted = serializers.BooleanField()
    blocked_by = serializers.ChoiceField(choices=checklist.REQUIRED_STEPS, allow_null=True)
    params = ChecklistStepParamsSerializer()
    video_topic = serializers.ChoiceField(choices=TutorialVideo.Topic.choices)


class ChecklistSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=(checklist.IN_PROGRESS, checklist.COMPLETED, checklist.NO_ACTIONS))
    dismissed = serializers.BooleanField()
    target_property = ChecklistTargetPropertySerializer(allow_null=True)
    progress = ChecklistProgressSerializer()
    next_step = serializers.ChoiceField(choices=checklist.REQUIRED_STEPS, allow_null=True)
    steps = ChecklistStepSerializer(many=True)


class TutorialVideoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TutorialVideo
        fields = ['topic', 'language', 'title', 'description', 'youtube_id', 'duration_seconds']
        read_only_fields = fields


class TutorialVideoListSerializer(serializers.Serializer):
    requested_language = serializers.ChoiceField(choices=settings.LANGUAGES)
    # Languages with at least one active video this role can see, in settings.LANGUAGES order.
    available_languages = serializers.ListField(child=serializers.ChoiceField(choices=settings.LANGUAGES))
    videos = TutorialVideoSerializer(many=True)
