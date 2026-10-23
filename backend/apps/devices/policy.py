"""Cached read access to AppVersionPolicy, shared by the version-policy
endpoint and the enforcement middleware (one DB lookup per 60 s per
platform/flavor, invalidated immediately when a policy is saved)."""
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from typing import Optional

from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import DEFAULT_CHECK_INTERVAL_SECONDS, AppVersionPolicy

POLICY_CACHE_TTL_SECONDS = 60
_MISSING = 'missing'


@dataclass(frozen=True)
class PolicySnapshot:
    min_build: int
    latest_build: int
    latest_version: str
    store_url: str
    release_notes: dict = field(default_factory=dict)
    soft_update_enabled: bool = True
    maintenance_enabled: bool = False
    maintenance_message: str = ''
    maintenance_expires_at: Optional[datetime] = None
    check_interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS

    def maintenance_active(self, now=None):
        if not self.maintenance_enabled:
            return False
        if self.maintenance_expires_at is None:
            return True
        return self.maintenance_expires_at > (now or timezone.now())

    def update_mode(self, build):
        """Integers only — never compare version strings."""
        if build < self.min_build:
            return 'force'
        if build < self.latest_build and self.soft_update_enabled:
            return 'soft'
        return 'none'


def cache_key(platform, flavor):
    return f'app_version_policy:{platform}:{flavor}'


def get_policy(platform, flavor):
    """The policy for (platform, flavor), or None when no row exists."""
    key = cache_key(platform, flavor)
    cached = cache.get(key)
    if isinstance(cached, str) and cached == _MISSING:
        return None
    if cached is not None:
        return cached
    row = AppVersionPolicy.objects.filter(platform=platform, flavor=flavor).first()
    if row is None:
        cache.set(key, _MISSING, POLICY_CACHE_TTL_SECONDS)
        return None
    snapshot = PolicySnapshot(
        min_build=row.min_build, latest_build=row.latest_build,
        latest_version=row.latest_version, store_url=row.store_url,
        release_notes=row.release_notes or {}, soft_update_enabled=row.soft_update_enabled,
        maintenance_enabled=row.maintenance_enabled, maintenance_message=row.maintenance_message,
        maintenance_expires_at=row.maintenance_expires_at,
        check_interval_seconds=row.check_interval_seconds,
    )
    cache.set(key, snapshot, POLICY_CACHE_TTL_SECONDS)
    return snapshot


def iso_z(value):
    """UTC ISO-8601 with a trailing Z (the wire format the app parses)."""
    if value is None:
        return None
    return value.astimezone(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@receiver([post_save, post_delete], sender=AppVersionPolicy)
def _invalidate_policy_cache(sender, instance, **kwargs):
    key = cache_key(instance.platform, instance.flavor)
    cache.delete(key)
    # Again after commit: a request between the delete and the commit could
    # have re-cached the pre-commit row.
    transaction.on_commit(lambda: cache.delete(key))
