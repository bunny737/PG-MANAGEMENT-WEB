"""Idempotent backfill of existing resident KYC objects into the dedicated KYC storage.

Migration `0013` moved `Resident.aadhaar_document` / `Resident.pan_document` from
`default_storage` ($MEDIA_BUCKET) to `kyc_storage` ($KYC_BUCKET) without moving
any already-uploaded objects. Run this before flipping live traffic (or via the
`pglive-backfill-kyc` Cloud Run job) so pre-existing documents remain readable
under the dedicated KYC bucket. Safe when 0 documents exist and safe to re-run.
"""
import os
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils.functional import empty

from apps.core.storage import _is_gcs, kyc_storage
from apps.core.tenancy import tenant_context
from apps.residents.models import Resident
from apps.residents.services import KYC_FILE_FIELDS


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


def _copy_object(src, dst, key):
    if _is_gcs(src) and _is_gcs(dst) and hasattr(src.bucket, 'copy_blob'):
        src_blob = src.bucket.get_blob(key)
        if src_blob is None:
            raise FileNotFoundError(key)
        src.bucket.copy_blob(src_blob, dst.bucket, new_name=key)
        saved_name = key
    else:
        with src.open(key, 'rb') as handle:
            saved_name = dst.save(key, File(handle, name=key))
    if saved_name != key or not dst.exists(key):
        raise RuntimeError(f'target key mismatch after copy ({saved_name != key})')


class Command(BaseCommand):
    help = 'Copy existing resident KYC objects from default storage into dedicated KYC storage idempotently.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Inspect DB references and storage without copying or deleting any objects.',
        )
        parser.add_argument(
            '--delete-source', action='store_true',
            help='Delete the source object from default storage once verified present in KYC storage.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        delete_source = options['delete_source']

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
                        if delete_source and not dry_run and src.exists(key):
                            src.delete(key)
                            deleted_source += 1
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
                        src.delete(key)
                        deleted_source += 1
                except Exception as exc:  # noqa: BLE001 - continue remaining rows and summarize safely
                    errors += 1
                    problems.append(f'resident={resident_id} field={field}: {type(exc).__name__}')

        summary = (
            f'scanned={scanned} already_in_kyc={already_in_kyc} copied={copied} '
            f'to_copy={to_copy} deleted_source={deleted_source} missing={missing} errors={errors}'
        )
        if problems:
            raise CommandError(
                f'KYC backfill finished with problems ({summary}):\n- ' + '\n- '.join(problems)
            )
        self.stdout.write(self.style.SUCCESS(f'KYC backfill complete ({summary}).'))

