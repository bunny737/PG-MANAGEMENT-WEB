"""Tests for KYC storage preflight (`check_kyc_storage`) and backfill (`backfill_kyc_documents`)."""
import io
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from google.api_core.exceptions import Forbidden, NotFound
from storages.backends.gcloud import GoogleCloudStorage

from apps.core.tenancy import tenant_context
from apps.core.test_deployment import _fake_service_account
from apps.residents.models import Resident

from .base import ResidentAPITestCase

PDF = b'%PDF-1.4 ' + b'0' * 32


class BackfillKycDocumentsCommandTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.media_dir = tempfile.mkdtemp()
        self.kyc_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, True)
        self.addCleanup(shutil.rmtree, self.kyc_dir, True)

        self.tenant = self.create_tenant()
        self.prop = self.create_property(self.tenant)
        self.resident = self.create_resident(self.prop, first_name='Ravi', phone='9000000001')

    def _storages(self):
        return {
            **settings.STORAGES,
            'default': {
                'BACKEND': 'django.core.files.storage.FileSystemStorage',
                'OPTIONS': {'location': self.media_dir},
            },
            'kyc': {
                'BACKEND': 'django.core.files.storage.FileSystemStorage',
                'OPTIONS': {'location': self.kyc_dir},
            },
        }

    def test_backfill_is_idempotent_supports_dry_run_and_delete_source_without_pii(self):
        src_storage = FileSystemStorage(location=self.media_dir)
        dst_storage = FileSystemStorage(location=self.kyc_dir)
        key = f'residents/{self.tenant.id}/{self.resident.id}/legacy_aadhaar_9999.pdf'
        src_storage.save(key, ContentFile(PDF))
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=self.resident.pk).update(aadhaar_document=key)

        with override_settings(STORAGES=self._storages()):
            dry_out = io.StringIO()
            call_command('backfill_kyc_documents', '--dry-run', stdout=dry_out)
            self.assertIn('scanned=1 already_in_kyc=0 copied=0 to_copy=1', dry_out.getvalue())
            self.assertFalse(dst_storage.exists(key))

            first_out = io.StringIO()
            call_command('backfill_kyc_documents', stdout=first_out)
            self.assertIn('scanned=1 already_in_kyc=0 copied=1', first_out.getvalue())
            self.assertTrue(dst_storage.exists(key))
            self.assertEqual(dst_storage.open(key, 'rb').read(), PDF)
            self.assertTrue(src_storage.exists(key))

            # Second run is a clean idempotent no-op, and --delete-source cleans up source cleanly.
            second_out = io.StringIO()
            call_command('backfill_kyc_documents', '--delete-source', stdout=second_out)
            self.assertIn('already_in_kyc=1 copied=0 to_copy=0 deleted_source=1 deleted_generations=1', second_out.getvalue())
            self.assertIn('legacy_media_live=0', second_out.getvalue())
            self.assertTrue(dst_storage.exists(key))
            self.assertFalse(src_storage.exists(key))
            self.assertNotIn('legacy_aadhaar_9999.pdf', first_out.getvalue() + second_out.getvalue())

    def test_backfill_purge_orphaned_legacy_requires_delete_source_and_clears_leftovers(self):
        src_storage = FileSystemStorage(location=self.media_dir)
        dst_storage = FileSystemStorage(location=self.kyc_dir)
        active_key = f'residents/{self.tenant.id}/{self.resident.id}/active.pdf'
        orphan_key = f'residents/{self.tenant.id}/{self.resident.id}/replaced_old.pdf'
        src_storage.save(active_key, ContentFile(PDF))
        src_storage.save(orphan_key, ContentFile(PDF))
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=self.resident.pk).update(aadhaar_document=active_key)

        with override_settings(STORAGES=self._storages()):
            with self.assertRaises(CommandError):
                call_command('backfill_kyc_documents', '--purge-orphaned-legacy', stdout=io.StringIO())

            out = io.StringIO()
            call_command('backfill_kyc_documents', '--delete-source', '--purge-orphaned-legacy', stdout=out)
        self.assertTrue(dst_storage.exists(active_key))
        self.assertFalse(src_storage.exists(active_key))
        self.assertFalse(src_storage.exists(orphan_key))
        self.assertIn('purged_orphaned_generations=1', out.getvalue())
        self.assertIn('legacy_media_live=0', out.getvalue())

    def test_backfill_delete_source_removes_all_gcs_generations_live_and_noncurrent(self):
        creds = _fake_service_account()
        storages_cfg = {
            **settings.STORAGES,
            'default': {
                'BACKEND': 'storages.backends.gcloud.GoogleCloudStorage',
                'OPTIONS': {'bucket_name': 'pglive-media', 'project_id': 'test', 'credentials': creds, 'iam_sign_blob': False},
            },
            'kyc': {
                'BACKEND': 'storages.backends.gcloud.GoogleCloudStorage',
                'OPTIONS': {'bucket_name': 'pglive-kyc', 'project_id': 'test', 'credentials': creds, 'iam_sign_blob': False},
            },
        }
        key = f'residents/{self.tenant.id}/{self.resident.id}/versioned.pdf'
        orphan_key = f'residents/{self.tenant.id}/{self.resident.id}/old_orphan.pdf'
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=self.resident.pk).update(aadhaar_document=key)

        blobs = [
            mock.Mock(name='gen1', generation=101, time_deleted='2026-11-01T00:00:00Z'),
            mock.Mock(name='gen2', generation=102, time_deleted=None),
            mock.Mock(name='orphan1', generation=201, time_deleted='2026-11-02T00:00:00Z'),
        ]
        blobs[0].name = key
        blobs[1].name = key
        blobs[2].name = orphan_key

        deleted_calls = []
        src_bucket = mock.Mock(name='media_bucket')
        dst_bucket = mock.Mock(name='kyc_bucket')

        def fake_list_blobs(prefix='', versions=None, soft_deleted=None):
            if soft_deleted:
                return []
            return [b for b in blobs if b.name.startswith(prefix)]

        def fake_delete_blob(blob_name, generation=None):
            deleted_calls.append((blob_name, generation))
            blobs[:] = [b for b in blobs if not (b.name == blob_name and b.generation == generation)]

        src_bucket.list_blobs.side_effect = fake_list_blobs
        src_bucket.delete_blob.side_effect = fake_delete_blob
        src_bucket.get_blob.return_value = blobs[1]

        def bucket_for(storage_self):
            return dst_bucket if storage_self.bucket_name == 'pglive-kyc' else src_bucket

        with override_settings(STORAGES=storages_cfg), \
             mock.patch.object(GoogleCloudStorage, 'exists', autospec=True,
                               side_effect=lambda s, n: s.bucket_name == 'pglive-kyc'), \
             mock.patch('storages.backends.gcloud.GoogleCloudStorage.bucket', new=property(bucket_for)):
            out = io.StringIO()
            call_command(
                'backfill_kyc_documents', '--delete-source', '--purge-orphaned-legacy', stdout=out,
            )

        self.assertEqual(deleted_calls, [(key, 101), (key, 102), (orphan_key, 201)])
        self.assertIn('deleted_generations=2', out.getvalue())
        self.assertIn('purged_orphaned_generations=1', out.getvalue())
        self.assertIn('legacy_media_live=0 legacy_media_noncurrent=0', out.getvalue())
        self.assertIn('soft-delete retention', out.getvalue())
        self.assertNotIn('versioned.pdf', out.getvalue())
        self.assertNotIn('old_orphan.pdf', out.getvalue())

    def test_backfill_fails_if_referenced_object_is_missing_from_both_storages(self):
        missing_key = f'residents/{self.tenant.id}/{self.resident.id}/missing.pdf'
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=self.resident.pk).update(pan_document=missing_key)

        with override_settings(STORAGES=self._storages()):
            with self.assertRaises(CommandError) as ctx:
                call_command('backfill_kyc_documents', stdout=io.StringIO())
        self.assertIn('missing=1', str(ctx.exception))
        self.assertNotIn('missing.pdf', str(ctx.exception))

    def test_backfill_skips_cleanly_when_kyc_storage_is_unset_and_supports_gcs_copy_blob(self):
        out = io.StringIO()
        call_command('backfill_kyc_documents', stdout=out)
        self.assertIn('nothing to backfill', out.getvalue())

        creds = _fake_service_account()
        storages_cfg = {
            **settings.STORAGES,
            'default': {
                'BACKEND': 'storages.backends.gcloud.GoogleCloudStorage',
                'OPTIONS': {'bucket_name': 'pglive-media', 'project_id': 'test', 'credentials': creds, 'iam_sign_blob': False},
            },
            'kyc': {
                'BACKEND': 'storages.backends.gcloud.GoogleCloudStorage',
                'OPTIONS': {'bucket_name': 'pglive-kyc', 'project_id': 'test', 'credentials': creds, 'iam_sign_blob': False},
            },
        }
        key = f'residents/{self.tenant.id}/{self.resident.id}/doc.pdf'
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=self.resident.pk).update(aadhaar_document=key)

        src_bucket = mock.Mock(name='media_bucket')
        dst_bucket = mock.Mock(name='kyc_bucket')
        copied = {'done': False}
        src_blob = mock.Mock(name='src_blob')

        def fake_copy_blob(blob, target_bucket, new_name=None):
            self.assertIs(blob, src_blob)
            self.assertIs(target_bucket, dst_bucket)
            self.assertEqual(new_name, key)
            copied['done'] = True

        src_bucket.get_blob.return_value = src_blob
        src_bucket.copy_blob.side_effect = fake_copy_blob
        src_bucket.list_blobs.return_value = []
        dst_bucket.blob.side_effect = lambda name: mock.Mock(exists=lambda: copied['done'])

        def bucket_for(storage_self):
            return dst_bucket if storage_self.bucket_name == 'pglive-kyc' else src_bucket

        with override_settings(STORAGES=storages_cfg), \
             mock.patch.object(GoogleCloudStorage, 'exists', autospec=True,
                               side_effect=lambda s, n: (s.bucket_name == 'pglive-media') or copied['done']), \
             mock.patch('storages.backends.gcloud.GoogleCloudStorage.bucket',
                        new=property(bucket_for)):
            gcs_out = io.StringIO()
            call_command('backfill_kyc_documents', stdout=gcs_out)
        self.assertIn('copied=1', gcs_out.getvalue())
        self.assertTrue(copied['done'])


