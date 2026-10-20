"""Uploaded files (Aadhaar/PAN, complaint and expense attachments, property
images) live in a private GCS bucket and are only ever handed out as V4
signed URLs. Every serializer FileField goes through `storage.url()`, which
signs for GS_EXPIRATION; `signed_url()` lets a caller pick a different TTL.
Local dev storage (no GS_BUCKET_NAME) returns the plain media URL.
"""
from datetime import timedelta

from django.conf import settings


def _is_gcs(storage):
    try:
        from storages.backends.gcloud import GoogleCloudStorage
    except ImportError:  # pragma: no cover - django-storages[google] is a base requirement
        return False
    return isinstance(storage, GoogleCloudStorage)


def url_ttl_seconds():
    return int(settings.MEDIA_URL_TTL_SECONDS)


def signed_url(field_file, ttl_seconds=None):
    """Short-lived URL for a stored file. Never a public object URL."""
    storage = field_file.storage
    if _is_gcs(storage):
        ttl = url_ttl_seconds() if ttl_seconds is None else int(ttl_seconds)
        return storage.url(field_file.name, parameters={'expiration': timedelta(seconds=ttl)})
    return field_file.url
