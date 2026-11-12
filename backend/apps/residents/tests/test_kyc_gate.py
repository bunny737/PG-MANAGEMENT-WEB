import shutil
import tempfile
from unittest import mock

from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.residents.models import Resident

from .base import ResidentAPITestCase

_MEDIA_ROOT = tempfile.mkdtemp()

PDF = b'%PDF-1.4 ' + b'0' * 32
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 32
JPEG = b'\xff\xd8\xff\xe0' + b'0' * 32
WEBP = b'RIFF\x00\x00\x00\x00WEBPVP8 ' + b'0' * 32
EXECUTABLE = b'MZ\x90\x00 not a document'


class KycTestCase(ResidentAPITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant)
        self.property = self.create_property(self.tenant)
        self.authenticate(self.owner)

    def payload(self, **files):
        return {'property': str(self.property.id), 'first_name': 'Ravi', 'phone': '9000000001', **files}

    def create(self, **files):
        return self.client.post(reverse('resident-list'), self.payload(**files), format='multipart')

    def patch(self, resident_id, data, format='multipart'):
        return self.client.patch(reverse('resident-detail', args=[resident_id]), data, format=format)

    @staticmethod
    def doc(name, content):
        return SimpleUploadedFile(name, content)

    def resident_count(self):
        with tenant_context(self.tenant.id):
            return Resident.objects.count()


