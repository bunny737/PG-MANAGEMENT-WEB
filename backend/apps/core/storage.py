"""Uploaded files (complaint and expense attachments, property images, resident
KYC documents) live in private GCS buckets and are only ever handed out as V4
signed URLs. Resident KYC documents use a dedicated non-versioned bucket when
GS_KYC_BUCKET_NAME is configured so deletions are immediate hard deletes.
Local dev storage (no bucket configured) returns the plain media URL.
"""
from datetime import timedelta
import logging

from django.conf import settings
from django.core.files.storage import default_storage, storages
from django.core.signals import setting_changed
from django.db import transaction
from django.dispatch import receiver
from django.utils.functional import LazyObject, empty

logger = logging.getLogger(__name__)


class KycStorage(LazyObject):
    """Dedicated storage for resident KYC documents, falling back to default_storage."""

    def _setup(self):
        self._wrapped = storages['kyc'] if 'kyc' in settings.STORAGES else default_storage


kyc_storage = KycStorage()


@receiver(setting_changed)
def _reset_kyc_storage(*, setting, **kwargs):
    if setting in ('STORAGES', 'MEDIA_ROOT', 'MEDIA_URL', 'GS_KYC_BUCKET_NAME'):
        kyc_storage._wrapped = empty


def get_kyc_storage():
    """Callable storage getter so Django migrations stay portable across dev/prod."""
    return kyc_storage


def delete_storage_object_on_commit(storage, name, *, tenant_id=None, object_id=None, field=''):
    """Schedule best-effort deletion of a replaced/cleared object after DB commit.

    Storage deletes are irreversible and outside the database transaction. Once
    the DB update has committed, a storage delete error must not convert an
    already-committed request into a 500 or leak object keys into logs.
    """
    if not name or storage is None:
        return

    def _delete():
        try:
            storage.delete(name)
        except Exception as exc:
            logger.error(
                'storage_post_commit_delete_failed tenant_id=%s object_id=%s field=%s error=%s',
                tenant_id, object_id, field, type(exc).__name__,
            )

    transaction.on_commit(_delete)


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
