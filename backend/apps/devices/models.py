import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .choices import DEFAULT_CHECK_INTERVAL_SECONDS, Flavor, Platform  # noqa: F401


class AppInstallation(models.Model):
    """One install of the mobile app (identified by a client-generated UUID).

    Platform-level, NOT under RLS (no tenant_id): the app registers itself
    before login, and a device can be used by users of different tenants over
    its lifetime. Holds no name/phone/email/location/advertising ID — the user
    link is a bare FK, SET_NULL so deleting a user leaves an anonymous row.
    """

    installation_id = models.UUIDField(unique=True, default=uuid.uuid4)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='app_installations',
    )

    platform = models.CharField(max_length=10, choices=Platform.choices)
    flavor = models.CharField(max_length=10, choices=Flavor.choices)
    build_mode = models.CharField(max_length=16, blank=True)

    version_name = models.CharField(max_length=64, blank=True)
    build_number = models.PositiveIntegerField()
    package_id = models.CharField(max_length=128, blank=True)

    os_name = models.CharField(max_length=64, blank=True)
    os_version = models.CharField(max_length=64, blank=True)
    os_sdk_int = models.PositiveIntegerField(null=True, blank=True)

    device_manufacturer = models.CharField(max_length=64, blank=True)
    device_model = models.CharField(max_length=64, blank=True)
    is_physical = models.BooleanField(default=True)

    screen_width_px = models.PositiveIntegerField(null=True, blank=True)
    screen_height_px = models.PositiveIntegerField(null=True, blank=True)
    pixel_ratio = models.FloatField(null=True, blank=True)

    locale = models.CharField(max_length=16, blank=True)
    utc_offset_minutes = models.IntegerField(null=True, blank=True)
    timezone_abbr = models.CharField(max_length=16, blank=True)
    network_type = models.CharField(max_length=32, blank=True)

    push_permission = models.CharField(max_length=32, blank=True)
    # A token belongs to exactly one install: registration nulls it on any
    # other holder first. NULLs don't collide under the unique constraint.
    fcm_token = models.CharField(max_length=255, null=True, blank=True, unique=True)

    last_sync_seq = models.BigIntegerField(default=0)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'app_installations'
        indexes = [models.Index(fields=['platform', 'build_number'], name='appinst_platform_build_idx')]

    def __str__(self):
        return f'{self.platform} {self.version_name or self.build_number} [{self.installation_id}]'


class AppInstallationHistory(models.Model):
    """Append-only: one row per observed (build_number, os_version) change of
    an install, including the first sighting. Powers the upgrade funnel."""

    installation = models.ForeignKey(AppInstallation, on_delete=models.CASCADE, related_name='history')
    build_number = models.PositiveIntegerField()
    version_name = models.CharField(max_length=64, blank=True)
    os_version = models.CharField(max_length=64, blank=True)
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'app_installation_history'
        ordering = ['-recorded_at', '-id']
        verbose_name_plural = 'app installation history'


class AppVersionPolicy(models.Model):
    """Super-Admin-editable version/maintenance policy, one row per
    (platform, flavor) — invariant 10: nothing here is a code constant."""

    platform = models.CharField(max_length=10, choices=Platform.choices)
    flavor = models.CharField(max_length=10, choices=Flavor.choices, default=Flavor.PROD)

    min_build = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)],
        help_text=_('Builds below this are force-updated. Raise only after the new build is fully live in the store.'),
    )
    latest_build = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    latest_version = models.CharField(max_length=64, blank=True)
    store_url = models.URLField(max_length=500, blank=True)
    release_notes = models.JSONField(default=dict, blank=True, help_text=_('{"en": "...", "te": "..."}'))
    soft_update_enabled = models.BooleanField(default=True)

    maintenance_enabled = models.BooleanField(default=False)
    maintenance_message = models.CharField(max_length=500, blank=True)
    maintenance_expires_at = models.DateTimeField(null=True, blank=True)

    check_interval_seconds = models.PositiveIntegerField(
        default=DEFAULT_CHECK_INTERVAL_SECONDS, validators=[MinValueValidator(60)],
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'app_version_policies'
        constraints = [
            models.UniqueConstraint(fields=['platform', 'flavor'], name='unique_app_policy_per_platform_flavor'),
        ]
        verbose_name_plural = 'app version policies'

    def clean(self):
        super().clean()
        if self.latest_build is not None and self.min_build is not None and self.latest_build < self.min_build:
            raise ValidationError({'latest_build': _('latest_build must be greater than or equal to min_build.')})
        if self.release_notes is not None and not isinstance(self.release_notes, dict):
            raise ValidationError({'release_notes': _('release_notes must be a JSON object keyed by locale.')})

    def __str__(self):
        return f'{self.platform}/{self.flavor} min={self.min_build} latest={self.latest_build}'