@override_settings(MEDIA_ROOT=_MEDIA_ROOT, KYC_UPLOADS_ENABLED=True, KYC_DOCUMENT_MAX_BYTES=1024)
class KycUploadsEnabledTests(KycTestCase):
    def test_accepts_pdf_jpeg_and_png(self):
        for index, (name, content) in enumerate(
            [('a.pdf', PDF), ('a.jpg', JPEG), ('a.png', PNG)]
        ):
            response = self.client.post(
                reverse('resident-list'),
                self.payload(first_name=f'R{index}', phone=f'90000000{index:02d}',
                             aadhaar_document=self.doc(name, content), pan_document=self.doc(name, content)),
                format='multipart',
            )
            self.assertEqual(response.status_code, 201, response.data)
            self.assertIs(response.data['has_aadhaar_document'], True)
            self.assertIs(response.data['has_pan_document'], True)
            self.assertNotIn('aadhaar_document', response.data)
            self.assertNotIn('pan_document', response.data)

    def test_webp_is_not_in_the_approved_kyc_set(self):
        # apps.core.uploads also backs expenses, which does accept WebP — KYC passes its own
        # narrower allowed_types, since only PDF/JPEG/PNG were approved for identity documents.
        response = self.create(aadhaar_document=self.doc('a.webp', WEBP))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['aadhaar_document'][0].code, 'document_type_not_allowed')

    def test_clearing_a_document_deletes_the_stored_file(self):
        created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        with tenant_context(self.tenant.id):
            stored = Resident.objects.get(pk=created.data['id']).aadhaar_document
            storage, name = stored.storage, stored.name
        self.assertTrue(storage.exists(name))
        with self.captureOnCommitCallbacks(execute=True):
            cleared = self.patch(created.data['id'], {'aadhaar_document': None}, format='json')
        self.assertEqual(cleared.status_code, 200, cleared.data)
        self.assertFalse(storage.exists(name))

    def test_replacing_a_document_deletes_the_old_file_only_after_commit(self):
        created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        with tenant_context(self.tenant.id):
            stored = Resident.objects.get(pk=created.data['id']).aadhaar_document
            storage, first = stored.storage, stored.name
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            replaced = self.patch(created.data['id'], {'aadhaar_document': self.doc('b.pdf', PDF)})
        self.assertEqual(replaced.status_code, 200, replaced.data)
        self.assertTrue(storage.exists(first))  # nothing is deleted before the commit
        for callback in callbacks:
            callback()
        self.assertFalse(storage.exists(first))
        with tenant_context(self.tenant.id):
            second = Resident.objects.get(pk=created.data['id']).aadhaar_document.name
        self.assertTrue(storage.exists(second))

    def test_an_invalid_replacement_does_not_delete_the_existing_file(self):
        created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        with tenant_context(self.tenant.id):
            stored = Resident.objects.get(pk=created.data['id']).aadhaar_document
            storage, name = stored.storage, stored.name
        with self.captureOnCommitCallbacks(execute=True):
            bad = self.patch(created.data['id'], {'aadhaar_document': self.doc('x.pdf', EXECUTABLE)})
        self.assertEqual(bad.status_code, 400)
        self.assertTrue(storage.exists(name))

    def test_the_real_type_is_checked_not_the_filename(self):
        for field in ('aadhaar_document', 'pan_document'):
            response = self.create(**{field: self.doc('scan.pdf', EXECUTABLE)})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data[field][0].code, 'document_type_not_allowed')
        self.assertEqual(self.resident_count(), 0)

    def test_oversized_files_are_rejected(self):
        response = self.create(aadhaar_document=self.doc('big.pdf', PDF + b'0' * 2048))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['aadhaar_document'][0].code, 'document_too_large')

    def test_a_replacement_is_validated_and_a_bad_one_keeps_the_stored_file(self):
        created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        with tenant_context(self.tenant.id):
            before_name = Resident.objects.get(pk=created.data['id']).aadhaar_document.name
        bad = self.patch(created.data['id'], {'aadhaar_document': self.doc('x.pdf', EXECUTABLE)})
        self.assertEqual(bad.status_code, 400)
        with tenant_context(self.tenant.id):
            after = Resident.objects.get(pk=created.data['id']).aadhaar_document
            self.assertEqual(after.name, before_name)
            self.assertTrue(after.storage.exists(before_name))
        detail = self.client.get(reverse('resident-detail', args=[created.data['id']]))
        self.assertIs(detail.data['has_aadhaar_document'], True)

    def test_a_resident_of_another_tenant_cannot_be_touched(self):
        created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        other = self.create_owner(self.create_tenant('Other PG'), email='other@example.com')
        self.authenticate(other)
        response = self.patch(created.data['id'], {'pan_document': self.doc('p.pdf', PDF)})
        self.assertEqual(response.status_code, 404)

    def test_kyc_lifecycle_emits_metadata_only_audit_events_with_sniffed_type(self):
        spoofed_pdf = SimpleUploadedFile('secret_aadhaar_1234.pdf', PDF, content_type='text/plain')
        created = self.create(aadhaar_number='1234-5678-9012', aadhaar_document=spoofed_pdf)
        self.assertEqual(created.status_code, 201, created.data)
        resident_id = created.data['id']

        replaced = self.patch(resident_id, {'aadhaar_document': SimpleUploadedFile('my_pan_scan.png', PNG, content_type='application/octet-stream')})
        self.assertEqual(replaced.status_code, 200, replaced.data)

        download = self.client.get(reverse('resident-document-url', args=[resident_id, 'aadhaar_document']))
        self.assertEqual(download.status_code, 200)

        with self.captureOnCommitCallbacks(execute=True):
            removed = self.patch(resident_id, {'aadhaar_document': None}, format='json')
        self.assertEqual(removed.status_code, 200)
        self.assertIs(removed.data['has_aadhaar_document'], False)

        with tenant_context(self.tenant.id):
            logs = list(
                AuditLog.objects.filter(object_type='Resident', object_id=str(resident_id))
                .order_by('created_at')
            )
            resident_obj = Resident.objects.get(pk=resident_id)

        by_action = {log.action: log for log in logs}
        self.assertIn('resident.kyc_document_uploaded', by_action)
        self.assertIn('resident.kyc_document_replaced', by_action)
        self.assertIn('resident.kyc_document_url_issued', by_action)
        self.assertIn('resident.kyc_document_removed', by_action)

        self.assertEqual(
            by_action['resident.kyc_document_uploaded'].after,
            {'field': 'aadhaar_document', 'content_type': 'application/pdf'},
        )
        self.assertEqual(by_action['resident.kyc_document_replaced'].before, {'field': 'aadhaar_document'})
        self.assertEqual(
            by_action['resident.kyc_document_replaced'].after,
            {'field': 'aadhaar_document', 'content_type': 'image/png'},
        )
        self.assertEqual(
            by_action['resident.kyc_document_url_issued'].after,
            {'field': 'aadhaar_document'},
        )
        self.assertEqual(by_action['resident.kyc_document_removed'].before, {'field': 'aadhaar_document'})
        self.assertIsNone(by_action['resident.kyc_document_removed'].after)

        # Never record filenames, signed URLs, object keys, or Aadhaar/PAN numbers in audit metadata.
        serialized = str([(l.action, l.before, l.after) for l in logs])
        for forbidden in ('secret_aadhaar', 'my_pan_scan', '1234-5678-9012', 'http://', 'https://', str(resident_obj.id)):
            if forbidden == str(resident_obj.id):
                # object_id holds the UUID, but `before`/`after` must not hold storage keys/URLs
                self.assertNotIn(f'residents/{self.tenant.id}', serialized)
            else:
                self.assertNotIn(forbidden, serialized)

    def test_storage_save_failure_leaves_no_row_and_preserves_prior_file(self):
        with mock.patch.object(FileSystemStorage, '_save', side_effect=OSError('gcs upload failed')):
            with self.assertRaises(OSError):
                self.create(aadhaar_document=self.doc('a.pdf', PDF))
        self.assertEqual(self.resident_count(), 0)

        created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        resident_id = created.data['id']
        with tenant_context(self.tenant.id):
            orig = Resident.objects.get(pk=resident_id).aadhaar_document
            orig_storage, orig_name = orig.storage, orig.name

        with mock.patch.object(FileSystemStorage, '_save', side_effect=OSError('gcs upload failed')):
            with self.assertRaises(OSError):
                self.patch(resident_id, {'aadhaar_document': self.doc('b.pdf', PDF)})
        with tenant_context(self.tenant.id):
            current = Resident.objects.get(pk=resident_id).aadhaar_document.name
        self.assertEqual(current, orig_name)
        self.assertTrue(orig_storage.exists(orig_name))

    def test_db_or_audit_failure_after_upload_cleans_up_new_blob_best_effort(self):
        # 1. Create path: audit failure triggers best-effort delete of written blob
        saved_names = []
        orig_save = FileSystemStorage._save

        def tracking_save(storage_self, name, content):
            saved = orig_save(storage_self, name, content)
            saved_names.append(saved)
            return saved

        with mock.patch.object(FileSystemStorage, '_save', autospec=True, side_effect=tracking_save), \
             mock.patch('apps.residents.services.audit_log.record', side_effect=RuntimeError('audit fail')):
            with self.assertRaisesRegex(RuntimeError, 'audit fail'):
                self.create(aadhaar_document=self.doc('a.pdf', PDF))
        self.assertEqual(self.resident_count(), 0)
        self.assertEqual(len(saved_names), 1)
        self.assertFalse(FileSystemStorage(location=_MEDIA_ROOT).exists(saved_names[0]))

        # 2. Update path + cleanup failure: original exception still raised & sanitized error logged
        saved_names.clear()
        created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        resident_id = created.data['id']
        with tenant_context(self.tenant.id):
            first_name = Resident.objects.get(pk=resident_id).aadhaar_document.name

        with mock.patch.object(FileSystemStorage, '_save', autospec=True, side_effect=tracking_save), \
             mock.patch('apps.residents.services.audit_log.record', side_effect=RuntimeError('db audit fail')), \
             mock.patch.object(FileSystemStorage, 'delete', side_effect=OSError('cleanup failed')), \
             self.assertLogs('apps.residents.services', level='ERROR') as logs:
            with self.assertRaisesRegex(RuntimeError, 'db audit fail'):
                self.patch(resident_id, {'aadhaar_document': self.doc('b.pdf', PDF)})

        with tenant_context(self.tenant.id):
            self.assertEqual(Resident.objects.get(pk=resident_id).aadhaar_document.name, first_name)
        self.assertTrue(any('kyc_orphan_cleanup_failed' in line for line in logs.output))
        # Sanitized: never log the object key
        self.assertFalse(any(saved_names[-1] in line for line in logs.output))

    def test_post_commit_old_blob_delete_failure_is_logged_not_raised(self):
        created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        resident_id = created.data['id']
        with tenant_context(self.tenant.id):
            first_name = Resident.objects.get(pk=resident_id).aadhaar_document.name

        with mock.patch.object(FileSystemStorage, 'delete', side_effect=OSError('gcs delete timeout')), \
             self.assertLogs('apps.core.storage', level='ERROR') as logs:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.patch(resident_id, {'aadhaar_document': self.doc('b.pdf', PDF)})

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(any('storage_post_commit_delete_failed' in line for line in logs.output))
        self.assertFalse(any(first_name in line for line in logs.output))
        with tenant_context(self.tenant.id):
            second_name = Resident.objects.get(pk=resident_id).aadhaar_document.name
        self.assertNotEqual(second_name, first_name)


