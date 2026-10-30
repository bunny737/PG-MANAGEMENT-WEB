from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.roles import Role

# Roles a tutorial can be shown to — the staff app's audience (IsTenantStaff).
AUDIENCE_ROLES = (Role.OWNER, Role.MANAGER, Role.RECEPTIONIST)


def default_audience():
    return [str(role) for role in AUDIENCE_ROLES]


class TutorialVideo(models.Model):
    """A how-to video, one row per (topic, language), edited by a Super Admin in
    Django admin so videos can be added or replaced without a deploy.

    Platform-level and deliberately NOT tenant-scoped — the same class of table
    as PlatformConfig / NotificationTemplate. Only the YouTube id is stored:
    videos are unlisted YouTube uploads (owner decision 2026-10-28)."""

    class Topic(models.TextChoices):
        OVERVIEW = 'overview', _('Overview')
        ADD_PROPERTY = 'add_property', _('Add a property')
        ADD_BUILDING = 'add_building', _('Add a building')
        ADD_FLOOR = 'add_floor', _('Add a floor')
        ADD_ROOM = 'add_room', _('Add rooms and beds')
        ADMIT_RESIDENT = 'admit_resident', _('Admit a resident')
        PROPERTY_SETTINGS = 'property_settings', _('Property settings')
        EXPENSES = 'expenses', _('Expenses')
        BILLING = 'billing', _('Billing')
        STAFF = 'staff', _('Staff')

    topic = models.CharField(max_length=32, choices=Topic.choices)
    language = models.CharField(max_length=8, choices=settings.LANGUAGES)
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    youtube_id = models.CharField(
        max_length=11,
        validators=[RegexValidator(r'^[A-Za-z0-9_-]{11}$', _('Enter the 11-character YouTube video id.'))],
        help_text=_('The id from the video link, e.g. dQw4w9WgXcQ in youtu.be/dQw4w9WgXcQ.'),
    )
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    audience = models.JSONField(
        default=default_audience, blank=True,
        help_text=_('Roles that see this video: any of "owner", "manager", "receptionist".'),
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tutorial_videos'
        constraints = [
            models.UniqueConstraint(fields=['topic', 'language'], name='unique_tutorial_video_per_topic_language'),
        ]
        ordering = ['sort_order', 'topic', 'language']

    def clean(self):
        super().clean()
        allowed = default_audience()
        if not isinstance(self.audience, list) or not all(role in allowed for role in self.audience):
            raise ValidationError(
                {'audience': _('audience must be a list of: %(roles)s.') % {'roles': ', '.join(allowed)}},
            )

    def __str__(self):
        return f'{self.topic} [{self.language}] {self.title}'
