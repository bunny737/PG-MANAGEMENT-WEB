import re
import shutil
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from google.api_core.exceptions import GoogleAPIError
from storages.backends.gcloud import GoogleCloudStorage

from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.storage import get_kyc_storage, signed_url
from apps.core.tenancy import tenant_context
from apps.core.test_deployment import _fake_service_account
from apps.residents.models import Resident

from .base import ResidentAPITestCase

_MEDIA_ROOT = tempfile.mkdtemp()
PDF = b'%PDF-1.4 ' + b'0' * 32


@override_settings(MEDIA_ROOT=_MEDIA_ROOT, KYC_UPLOADS_ENABLED=True)
class ResidentDocumentUploadTests(ResidentAPITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        super().setUp()
        cache.clear()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)

    def test_owner_uploads_aadhaar_document_on_create(self):
        self.authenticate(self.owner)
        aadhaar_file = SimpleUploadedFile('aadhaar.pdf', PDF, content_type='application/pdf')

        response = self.client.post(reverse('resident-list'), {
            'property': str(self.property.id), 'first_name': 'Ravi', 'phone': '9000000001',
            'aadhaar_number': '1234-5678-9012', 'aadhaar_document': aadhaar_file,
        }, format='multipart')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertIs(response.data['has_aadhaar_document'], True)
        self.assertIs(response.data['has_pan_document'], False)
        self.assertNotIn('aadhaar_document', response.data)
        self.assertNotIn('pan_document', response.data)

        resident_id = response.data['id']
        with tenant_context(self.tenant.id):
            key = Resident.objects.get(pk=resident_id).aadhaar_document.name
        self.assertRegex(key, rf'^residents/{self.tenant.id}/{resident_id}/[0-9a-f]{{32}}\.pdf$')
        self.assertNotIn('aadhaar.pdf', key)

        download = self.client.get(reverse('resident-document-url', args=[resident_id, 'aadhaar_document']))
        self.assertEqual(download.status_code, 200, download.data)
        self.assertTrue(download.data['url'].startswith('http://testserver/media/residents/'))
        self.assertEqual(download.data['expires_in'], settings.MEDIA_URL_TTL_SECONDS)
        expires_at = datetime.fromisoformat(download.data['expires_at'])
        self.assertGreater(expires_at, timezone.now())

    def test_document_field_is_optional(self):
        self.authenticate(self.owner)

        response = self.client.post(reverse('resident-list'), {
            'property': str(self.property.id), 'first_name': 'Ravi', 'phone': '9000000001',
        })

        self.assertEqual(response.status_code, 201)
        self.assertIs(response.data['has_aadhaar_document'], False)
        self.assertIs(response.data['has_pan_document'], False)
        self.assertNotIn('aadhaar_document', response.data)
        self.assertNotIn('pan_document', response.data)

    def test_list_endpoint_skips_url_signing_and_preserves_flags_and_redaction(self):
        self.authenticate(self.owner)
        floor = self.create_floor(self.property)
        room = self.create_room(floor)
        bed = self.create_bed(room)
        created = self.client.post(reverse('resident-list'), {
            'property': str(self.property.id), 'first_name': 'Ravi', 'phone': '9000000001',
            'status': 'reserved',
            'aadhaar_document': SimpleUploadedFile('aadhaar.pdf', PDF),
        }, format='multipart')
        self.assertEqual(created.status_code, 201, created.data)
        with tenant_context(self.tenant.id):
            resident = Resident.objects.get(pk=created.data['id'])
        self.check_in(resident, bed, security_deposit_amount=Decimal('5000.00'))

        with mock.patch('django.core.files.storage.FileSystemStorage.url', side_effect=AssertionError('must not sign')), \
             mock.patch('apps.residents.views.signed_url', side_effect=AssertionError('must not sign')):
            listed = self.client.get(reverse('resident-list'))
            self.assertEqual(listed.status_code, 200)
            row = next(r for r in listed.data if r['id'] == str(resident.id))
            self.assertIs(row['has_aadhaar_document'], True)
            self.assertIs(row['has_pan_document'], False)
            self.assertNotIn('aadhaar_document', row)
            self.assertNotIn('pan_document', row)
            self.assertIn('contracted_rent', row)

            detail = self.client.get(reverse('resident-detail', args=[resident.id]))
            self.assertEqual(detail.status_code, 200)
            self.assertIs(detail.data['has_aadhaar_document'], True)
            self.assertNotIn('aadhaar_document', detail.data)

            receptionist = self.create_receptionist(self.tenant)
            self.assign_staff(receptionist, self.property)
            self.authenticate(receptionist)
            rec_list = self.client.get(reverse('resident-list'))
            self.assertEqual(rec_list.status_code, 200)
            rec_row = next(r for r in rec_list.data if r['id'] == str(resident.id))
            self.assertIs(rec_row['has_aadhaar_document'], True)
            self.assertNotIn('contracted_rent', rec_row)
            self.assertNotIn('security_deposit_amount', rec_row)

    def test_download_endpoint_permissions_scoping_and_errors(self):
        self.authenticate(self.owner)
        created = self.client.post(reverse('resident-list'), {
            'property': str(self.property.id), 'first_name': 'Ravi', 'phone': '9000000001',
            'aadhaar_document': SimpleUploadedFile('aadhaar.pdf', PDF),
        }, format='multipart')
        resident_id = created.data['id']

        # Unknown field or unuploaded field -> 404
        self.assertEqual(
            self.client.get(reverse('resident-document-url', args=[resident_id, 'passport_document'])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse('resident-document-url', args=[resident_id, 'pan_document'])).status_code,
            404,
        )

        # Receptionist (view_resident_profile) can issue a download URL
        receptionist = self.create_receptionist(self.tenant)
        self.assign_staff(receptionist, self.property)
        self.authenticate(receptionist)
        self.assertEqual(
            self.client.get(reverse('resident-document-url', args=[resident_id, 'aadhaar_document'])).status_code,
            200,
        )

        # Unassigned manager gets 404; resident role gets 403; cross-tenant owner gets 404
        manager = self.create_manager(self.tenant)
        self.authenticate(manager)
        self.assertEqual(
            self.client.get(reverse('resident-document-url', args=[resident_id, 'aadhaar_document'])).status_code,
            404,
        )
        res_user = self.create_user(self.tenant, Role.RESIDENT, 'res@example.com')
        self.authenticate(res_user)
        self.assertEqual(
            self.client.get(reverse('resident-document-url', args=[resident_id, 'aadhaar_document'])).status_code,
            403,
        )
        other_owner = self.create_owner(self.create_tenant('Other PG'), email='other@example.com')
        self.authenticate(other_owner)
        self.assertEqual(
            self.client.get(reverse('resident-document-url', args=[resident_id, 'aadhaar_document'])).status_code,
            404,
        )

    def test_download_endpoint_handles_signing_and_audit_failures_safely(self):
        self.authenticate(self.owner)
        created = self.client.post(reverse('resident-list'), {
            'property': str(self.property.id), 'first_name': 'Ravi', 'phone': '9000000001',
            'aadhaar_document': SimpleUploadedFile('aadhaar.pdf', PDF),
        }, format='multipart')
        resident_id = created.data['id']
        url = reverse('resident-document-url', args=[resident_id, 'aadhaar_document'])

        with tenant_context(self.tenant.id):
            secret_key = Resident.objects.get(pk=resident_id).aadhaar_document.name

        secret_msg = f'sa@pglive.iam.gserviceaccount.com failed signing {secret_key}'
        with mock.patch('apps.residents.views.signed_url', side_effect=GoogleAPIError(secret_msg)), \
             self.assertLogs('apps.residents.views', level='ERROR') as logs:
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data['code'], 'DOCUMENT_URL_UNAVAILABLE')
        self.assertNotIn('pglive.iam.gserviceaccount.com', str(resp.data))
        self.assertNotIn(secret_key, str(resp.data))
        self.assertTrue(any('kyc_signed_url_failed' in line for line in logs.output))
        self.assertFalse(any(secret_key in line for line in logs.output))
        with tenant_context(self.tenant.id):
            self.assertFalse(AuditLog.objects.filter(action='resident.kyc_document_url_issued').exists())

        # Mandatory audit: if audit logging fails, never return a signed URL.
        with mock.patch('apps.residents.views.audit_log.record', side_effect=RuntimeError('audit db down')):
            with self.assertRaises(RuntimeError):
                self.client.get(url)

    def test_download_endpoint_is_rate_limited(self):
        from rest_framework.throttling import SimpleRateThrottle

        self.assertEqual(SimpleRateThrottle.THROTTLE_RATES['kyc_document_download'], '60/min')
        self.authenticate(self.owner)
        created = self.client.post(reverse('resident-list'), {
            'property': str(self.property.id), 'first_name': 'Ravi', 'phone': '9000000001',
            'aadhaar_document': SimpleUploadedFile('aadhaar.pdf', PDF),
        }, format='multipart')
        url = reverse('resident-document-url', args=[created.data['id'], 'aadhaar_document'])
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {'kyc_document_download': '2/min'}):
            self.assertEqual(self.client.get(url).status_code, 200)
            self.assertEqual(self.client.get(url).status_code, 200)
            self.assertEqual(self.client.get(url).status_code, 429)

    def test_gcs_backend_contract_handles_long_special_filenames_and_kyc_bucket(self):
        creds = _fake_service_account()
        kyc_gcs = GoogleCloudStorage(
            bucket_name='pglive-test-kyc', project_id='test', credentials=creds,
            querystring_auth=True, default_acl=None, expiration=timedelta(seconds=300),
            file_overwrite=False, iam_sign_blob=False,
        )
        default_gcs = GoogleCloudStorage(
            bucket_name='pglive-test-media', project_id='test', credentials=creds,
            querystring_auth=True, default_acl=None, expiration=timedelta(seconds=300),
            file_overwrite=False, iam_sign_blob=False,
        )
        saved_blobs = []
        fake_bucket = mock.Mock()
        fake_bucket.name = 'pglive-test-kyc'
        fake_bucket.get_blob.return_value = None  # file doesn't exist yet -> no collision suffix needed

        def fake_upload(blob_self, file_obj, **kwargs):
            saved_blobs.append((blob_self.name, blob_self.bucket.name, file_obj.read(), kwargs))

        storages_cfg = {
            **settings.STORAGES,
            'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            'kyc': {
                'BACKEND': 'storages.backends.gcloud.GoogleCloudStorage',
                'OPTIONS': {
                    'bucket_name': 'pglive-test-kyc', 'project_id': 'test', 'credentials': creds,
                    'querystring_auth': True, 'default_acl': None,
                    'expiration': timedelta(seconds=300), 'file_overwrite': False, 'iam_sign_blob': False,
                },
            },
        }
        long_name = 'my.very.long aadhaar scan (final copy) #1234567890_extra_chars.pdf'
        with override_settings(STORAGES=storages_cfg):
            storage = get_kyc_storage()
            self.assertIsInstance(storage, GoogleCloudStorage)
            self.assertEqual(storage.bucket_name, 'pglive-test-kyc')
            self.assertNotEqual(storage.bucket_name, default_gcs.bucket_name)

            with mock.patch.object(GoogleCloudStorage, 'bucket', new_callable=mock.PropertyMock, return_value=fake_bucket), \
                 mock.patch('storages.backends.gcloud.Blob.upload_from_file', autospec=True, side_effect=fake_upload):
                resident = Resident(tenant_id=self.tenant.id, property=self.property, first_name='Ravi', phone='9000000001')
                resident.aadhaar_document.save(long_name, SimpleUploadedFile(long_name, PDF), save=False)
                key = resident.aadhaar_document.name

            self.assertLessEqual(len(key), 255)
            self.assertTrue(re.match(
                rf'^residents/{self.tenant.id}/{resident.id}/[0-9a-f]{{32}}\.pdf$', key,
            ), key)
            self.assertEqual(len(saved_blobs), 1)
            self.assertEqual(saved_blobs[0][0], key)
            self.assertEqual(saved_blobs[0][1], 'pglive-test-kyc')
            self.assertEqual(saved_blobs[0][2], PDF)

            field_file = mock.Mock(storage=kyc_gcs)
            field_file.name = key
            url = signed_url(field_file, ttl_seconds=300)
            self.assertTrue(url.startswith(f'https://storage.googleapis.com/pglive-test-kyc/{key}'))
            params = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            self.assertEqual(params['X-Goog-Expires'], '300')
            self.assertIn('X-Goog-Signature', params)

