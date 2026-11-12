"""Deploy preflight for resident KYC GCS storage (`pglive-check-kyc`).

Validates that the dedicated KYC bucket exists, enforces hard deletion
(no object versioning and 0s soft-delete retention), enforces UBLA + public
access prevention, grants the API runtime account the required object
permissions + IAM SignBlob URL signing capability, and has zero unmigrated
resident KYC documents missing from KYC storage.
"""
from datetime import timedelta
import os
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils.functional import empty
from google.api_core.exceptions import Forbidden, GoogleAPIError, NotFound

from apps.core.storage import _is_gcs, kyc_storage
from apps.core.tenancy import tenant_context
from apps.residents.models import Resident
from apps.residents.services import KYC_FILE_FIELDS

REQUIRED_OBJECT_PERMISSIONS = (
    'storage.objects.create',
    'storage.objects.get',
    'storage.objects.delete',
    'storage.objects.list',
)


def _unwrap_storage(proxy):
    if hasattr(proxy, '_wrapped'):
        if proxy._wrapped is empty:
            proxy._setup()
        return proxy._wrapped
    return proxy


class Command(BaseCommand):
    help = 'Validate KYC bucket existence, hard-delete settings, IAM permissions, URL signing, and backfill.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--require', action='store_true',
            help='Require dedicated GCS KYC bucket checks even when KYC_UPLOADS_ENABLED is False.',
        )

    def handle(self, *args, **options):
        enabled = bool(settings.KYC_UPLOADS_ENABLED)
        expect_enabled = os.environ.get('EXPECT_KYC_UPLOADS_ENABLED', '').lower() == 'true'
        bucket_name = (getattr(settings, 'GS_KYC_BUCKET_NAME', '') or '').strip()
        media_bucket = (getattr(settings, 'GS_BUCKET_NAME', '') or '').strip()

        if not (options['require'] or enabled or expect_enabled or bucket_name):
            self.stdout.write('KYC storage preflight skipped (uploads disabled and GS_KYC_BUCKET_NAME unset).')
            return

        problems = []
        if expect_enabled and not enabled:
            problems.append('EXPECT_KYC_UPLOADS_ENABLED=true but settings.KYC_UPLOADS_ENABLED is False.')

        if not bucket_name:
            problems.append('GS_KYC_BUCKET_NAME must be configured.')
        elif bucket_name == media_bucket:
            problems.append(f'GS_KYC_BUCKET_NAME ({bucket_name!r}) must be distinct from GS_BUCKET_NAME.')

        storage_backend = None
        if 'kyc' not in settings.STORAGES:
            problems.append("STORAGES['kyc'] is not configured.")
        else:
            storage_backend = _unwrap_storage(kyc_storage)
            if not _is_gcs(storage_backend):
                problems.append("STORAGES['kyc'] must use GoogleCloudStorage.")
                storage_backend = None

        if storage_backend is not None:
            if getattr(storage_backend, 'iam_sign_blob', False) and not getattr(storage_backend, 'sa_email', None):
                problems.append('GS_SA_EMAIL must be configured when GS_IAM_SIGN_BLOB=True.')

            bucket = storage_backend.bucket
            reloaded = False
            try:
                bucket.reload()
                reloaded = True
            except NotFound:
                problems.append(
                    f'KYC bucket gs://{bucket_name} does not exist; run infra/20-data.sh to provision it.'
                )
            except Forbidden:
                problems.append(
                    f'Caller lacks storage.buckets.get on gs://{bucket_name}; '
                    'run infra/20-data.sh to grant pglive.bucketMetadataReader to sa-api.'
                )
            except GoogleAPIError as exc:
                problems.append(f'Failed inspecting gs://{bucket_name} metadata ({type(exc).__name__}).')

            if reloaded:
                if bucket.versioning_enabled:
                    problems.append(
                        f'KYC bucket gs://{bucket_name} has object versioning enabled (--no-versioning required).'
                    )
                retention = getattr(bucket.soft_delete_policy, 'retention_duration_seconds', None)
                if retention not in (None, 0):
                    problems.append(
                        f'KYC bucket gs://{bucket_name} has soft-delete retention={retention}s '
                        '(--soft-delete-duration=0 required).'
                    )
                iam_cfg = bucket.iam_configuration
                if not iam_cfg.uniform_bucket_level_access_enabled:
                    problems.append(
                        f'KYC bucket gs://{bucket_name} must enable uniform bucket-level access.'
                    )
                if iam_cfg.public_access_prevention != 'enforced':
                    problems.append(
                        f'KYC bucket gs://{bucket_name} must enforce public access prevention '
                        f'(got {iam_cfg.public_access_prevention!r}).'
                    )

                try:
                    granted = set(bucket.test_iam_permissions(list(REQUIRED_OBJECT_PERMISSIONS)))
                    missing_perms = [perm for perm in REQUIRED_OBJECT_PERMISSIONS if perm not in granted]
                    if missing_perms:
                        problems.append(
                            f'Caller lacks KYC bucket permissions on gs://{bucket_name}: '
                            + ', '.join(missing_perms)
                        )
                except GoogleAPIError as exc:
                    problems.append(f'Failed testing IAM permissions on gs://{bucket_name} ({type(exc).__name__}).')

                try:
                    signed = storage_backend.url(
                        '__preflight_probe__', parameters={'expiration': timedelta(seconds=60)},
                    )
                    parsed = urlparse(signed)
                    params = parse_qs(parsed.query)
                    if parsed.scheme != 'https' or 'X-Goog-Signature' not in params:
                        problems.append('KYC signed URL probe did not return an HTTPS V4 signed URL.')
                except Exception as exc:  # noqa: BLE001 - surface credential / SignBlob errors cleanly
                    problems.append(
                        f'KYC URL signing check failed ({type(exc).__name__}); '
                        'verify roles/iam.serviceAccountTokenCreator and GS_SA_EMAIL.'
                    )

                # Confirm no resident row still references a document missing from KYC storage.
                with tenant_context(is_super_admin=True):
                    rows = list(
                        Resident.objects.filter(
                            (Q(aadhaar_document__isnull=False) & ~Q(aadhaar_document=''))
                            | (Q(pan_document__isnull=False) & ~Q(pan_document=''))
                        ).values(*KYC_FILE_FIELDS)
                    )
                missing_in_kyc = 0
                for row in rows:
                    for field in KYC_FILE_FIELDS:
                        key = (row[field] or '').strip()
                        if key and not storage_backend.exists(key):
                            missing_in_kyc += 1
                if missing_in_kyc:
                    problems.append(
                        f'{missing_in_kyc} resident KYC document(s) referenced in the DB are missing from '
                        f'gs://{bucket_name}; run manage.py backfill_kyc_documents.'
                    )

        if problems:
            raise CommandError('KYC storage preflight failed:\n- ' + '\n- '.join(problems))
        self.stdout.write(
            self.style.SUCCESS(
                f'KYC storage preflight passed for gs://{bucket_name} '
                f'(uploads_enabled={enabled}, hard-delete=on, signing=ok, missing_docs=0).'
            )
        )

