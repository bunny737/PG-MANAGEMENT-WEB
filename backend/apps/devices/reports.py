"""Read-only queries over app installs (adoption, outdated installs, support
lookups, device mix). Used by the Django admin report; plain functions so they
are testable and reusable from a future API."""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from .models import AppInstallation, AppVersionPolicy

ACTIVE_WINDOW_DAYS = 7


def active_installations(days=ACTIVE_WINDOW_DAYS, now=None):
    since = (now or timezone.now()) - timedelta(days=days)
    return AppInstallation.objects.filter(last_seen_at__gte=since)


def active_installs_by_build(days=ACTIVE_WINDOW_DAYS, now=None):
    """The adoption chart: [{platform, flavor, build_number, count}], newest build first."""
    return list(
        active_installations(days, now)
        .values('platform', 'flavor', 'build_number')
        .annotate(count=Count('id'))
        .order_by('platform', 'flavor', '-build_number')
    )


def adoption_summary(days=ACTIVE_WINDOW_DAYS, now=None):
    """Per policy row: active installs, and how many are below latest / min build."""
    rows = []
    for policy in AppVersionPolicy.objects.order_by('platform', 'flavor'):
        stats = active_installations(days, now).filter(
            platform=policy.platform, flavor=policy.flavor,
        ).aggregate(
            active=Count('id'),
            below_latest=Count('id', filter=Q(build_number__lt=policy.latest_build)),
            below_min=Count('id', filter=Q(build_number__lt=policy.min_build)),
        )
        rows.append({'policy': policy, **stats})
    return rows


def installs_below_build(platform, flavor, build, days=ACTIVE_WINDOW_DAYS, now=None):
    return active_installations(days, now).filter(platform=platform, flavor=flavor, build_number__lt=build)


def lookup_installations(*, user=None, installation_id=None):
    """Crash/support lookup: model, OS version, build and last seen for a user or install."""
    qs = AppInstallation.objects.select_related('user').order_by('-last_seen_at')
    if user is not None:
        qs = qs.filter(user=user)
    if installation_id is not None:
        qs = qs.filter(installation_id=installation_id)
    return qs


def top_device_models(limit=10, days=ACTIVE_WINDOW_DAYS, now=None):
    return list(
        active_installations(days, now)
        .values('device_manufacturer', 'device_model')
        .annotate(count=Count('id'))
        .order_by('-count', 'device_model')[:limit]
    )


def top_os_versions(limit=10, days=ACTIVE_WINDOW_DAYS, now=None):
    return list(
        active_installations(days, now)
        .values('os_name', 'os_version')
        .annotate(count=Count('id'))
        .order_by('-count', 'os_version')[:limit]
    )
