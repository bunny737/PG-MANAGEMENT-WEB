"""Concurrency proofs for resident KYC document replacements (`update_resident`).

Without a Resident row lock inside `update_resident`, two concurrent PATCHes for the
same resident read the same `prior_file` before either writes, upload two new blobs,
and schedule deletion only of the original blob — leaving the first writer's replacement
permanently orphaned in GCS/storage.

Needs real commits on separate connections (`TransactionTestCase`).
"""
import os
import shutil
import tempfile
import threading
import time

from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.serializers import LoginSerializer
from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.properties.models import Property
from apps.residents.models import Resident
from apps.subscriptions.tests.base import SubscriptionAPITestCase

_MEDIA_ROOT = tempfile.mkdtemp()
PDF = b'%PDF-1.4 ' + b'0' * 32


def _files_under(root):
    found = set()
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            found.add(os.path.relpath(os.path.join(dirpath, fname), root).replace(os.sep, '/'))
    return found


@override_settings(MEDIA_ROOT=_MEDIA_ROOT, KYC_UPLOADS_ENABLED=True, KYC_DOCUMENT_MAX_BYTES=1024)
class KycReplacementConcurrencyTests(TransactionTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def _fixture_teardown(self):
        pass

    def setUp(self):
        self.tenant = SubscriptionAPITestCase.create_tenant('KYC Concurrency Tenant')
        self.owner = SubscriptionAPITestCase.create_owner(
            self.tenant, email='kyc-race@concurrency.example.com',
        )
        self.property = SubscriptionAPITestCase.create_property(self.tenant)
        token = LoginSerializer.get_token(self.owner)
        self.auth = f'Bearer {token.access_token}'

    def tearDown(self):
        with tenant_context(is_super_admin=True):
            Resident.objects.filter(tenant_id=self.tenant.id).delete()
            Property.objects.filter(pk=self.property.pk).delete()
            AuditLog.objects.filter(tenant_id=self.tenant.id).delete()
        User.objects.filter(pk=self.owner.pk).delete()
        self.tenant.delete()

    def _client(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=self.auth)
        return client

    def _create_resident_with_aadhaar(self, phone='9100000001'):
        resp = self._client().post(
            reverse('resident-list'),
            {
                'property': str(self.property.id),
                'first_name': 'Ravi',
                'phone': phone,
                'aadhaar_document': SimpleUploadedFile('initial.pdf', PDF),
            },
            format='multipart',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data['id']

    def test_simultaneous_replacements_serialize_and_never_orphan_files(self):
        resident_id = self._create_resident_with_aadhaar('9100000010')
        with tenant_context(self.tenant.id):
            initial_key = Resident.objects.get(pk=resident_id).aadhaar_document.name

        first_in_save = threading.Event()
        orig_save = FileSystemStorage._save
        orig_update_lock = threading.local()

        def slow_first_save(storage_self, name, content):
            if getattr(orig_update_lock, 'is_first', False):
                first_in_save.set()
                time.sleep(0.15)
            return orig_save(storage_self, name, content)

        statuses = {}
        errors = []

        def worker(tag, payload_name, wait_for_first):
            try:
                if wait_for_first:
                    self.assertTrue(first_in_save.wait(timeout=5))
                else:
                    orig_update_lock.is_first = True
                resp = self._client().patch(
                    reverse('resident-detail', args=[resident_id]),
                    {'aadhaar_document': SimpleUploadedFile(payload_name, PDF)},
                    format='multipart',
                )
                statuses[tag] = resp.status_code
            except Exception as exc:  # noqa: BLE001 - surfaced via assertion below
                errors.append((tag, exc))
            finally:
                connection.close()

        from unittest import mock

        with mock.patch.object(FileSystemStorage, '_save', autospec=True, side_effect=slow_first_save):
            t1 = threading.Thread(target=worker, args=('first', 'second.pdf', False))
            t2 = threading.Thread(target=worker, args=('second', 'third.pdf', True))
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)

        self.assertEqual(errors, [], f'unexpected worker errors: {errors}')
        self.assertEqual(statuses, {'first': 200, 'second': 200})

        with tenant_context(self.tenant.id):
            final_key = Resident.objects.get(pk=resident_id).aadhaar_document.name
        self.assertNotEqual(final_key, initial_key)

        prefix = f'residents/{self.tenant.id}/{resident_id}/'
        files_on_disk = {f for f in _files_under(_MEDIA_ROOT) if f.startswith(prefix)}
        self.assertEqual(files_on_disk, {final_key})

    def test_simultaneous_aadhaar_and_pan_uploads_both_persist_cleanly(self):
        created = self._client().post(
            reverse('resident-list'),
            {'property': str(self.property.id), 'first_name': 'Sita', 'phone': '9100000011'},
            format='multipart',
        )
        self.assertEqual(created.status_code, 201, created.data)
        resident_id = created.data['id']

        barrier = threading.Barrier(2)
        statuses = {}
        errors = []

        def upload_field(field, fname):
            try:
                client = self._client()
                barrier.wait(timeout=10)
                resp = client.patch(
                    reverse('resident-detail', args=[resident_id]),
                    {field: SimpleUploadedFile(fname, PDF)},
                    format='multipart',
                )
                statuses[field] = resp.status_code
            except Exception as exc:  # noqa: BLE001 - surfaced via assertion below
                errors.append((field, exc))
            finally:
                connection.close()

        t1 = threading.Thread(target=upload_field, args=('aadhaar_document', 'aadhaar.pdf'))
        t2 = threading.Thread(target=upload_field, args=('pan_document', 'pan.pdf'))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        self.assertEqual(errors, [])
        self.assertEqual(statuses, {'aadhaar_document': 200, 'pan_document': 200})
        with tenant_context(self.tenant.id):
            resident = Resident.objects.get(pk=resident_id)
            expected = {resident.aadhaar_document.name, resident.pan_document.name}
        self.assertTrue(resident.aadhaar_document)
        self.assertTrue(resident.pan_document)
        prefix = f'residents/{self.tenant.id}/{resident_id}/'
        files_on_disk = {f for f in _files_under(_MEDIA_ROOT) if f.startswith(prefix)}
        self.assertEqual(files_on_disk, expected)