@override_settings(MEDIA_ROOT=_MEDIA_ROOT, KYC_UPLOADS_ENABLED=False)
class KycUploadsDisabledTests(KycTestCase):
    def test_a_new_document_is_refused_on_create_and_nothing_is_created(self):
        for field in ('aadhaar_document', 'pan_document'):
            response = self.create(**{field: self.doc('a.pdf', PDF)})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data[field][0].code, 'kyc_uploads_disabled')
        self.assertEqual(self.resident_count(), 0)

    def test_creating_a_resident_without_documents_still_works(self):
        response = self.create()
        self.assertEqual(response.status_code, 201)
        self.assertIs(response.data['has_aadhaar_document'], False)
        self.assertNotIn('aadhaar_document', response.data)

    def test_a_new_document_is_refused_on_update_even_with_a_valid_file(self):
        resident = self.create().data
        response = self.patch(resident['id'], {'pan_document': self.doc('p.pdf', PDF)})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['pan_document'][0].code, 'kyc_uploads_disabled')
        self.assertIs(self.client.get(reverse('resident-detail', args=[resident['id']])).data['has_pan_document'], False)

    def test_text_fields_can_still_be_edited(self):
        resident = self.create().data
        response = self.patch(resident['id'], {'aadhaar_number': '1234-5678-9012', 'first_name': 'Ravi K'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['first_name'], 'Ravi K')

    def test_stored_documents_stay_readable_and_can_be_cleared(self):
        with override_settings(KYC_UPLOADS_ENABLED=True):
            created = self.create(aadhaar_document=self.doc('a.pdf', PDF))
        self.assertIs(created.data['has_aadhaar_document'], True)
        with tenant_context(self.tenant.id):
            stored = Resident.objects.get(pk=created.data['id']).aadhaar_document
            storage, name = stored.storage, stored.name

        detail = reverse('resident-detail', args=[created.data['id']])
        download = reverse('resident-document-url', args=[created.data['id'], 'aadhaar_document'])
        self.assertIs(self.client.get(detail).data['has_aadhaar_document'], True)  # still readable
        self.assertEqual(self.client.get(download).status_code, 200)

        replacement = self.patch(created.data['id'], {'aadhaar_document': self.doc('b.pdf', PDF)})
        self.assertEqual(replacement.status_code, 400)  # but not replaceable
        self.assertIs(self.client.get(detail).data['has_aadhaar_document'], True)
        self.assertTrue(storage.exists(name))

        with self.captureOnCommitCallbacks(execute=True):
            cleared = self.patch(created.data['id'], {'aadhaar_document': None}, format='json')
        self.assertEqual(cleared.status_code, 200, cleared.data)
        self.assertIs(cleared.data['has_aadhaar_document'], False)
        self.assertFalse(storage.exists(name))  # clearing deletes the file, not just the reference
        self.assertEqual(self.client.get(download).status_code, 404)

    def test_a_resident_of_another_tenant_cannot_be_touched(self):
        resident = self.create().data
        other = self.create_owner(self.create_tenant('Other PG'), email='other@example.com')
        self.authenticate(other)
        self.assertEqual(self.patch(resident['id'], {'pan_document': self.doc('p.pdf', PDF)}).status_code, 404)


class KycFlagOnMeTests(KycTestCase):
    @override_settings(KYC_UPLOADS_ENABLED=False)
    def test_me_reports_uploads_off(self):
        self.assertIs(self.client.get(reverse('auth-me')).data['kyc_uploads_enabled'], False)

    @override_settings(KYC_UPLOADS_ENABLED=True)
    def test_me_reports_uploads_on(self):
        self.assertIs(self.client.get(reverse('auth-me')).data['kyc_uploads_enabled'], True)