def _make_fake_bucket(*, versioning=False, soft_delete_seconds=0, ubla=True, pap='enforced',
                      perms=None, existing_keys=()):
    bucket = mock.Mock()
    bucket.name = 'pglive-test-kyc'
    bucket.versioning_enabled = versioning
    bucket.soft_delete_policy = mock.Mock(retention_duration_seconds=soft_delete_seconds)
    bucket.iam_configuration = mock.Mock(
        uniform_bucket_level_access_enabled=ubla,
        public_access_prevention=pap,
    )
    if perms is None:
        perms = [
            'storage.objects.create',
            'storage.objects.get',
            'storage.objects.delete',
            'storage.objects.list',
        ]
    bucket.test_iam_permissions.return_value = perms

    def make_blob(name):
        blob = mock.Mock()
        blob.name = name
        blob.exists.return_value = name in existing_keys
        blob.generate_signed_url.return_value = (
            f'https://storage.googleapis.com/pglive-test-kyc/{name}?X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Expires=60&X-Goog-Signature=deadbeef'
        )
        return blob

    bucket.blob.side_effect = make_blob
    bucket.get_blob.side_effect = lambda name, **kwargs: make_blob(name) if name in existing_keys else None
    bucket.list_blobs.return_value = []
    return bucket


class CheckKycStorageCommandTests(ResidentAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.prop = self.create_property(self.tenant)
        self.resident = self.create_resident(self.prop, first_name='Ravi', phone='9000000001')

    def _gcs_storages(self, bucket_name='pglive-test-kyc', iam_sign_blob=False, sa_email='sa-api@test.iam.gserviceaccount.com'):
        creds = _fake_service_account()
        return {
            **settings.STORAGES,
            'default': {
                'BACKEND': 'storages.backends.gcloud.GoogleCloudStorage',
                'OPTIONS': {'bucket_name': 'pglive-test-media', 'project_id': 'test', 'credentials': creds, 'iam_sign_blob': False},
            },
            'kyc': {
                'BACKEND': 'storages.backends.gcloud.GoogleCloudStorage',
                'OPTIONS': {
                    'bucket_name': bucket_name, 'project_id': 'test', 'credentials': creds,
                    'querystring_auth': True, 'default_acl': None,
                    'expiration': timedelta(seconds=300), 'file_overwrite': False,
                    'iam_sign_blob': iam_sign_blob, 'sa_email': sa_email,
                },
            },
        }

    def test_skips_when_disabled_and_unconfigured_unless_required(self):
        out = io.StringIO()
        with override_settings(KYC_UPLOADS_ENABLED=False, GS_KYC_BUCKET_NAME=''):
            call_command('check_kyc_storage', stdout=out)
        self.assertIn('skipped', out.getvalue())

        with override_settings(KYC_UPLOADS_ENABLED=False, GS_KYC_BUCKET_NAME=''):
            with self.assertRaises(CommandError) as ctx:
                call_command('check_kyc_storage', '--require', stdout=io.StringIO())
        self.assertIn('GS_KYC_BUCKET_NAME must be configured', str(ctx.exception))

    def test_happy_path_passes_all_checks(self):
        key = f'residents/{self.tenant.id}/{self.resident.id}/ok.pdf'
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=self.resident.pk).update(aadhaar_document=key)
        bucket = _make_fake_bucket(existing_keys={key})
        out = io.StringIO()
        with override_settings(
            KYC_UPLOADS_ENABLED=True, GS_BUCKET_NAME='pglive-test-media',
            GS_KYC_BUCKET_NAME='pglive-test-kyc', STORAGES=self._gcs_storages(),
        ), mock.patch.dict('os.environ', {'EXPECT_KYC_UPLOADS_ENABLED': 'true'}), \
             mock.patch.object(GoogleCloudStorage, 'bucket', new=property(lambda s: bucket)):
            call_command('check_kyc_storage', '--require', stdout=out)
        self.assertIn('preflight passed', out.getvalue())
        self.assertIn('legacy_media_live=0, legacy_media_noncurrent=0, legacy_media_soft_deleted=0', out.getvalue())
        bucket.reload.assert_called_once()

    def test_detects_bad_bucket_config_missing_permissions_signing_error_and_unmigrated_docs(self):
        key = f'residents/{self.tenant.id}/{self.resident.id}/unmigrated.pdf'
        with tenant_context(self.tenant.id):
            Resident.objects.filter(pk=self.resident.pk).update(aadhaar_document=key)

        bad_bucket = _make_fake_bucket(
            versioning=True,
            soft_delete_seconds=604800,
            ubla=False,
            pap='inherited',
            perms=['storage.objects.get'],
            existing_keys=set(),
        )
        with override_settings(
            KYC_UPLOADS_ENABLED=False, GS_BUCKET_NAME='pglive-test-media',
            GS_KYC_BUCKET_NAME='pglive-test-kyc', STORAGES=self._gcs_storages(iam_sign_blob=True, sa_email=''),
        ), mock.patch.dict('os.environ', {'EXPECT_KYC_UPLOADS_ENABLED': 'true'}), \
             mock.patch.object(GoogleCloudStorage, 'bucket', new=property(lambda s: bad_bucket)), \
             mock.patch.object(GoogleCloudStorage, 'url', side_effect=RuntimeError('token creator missing')):
            with self.assertRaises(CommandError) as ctx:
                call_command('check_kyc_storage', '--require', stdout=io.StringIO())
        msg = str(ctx.exception)
        self.assertIn('EXPECT_KYC_UPLOADS_ENABLED=true', msg)
        self.assertIn('GS_SA_EMAIL must be configured', msg)
        self.assertIn('object versioning enabled', msg)
        self.assertIn('soft-delete retention=604800s', msg)
        self.assertIn('uniform bucket-level access', msg)
        self.assertIn('public access prevention', msg)
        self.assertIn('storage.objects.create', msg)
        self.assertIn('KYC URL signing check failed', msg)
        self.assertIn('1 resident KYC document(s)', msg)
        self.assertNotIn('unmigrated.pdf', msg)

    def test_reports_missing_bucket_and_missing_metadata_permission_clearly(self):
        for exc, expected_fragment in (
            (NotFound('missing'), 'does not exist; run infra/20-data.sh'),
            (Forbidden('denied'), 'storage.buckets.get'),
        ):
            bucket = _make_fake_bucket()
            bucket.reload.side_effect = exc
            with override_settings(
                KYC_UPLOADS_ENABLED=True, GS_BUCKET_NAME='pglive-test-media',
                GS_KYC_BUCKET_NAME='pglive-test-kyc', STORAGES=self._gcs_storages(),
            ), mock.patch.object(GoogleCloudStorage, 'bucket', new=property(lambda s, b=bucket: b)):
                with self.assertRaises(CommandError) as ctx:
                    call_command('check_kyc_storage', stdout=io.StringIO())
            self.assertIn(expected_fragment, str(ctx.exception))

    def test_reports_and_optionally_fails_when_legacy_media_objects_remain(self):
        kyc_bucket = _make_fake_bucket()
        media_bucket = _make_fake_bucket()
        live_blob = mock.Mock(time_deleted=None)
        noncurrent_blob = mock.Mock(time_deleted='2026-11-01T00:00:00Z')
        soft_blob = mock.Mock(time_deleted='2026-11-02T00:00:00Z')

        def media_list(prefix='', versions=None, soft_deleted=None):
            if soft_deleted:
                return [soft_blob]
            return [live_blob, noncurrent_blob]

        media_bucket.list_blobs.side_effect = media_list

        def bucket_for(storage_self):
            return kyc_bucket if storage_self.bucket_name == 'pglive-test-kyc' else media_bucket

        with override_settings(
            KYC_UPLOADS_ENABLED=True, GS_BUCKET_NAME='pglive-test-media',
            GS_KYC_BUCKET_NAME='pglive-test-kyc', STORAGES=self._gcs_storages(),
        ), mock.patch.dict('os.environ', {'EXPECT_KYC_UPLOADS_ENABLED': 'true'}), \
             mock.patch.object(GoogleCloudStorage, 'bucket', new=property(bucket_for)):
            out = io.StringIO()
            call_command('check_kyc_storage', '--require', stdout=out)
            self.assertIn('legacy_media_live=1, legacy_media_noncurrent=1, legacy_media_soft_deleted=1', out.getvalue())

            with self.assertRaises(CommandError) as ctx:
                call_command('check_kyc_storage', '--require', '--fail-on-legacy-media', stdout=io.StringIO())
        self.assertIn('1 live and 1 noncurrent legacy KYC object(s)', str(ctx.exception))
