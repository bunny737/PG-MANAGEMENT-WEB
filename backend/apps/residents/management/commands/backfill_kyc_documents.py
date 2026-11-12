"""Idempotent backfill & controlled purge of resident KYC objects into KYC storage.

Migration `0013` moved `Resident.aadhaar_document` / `Resident.pan_document` from
`default_storage` ($MEDIA_BUCKET) to `kyc_storage` ($KYC_BUCKET) without moving
any already-uploaded objects. Run `backfill_kyc_documents` before canary/smoke
(rollback-safe copy) and run `backfill_kyc_documents --delete-source
--purge-orphaned-legacy` post-cutover (or via `pglive-purge-legacy-kyc` once
legally approved) to delete all live and noncurrent generations under
`residents/` from `$MEDIA_BUCKET`.

Note: if `$MEDIA_BUCKET` has bucket-level `--soft-delete-duration=14d`, GCS
does not expose any API to force-purge already-soft-deleted generations before
`hard_delete_time`; deleted pre-migration bytes expire automatically after that
soft-delete window. New uploads after `0013` target `$KYC_BUCKET` directly
(`--no-versioning --soft-delete-duration=0`).
"""
import os
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils.functional import empty
from google.api_core.exceptions import GoogleAPIError, NotFound

from apps.core.storage import _is_gcs, kyc_storage
from apps.core.tenancy import tenant_context
from apps.residents.models import Resident
from apps.residents.services import KYC_FILE_FIELDS

LEGACY_KYC_PREFIX = 'residents/'


def _unwrap_storage(proxy):
    if hasattr(proxy, '_wrapped'):
        if proxy._wrapped is empty:
            proxy._setup()
        return proxy._wrapped
    return proxy


def _same_storage(src, dst):
    if src is dst:
        return True
    if _is_gcs(src) and _is_gcs(dst):
        return (src.bucket_name, getattr(src, 'project_id', None)) == (
            dst.bucket_name, getattr(dst, 'project_id', None),
        )
    if hasattr(src, 'location') and hasattr(dst, 'location'):
        return Path(os.path.abspath(src.location)) == Path(os.path.abspath(dst.location))
    return False


def _gcs_object_name(storage, key):
    if hasattr(storage, '_normalize_name'):
        return storage._normalize_name(key)
    return key


def _copy_object(src, dst, key):
    if _is_gcs(src) and _is_gcs(dst) and hasattr(src.bucket, 'copy_blob'):
        src_blob = src.bucket.get_blob(_gcs_object_name(src, key))
        if src_blob is None:
            raise FileNotFoundError(key)
        src.bucket.copy_blob(src_blob, dst.bucket, new_name=_gcs_object_name(dst, key))
        saved_name = key
    else:
        with src.open(key, 'rb') as handle:
            saved_name = dst.save(key, File(handle, name=key))
    if saved_name != key or not dst.exists(key):
        raise RuntimeError(f'target key mismatch after copy ({saved_name != key})')


def _delete_all_source_generations(src, key):
    """Delete live and noncurrent versions of `key` from `src`. Returns generation count removed."""
    if _is_gcs(src) and hasattr(src.bucket, 'list_blobs'):
        obj_name = _gcs_object_name(src, key)
        deleted = 0
        for blob in list(src.bucket.list_blobs(prefix=obj_name, versions=True)):
            if blob.name != obj_name:
                continue
            try:
                src.bucket.delete_blob(blob.name, generation=getattr(blob, 'generation', None))
                deleted += 1
            except NotFound:
                pass
        if deleted == 0 and src.exists(key):
            src.delete(key)
            deleted = 1
        return deleted

    if src.exists(key):
        src.delete(key)
        return 1
    return 0


def _iter_local_files(storage, prefix='residents'):
    try:
        directories, files = storage.listdir(prefix)
    except (FileNotFoundError, NotADirectoryError):
        return
    for name in files:
        yield f'{prefix}/{name}'
    for directory in directories:
        yield from _iter_local_files(storage, f'{prefix}/{directory}')


def inspect_legacy_media_residents(src):
    """Count live, noncurrent, and soft-deleted `residents/` objects remaining in `src`."""
    counts = {'live': 0, 'noncurrent': 0, 'soft_deleted': 0}
    if _is_gcs(src) and hasattr(src.bucket, 'list_blobs'):
        prefix = _gcs_object_name(src, LEGACY_KYC_PREFIX)
        for blob in src.bucket.list_blobs(prefix=prefix, versions=True):
            if getattr(blob, 'time_deleted', None) is not None:
                counts['noncurrent'] += 1
            else:
                counts['live'] += 1
        try:
            for _blob in src.bucket.list_blobs(prefix=prefix, soft_deleted=True):
                counts['soft_deleted'] += 1
        except (TypeError, GoogleAPIError):
            pass
        return counts

    counts['live'] = sum(1 for _ in _iter_local_files(src))
    return counts


