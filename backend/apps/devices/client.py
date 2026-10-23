"""Lenient parsing of the X-App-* request headers, plus the per-request log
context. A malformed or missing header must NEVER fail a request."""
import contextvars
import logging
import uuid
from dataclasses import dataclass, fields
from typing import Optional

from .choices import Flavor, Platform

MAX_BUILD = 2**31 - 1
_PLATFORMS = {c.value for c in Platform}
_FLAVORS = {c.value for c in Flavor}
_ATTRS = ('platform', 'version', 'build', 'flavor', 'installation_id')


@dataclass(frozen=True)
class AppClient:
    platform: Optional[str] = None
    version: Optional[str] = None
    build: Optional[int] = None
    flavor: Optional[str] = None
    installation_id: Optional[str] = None


def _parse_build(raw):
    raw = (raw or '').strip()
    if not raw.isascii() or not raw.isdigit():
        return None
    value = int(raw)
    return value if value <= MAX_BUILD else None


def _parse_uuid(raw):
    try:
        return str(uuid.UUID((raw or '').strip()))
    except (ValueError, AttributeError, TypeError):
        return None


def parse_app_client(request):
    """AppClient from the X-App-* headers, or None when none are usable."""
    meta = request.META
    platform = (meta.get('HTTP_X_APP_PLATFORM') or '').strip().lower()
    flavor = (meta.get('HTTP_X_APP_FLAVOR') or '').strip().lower()
    version = (meta.get('HTTP_X_APP_VERSION') or '').strip()[:64]
    client = AppClient(
        platform=platform if platform in _PLATFORMS else None,
        version=version or None,
        build=_parse_build(meta.get('HTTP_X_APP_BUILD')),
        flavor=flavor if flavor in _FLAVORS else None,
        installation_id=_parse_uuid(meta.get('HTTP_X_INSTALLATION_ID')),
    )
    if all(getattr(client, f.name) is None for f in fields(client)):
        return None
    return client


# --- log context / Sentry tags ------------------------------------------------

current_app_client = contextvars.ContextVar('current_app_client', default=None)


class AppClientLogFilter(logging.Filter):
    """Adds app_platform/app_version/app_build/app_flavor/app_installation_id
    to every record (reference them from the formatter)."""

    def filter(self, record):
        client = current_app_client.get()
        for attr in _ATTRS:
            value = getattr(client, attr, None) if client else None
            setattr(record, f'app_{attr}', '-' if value is None else value)
        return True


def tag_sentry(client):
    try:
        import sentry_sdk
    except ImportError:  # sentry-sdk is a prod-only requirement
        return
    for attr in _ATTRS:
        value = getattr(client, attr, None)
        if value is not None:
            sentry_sdk.set_tag(f'app.{attr}', value)
