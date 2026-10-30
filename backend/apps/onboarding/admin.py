from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.audit import log as audit_log

from .models import TutorialVideo

AUDIT_FIELDS = (
    'topic', 'language', 'title', 'description', 'youtube_id',
    'duration_seconds', 'sort_order', 'is_active', 'audience',
)


def video_snapshot(video):
    return {name: getattr(video, name) for name in AUDIT_FIELDS}


@admin.register(TutorialVideo)
class TutorialVideoAdmin(admin.ModelAdmin):
    """Super Admin catalog of how-to videos (Module 23): one unlisted YouTube
    video per (topic, language). Changes are audit-logged as platform records."""

    list_display = ('topic', 'language', 'title', 'is_active', 'sort_order', 'thumbnail', 'updated_at')
    list_filter = ('topic', 'language', 'is_active')
    search_fields = ('title', 'youtube_id')
    ordering = ('sort_order', 'topic', 'language')
    readonly_fields = ('thumbnail', 'updated_by', 'created_at', 'updated_at')

    @admin.display(description=_('Preview'))
    def thumbnail(self, obj):
        if not obj.youtube_id:
            return '—'
        return format_html(
            '<img src="https://i.ytimg.com/vi/{}/mqdefault.jpg" width="160" alt="">', obj.youtube_id,
        )

    def save_model(self, request, obj, form, change):
        before = video_snapshot(TutorialVideo.objects.get(pk=obj.pk)) if change else None
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
        audit_log.record(
            action='tutorial_video.updated' if change else 'tutorial_video.created',
            actor=request.user, tenant_id=None, obj=obj,
            before=before, after=video_snapshot(obj), request=request,
        )

    def delete_model(self, request, obj):
        before = video_snapshot(obj)
        audit_log.record(
            action='tutorial_video.deleted', actor=request.user, tenant_id=None, obj=obj,
            before=before, after=None, request=request,
        )
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for video in queryset:
            self.delete_model(request, video)