def _purge_orphaned_legacy_residents(src):
    """Delete any remaining live/noncurrent `residents/` generations in `src`."""
    deleted = 0
    if _is_gcs(src) and hasattr(src.bucket, 'list_blobs'):
        prefix = _gcs_object_name(src, LEGACY_KYC_PREFIX)
        for blob in list(src.bucket.list_blobs(prefix=prefix, versions=True)):
            try:
                src.bucket.delete_blob(blob.name, generation=getattr(blob, 'generation', None))
                deleted += 1
            except NotFound:
                pass
        return deleted

    for path in list(_iter_local_files(src)):
        src.delete(path)
        deleted += 1
    return deleted


class Command(BaseCommand):
    help = 'Copy existing resident KYC objects from default storage into dedicated KYC storage idempotently.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Inspect DB references and storage without copying or deleting any objects.',
        )
        parser.add_argument(
            '--delete-source', action='store_true',
            help='Delete all live and noncurrent versions of migrated keys from default storage once verified in KYC storage.',
        )
        parser.add_argument(
            '--purge-orphaned-legacy', action='store_true',
            help='Requires --delete-source. Purge all remaining live and noncurrent residents/ objects from default storage.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        delete_source = options['delete_source']
        purge_orphaned = options['purge_orphaned_legacy']
        if purge_orphaned and not delete_source:
            raise CommandError('--purge-orphaned-legacy requires --delete-source.')

        src = _unwrap_storage(default_storage)
        dst = _unwrap_storage(kyc_storage)
        if 'kyc' not in settings.STORAGES or _same_storage(src, dst):
            self.stdout.write(
                'KYC storage shares the same location as default storage (or STORAGES["kyc"] is unset); '
                'nothing to backfill.'
            )
            return

        with tenant_context(is_super_admin=True):
            rows = list(
                Resident.objects.filter(
                    (Q(aadhaar_document__isnull=False) & ~Q(aadhaar_document=''))
                    | (Q(pan_document__isnull=False) & ~Q(pan_document=''))
                )
                .values('id', *KYC_FILE_FIELDS)
                .order_by('created_at', 'id')
            )

        scanned = 0
        already_in_kyc = 0
        copied = 0
        to_copy = 0
        deleted_source = 0
        deleted_generations = 0
        purged_orphaned_generations = 0
        missing = 0
        errors = 0
        problems = []

        for row in rows:
            resident_id = row['id']
            for field in KYC_FILE_FIELDS:
                key = (row[field] or '').strip()
                if not key:
                    continue
                scanned += 1
                try:
                    if dst.exists(key):
                        already_in_kyc += 1
                        if delete_source and not dry_run:
                            gens = _delete_all_source_generations(src, key)
                            if gens:
                                deleted_source += 1
                                deleted_generations += gens
                        continue

                    if not src.exists(key):
                        missing += 1
                        problems.append(
                            f'resident={resident_id} field={field}: missing from both default and kyc storage'
                        )
                        continue

                    if dry_run:
                        to_copy += 1
                        continue

                    _copy_object(src, dst, key)
                    copied += 1
                    if delete_source:
                        gens = _delete_all_source_generations(src, key)
                        if gens:
                            deleted_source += 1
                            deleted_generations += gens
                except Exception as exc:  # noqa: BLE001 - continue remaining rows and summarize safely
                    errors += 1
                    problems.append(f'resident={resident_id} field={field}: {type(exc).__name__}')

        if purge_orphaned and not dry_run and not missing and not errors:
            purged_orphaned_generations = _purge_orphaned_legacy_residents(src)

        remaining = inspect_legacy_media_residents(src)
        summary = (
            f'scanned={scanned} already_in_kyc={already_in_kyc} copied={copied} '
            f'to_copy={to_copy} deleted_source={deleted_source} '
            f'deleted_generations={deleted_generations} '
            f'purged_orphaned_generations={purged_orphaned_generations} '
            f'legacy_media_live={remaining["live"]} '
            f'legacy_media_noncurrent={remaining["noncurrent"]} '
            f'legacy_media_soft_deleted={remaining["soft_deleted"]} '
            f'missing={missing} errors={errors}'
        )
        if (deleted_generations or purged_orphaned_generations) and _is_gcs(src):
            self.stdout.write(
                'Note: default media storage uses GCS soft-delete retention (14d in infra/20-data.sh); '
                'deleted pre-migration source generations cannot be API-purged early and expire '
                'automatically at hardDeleteTime.'
            )
        if problems:
            raise CommandError(
                f'KYC backfill finished with problems ({summary}):\n- ' + '\n- '.join(problems)
            )
        self.stdout.write(self.style.SUCCESS(f'KYC backfill complete ({summary}).'))

